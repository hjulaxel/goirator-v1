#!/usr/bin/env python3
"""
Warm-start model preparation for Goirator.

Supports three modes:
  1. single  - Use a single .bin.gz model directly (copy/symlink for self-play)
  2. merge   - Average weights of two .bin.gz models with matching architecture
  3. info    - Print model metadata (name, version, layer shapes)

The merged model can be used for initial self-play to generate training data
that captures knowledge from both source models.

Usage:
  python warmstart.py info model_a.bin.gz
  python warmstart.py single model_a.bin.gz -o output.bin.gz
  python warmstart.py merge model_a.bin.gz model_b.bin.gz -o merged.bin.gz [--alpha 0.5]
"""

import argparse
import gzip
import struct
import shutil


# --- .bin format parser ---
#
# The KataGo .bin format interleaves ASCII text and binary weight blocks.
# Weight blocks are prefixed with "@BIN@" followed by N little-endian floats.
# N is determined by the preceding text descriptors (e.g., conv: y*x*ic*oc).
# After the float data, a trailing "\n" follows.
#
# Key insight from desc.cpp: the C++ reader already knows numFloats from the
# layer descriptor before encountering @BIN@, and reads exactly numFloats*4 bytes.
#
# We parse by scanning for @BIN@ markers, then computing float count from
# the preceding text context. Alternatively, since each @BIN@ block is followed
# by exactly numFloats*4 bytes then "\n", and the next section starts with
# printable ASCII, we can detect the boundary by looking for the structure.
#
# Our approach: parse the layer descriptors to compute expected float counts.


def open_model(path: str):
    """Open a .bin or .bin.gz model file for reading."""
    if path.endswith(".gz"):
        return gzip.open(path, "rb")
    return open(path, "rb")


def parse_model_raw(raw: bytes):
    """
    Parse a .bin model into segments: text chunks and binary weight blocks.

    Returns a list of segments: ('text', bytes) or ('weights', bytes)
    Each 'weights' bytes is the raw float data (without @BIN@ prefix or trailing newline).

    The .bin format has @BIN@ followed by N*4 bytes of little-endian floats then \\n.
    Since the binary data can contain \\n bytes, we detect the real boundary by
    requiring the candidate \\n to be at a 4-byte-aligned offset AND followed by
    a long run (16+) of printable ASCII — astronomically unlikely in random floats.
    """
    MIN_ASCII_RUN = 16

    def is_ascii_run(start, length):
        end = min(start + length, len(raw))
        if end - start < length:
            return end >= len(raw)  # OK if at EOF
        for i in range(start, end):
            b = raw[i]
            if not (b == 0x0A or (0x20 <= b <= 0x7E)):
                return False
        return True

    segments = []
    pos = 0
    n = len(raw)

    while pos < n:
        bin_pos = raw.find(b"@BIN@", pos)

        if bin_pos == -1:
            segments.append(("text", raw[pos:]))
            break

        if bin_pos > pos:
            segments.append(("text", raw[pos:bin_pos]))

        data_start = bin_pos + 5

        # Find end of binary float data
        scan = data_start
        boundary = n  # fallback
        while scan < n:
            nl = raw.find(b"\n", scan)
            if nl == -1:
                boundary = n
                break

            # Must be on a 4-byte boundary from data_start
            if (nl - data_start) % 4 != 0:
                scan = nl + 1
                continue

            # At EOF
            if nl + 1 >= n:
                boundary = nl
                break

            # Next is @BIN@
            if raw[nl+1:nl+6] == b"@BIN@":
                boundary = nl
                break

            # Long ASCII run after newline → real boundary
            if is_ascii_run(nl + 1, MIN_ASCII_RUN):
                boundary = nl
                break

            scan = nl + 1

        weight_data = raw[data_start:boundary]
        segments.append(("weights", weight_data))
        pos = boundary + 1

    return segments


def get_meta(segments):
    """Extract metadata from the first text segment."""
    meta = {}
    first_text = b""
    for typ, data in segments:
        if typ == "text":
            first_text = data
            break

    lines = first_text.split(b"\n")
    if len(lines) >= 1:
        meta["name"] = lines[0].decode("ascii", errors="replace").strip()
    if len(lines) >= 2:
        meta["version"] = lines[1].decode("ascii", errors="replace").strip()

    weight_blocks = [(i, d) for i, (t, d) in enumerate(segments) if t == "weights"]
    meta["num_weight_blocks"] = len(weight_blocks)
    meta["total_params"] = sum(len(d) // 4 for _, d in weight_blocks)
    return meta


def write_model(f, segments):
    """Write segments back to a .bin file."""
    for typ, data in segments:
        if typ == "text":
            f.write(data)
        elif typ == "weights":
            f.write(b"@BIN@")
            f.write(data)
            f.write(b"\n")


def merge_weights(data_a: bytes, data_b: bytes, alpha: float) -> bytes:
    """Average two weight blocks: result = alpha * A + (1 - alpha) * B."""
    n = len(data_a) // 4
    assert len(data_a) == len(data_b), (
        f"Weight block size mismatch: {len(data_a)} vs {len(data_b)} bytes"
    )
    floats_a = struct.unpack(f"<{n}f", data_a)
    floats_b = struct.unpack(f"<{n}f", data_b)
    merged = [alpha * a + (1.0 - alpha) * b for a, b in zip(floats_a, floats_b)]
    return struct.pack(f"<{n}f", *merged)


# --- Commands ---

def cmd_info(args):
    """Print model metadata."""
    with open_model(args.model) as f:
        raw = f.read()
    segments = parse_model_raw(raw)
    meta = get_meta(segments)

    print(f"Model: {meta['name']}")
    print(f"Version: {meta['version']}")
    print(f"Weight blocks: {meta['num_weight_blocks']}")

    block_idx = 0
    for typ, data in segments:
        if typ == "weights":
            n_floats = len(data) // 4
            print(f"  block {block_idx:3d}: {n_floats:>10,} floats  ({len(data):>12,} bytes)")
            block_idx += 1

    print(f"Total parameters: {meta['total_params']:,}")


def cmd_single(args):
    """Copy a single model for warm-start."""
    src = args.model
    dst = args.output
    if src.endswith(".gz") and not dst.endswith(".gz"):
        with gzip.open(src, "rb") as fin, open(dst, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    elif not src.endswith(".gz") and dst.endswith(".gz"):
        with open(src, "rb") as fin, gzip.open(dst, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    else:
        shutil.copy2(src, dst)
    print(f"Copied {src} -> {dst}")


def cmd_merge(args):
    """Merge two models by averaging weights."""
    alpha = args.alpha
    print(f"Merging: alpha={alpha} (A * {alpha} + B * {1-alpha})")
    print(f"  Model A: {args.model_a}")
    print(f"  Model B: {args.model_b}")

    with open_model(args.model_a) as f:
        raw_a = f.read()
    with open_model(args.model_b) as f:
        raw_b = f.read()

    seg_a = parse_model_raw(raw_a)
    seg_b = parse_model_raw(raw_b)
    meta_a = get_meta(seg_a)
    meta_b = get_meta(seg_b)

    print(f"  A: {meta_a['name']} v{meta_a['version']} "
          f"({meta_a['num_weight_blocks']} blocks, {meta_a['total_params']:,} params)")
    print(f"  B: {meta_b['name']} v{meta_b['version']} "
          f"({meta_b['num_weight_blocks']} blocks, {meta_b['total_params']:,} params)")

    weights_a = [(i, data) for i, (typ, data) in enumerate(seg_a) if typ == "weights"]
    weights_b = [(i, data) for i, (typ, data) in enumerate(seg_b) if typ == "weights"]

    # Determine merge strategy
    if len(weights_a) == len(weights_b):
        mismatches = [
            j for j, ((_, da), (_, db)) in enumerate(zip(weights_a, weights_b))
            if len(da) != len(db)
        ]
        if not mismatches:
            print(f"\nArchitectures match perfectly. Full merge.")
            do_full_merge(seg_a, meta_a, meta_b, weights_b, alpha, args.output)
            return
        else:
            print(f"\n{len(mismatches)} block(s) differ in size. Partial merge.")
    else:
        print(f"\nDifferent block counts ({len(weights_a)} vs {len(weights_b)}). Partial merge.")
        mismatches = None

    do_partial_merge(seg_a, meta_a, meta_b, weights_a, weights_b, alpha, args.output)


def do_full_merge(seg_a, meta_a, meta_b, weights_b, alpha, output):
    """Average all weight blocks between A and B."""
    merged = []
    b_idx = 0
    for typ, data in seg_a:
        if typ == "weights":
            _, data_b = weights_b[b_idx]
            merged.append(("weights", merge_weights(data, data_b, alpha)))
            b_idx += 1
        else:
            merged.append(("text", data))

    # Update model name in first text segment
    merged = update_model_name(merged, f"merged_{meta_a['name']}_{meta_b['name']}")
    write_output(merged, output)
    meta = get_meta(merged)
    print(f"Output: {output} ({meta['total_params']:,} params)")


def do_partial_merge(seg_a, meta_a, meta_b, weights_a, weights_b, alpha, output):
    """Average only weight blocks with matching sizes, keep A's for mismatches."""
    merged_count = 0
    kept_count = 0

    merged = []
    a_idx = 0
    for typ, data in seg_a:
        if typ == "weights":
            if a_idx < len(weights_b):
                _, data_b = weights_b[a_idx]
                if len(data) == len(data_b):
                    merged.append(("weights", merge_weights(data, data_b, alpha)))
                    merged_count += 1
                else:
                    merged.append(("weights", data))
                    kept_count += 1
            else:
                merged.append(("weights", data))
                kept_count += 1
            a_idx += 1
        else:
            merged.append(("text", data))

    merged = update_model_name(merged, f"partial_{meta_a['name']}_{meta_b['name']}")
    write_output(merged, output)
    print(f"  Averaged: {merged_count} blocks")
    print(f"  Kept from A: {kept_count} blocks")
    meta = get_meta(merged)
    print(f"Output: {output} ({meta['total_params']:,} params)")


def update_model_name(segments, new_name):
    """Replace the model name in the first text segment."""
    result = []
    name_replaced = False
    for typ, data in segments:
        if typ == "text" and not name_replaced:
            lines = data.split(b"\n", 1)
            lines[0] = new_name.encode("ascii")
            result.append(("text", b"\n".join(lines)))
            name_replaced = True
        else:
            result.append((typ, data))
    return result


def write_output(segments, output):
    """Write segments to .bin or .bin.gz file."""
    if output.endswith(".gz"):
        with gzip.open(output, "wb") as f:
            write_model(f, segments)
    else:
        with open(output, "wb") as f:
            write_model(f, segments)


def main():
    parser = argparse.ArgumentParser(
        description="Warm-start model preparation for Goirator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="Print model metadata and weight block sizes")
    p_info.add_argument("model", help="Path to .bin or .bin.gz model file")

    p_single = sub.add_parser("single", help="Copy a model (with optional compress/decompress)")
    p_single.add_argument("model", help="Path to source .bin or .bin.gz model")
    p_single.add_argument("-o", "--output", required=True, help="Output path")

    p_merge = sub.add_parser("merge", help="Average weights of two models")
    p_merge.add_argument("model_a", help="Path to first .bin or .bin.gz model")
    p_merge.add_argument("model_b", help="Path to second .bin or .bin.gz model")
    p_merge.add_argument("-o", "--output", required=True, help="Output path for merged model")
    p_merge.add_argument(
        "--alpha", type=float, default=0.5,
        help="Blending: output = alpha*A + (1-alpha)*B (default: 0.5)",
    )

    args = parser.parse_args()
    {"info": cmd_info, "single": cmd_single, "merge": cmd_merge}[args.command](args)


if __name__ == "__main__":
    main()
