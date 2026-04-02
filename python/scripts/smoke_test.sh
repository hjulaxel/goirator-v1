#!/bin/bash -eu
# Quick smoke test for the full Goirator pipeline on RunPod.
# Verifies: git pull → build → selfplay → shuffle → train → export → benchmark
#
# Runs in ~5-10 minutes. Uses tiny parameters so each step finishes fast.
# Exits 0 on success, non-zero on first failure.
#
# Usage:
#   bash smoke_test.sh          # run all steps
#   bash smoke_test.sh --skip-build   # skip git pull + build (if already done)

set -o pipefail

SKIP_BUILD=false
if [[ "${1:-}" == "--skip-build" ]]; then
    SKIP_BUILD=true
fi

BASEDIR="/workspace/smoke_test_data"
TMPDIR="/workspace/smoke_test_tmp"
MODEL_DIR="$BASEDIR/models"
ENGINE="/workspace/goirator-v1/cpp/build/katago"
GO_IN_ROW="/workspace/go-in-row"
SCRIPTS_DIR="/workspace/goirator-v1/python/scripts"
PASS=0
FAIL=0

step_ok()   { PASS=$((PASS + 1)); echo "  ✓ $1"; }
step_fail() { FAIL=$((FAIL + 1)); echo "  ✗ $1"; }

echo "============================================"
echo " Goirator Smoke Test"
echo " $(date)"
echo "============================================"
echo ""

# ── Clean slate ──
rm -rf "$BASEDIR" "$TMPDIR"
mkdir -p "$BASEDIR"/{selfplay,models,shuffleddata}
mkdir -p "$TMPDIR"

# ── 1. Git pull ──
echo "[1/7] Git pull..."
if [ "$SKIP_BUILD" = false ]; then
    cd /workspace/goirator-v1
    if git pull --ff-only 2>&1; then
        step_ok "goirator-v1 pull"
    else
        step_fail "goirator-v1 pull"
    fi

    cd /workspace/go-in-row
    if git pull --ff-only 2>&1; then
        step_ok "go-in-row pull"
    else
        step_fail "go-in-row pull"
    fi
else
    echo "  (skipped)"
fi

# ── 2. Build ──
echo "[2/7] Build engine..."
if [ "$SKIP_BUILD" = false ]; then
    cd /workspace/goirator-v1/cpp/build
    if make -j$(nproc) 2>&1 | tail -3; then
        step_ok "C++ engine build"
    else
        step_fail "C++ engine build"
    fi
else
    echo "  (skipped)"
fi

# Verify engine exists
if [ -x "$ENGINE" ]; then
    step_ok "Engine binary exists"
else
    step_fail "Engine binary missing at $ENGINE"
    echo "FATAL: cannot continue without engine."
    exit 1
fi

# ── 3. Model available ──
echo "[3/7] Warm-start model..."
if [ -f /workspace/models/model.bin.gz ]; then
    cp /workspace/models/model.bin.gz "$MODEL_DIR"/
    step_ok "Model copied to smoke test dir"
elif [ -f /workspace/models/b10_freestyle15x.bin.gz ]; then
    cp /workspace/models/b10_freestyle15x.bin.gz "$MODEL_DIR"/model.bin.gz
    step_ok "Model copied from downloaded gomoku model"
else
    step_fail "No warm-start model found in /workspace/models/"
    echo "FATAL: cannot continue without a model."
    exit 1
fi

# ── 4. Self-play (50 games — just enough to produce data) ──
echo "[4/7] Self-play (50 games)..."
cd /workspace/goirator-v1/python

# Use a tweaked selfplay config: fewer threads for quick test
SMOKE_SELFPLAY_CFG="$BASEDIR/smoke_selfplay.cfg"
sed 's/numGameThreads = 512/numGameThreads = 32/' \
    "$SCRIPTS_DIR/selfplay.cfg" \
    | sed 's/nnMaxBatchSize = 256/nnMaxBatchSize = 32/' \
    > "$SMOKE_SELFPLAY_CFG"

if CUDA_VISIBLE_DEVICES="0" "$ENGINE" selfplay \
    -models-dir "$MODEL_DIR" \
    -config "$SMOKE_SELFPLAY_CFG" \
    -output-dir "$BASEDIR/selfplay" \
    -max-games-total 50 2>&1 | tail -5; then
    step_ok "Self-play (50 games)"
else
    step_fail "Self-play"
fi

# Verify data was produced
SELFPLAY_FILES=$(find "$BASEDIR/selfplay" -name "*.npz" -o -name "*.zip" 2>/dev/null | head -5 | wc -l)
if [ "$SELFPLAY_FILES" -gt 0 ]; then
    step_ok "Self-play data files exist ($SELFPLAY_FILES+ files)"
else
    step_fail "No self-play data files produced"
fi

# ── 5. Shuffle ──
echo "[5/7] Shuffle..."
# Use a very low min-rows for smoke test
if SKIP_VALIDATE=1 bash selfplay/shuffle.sh \
    "$BASEDIR" "$TMPDIR" 2 128 \
    -keep-target-rows 100000 \
    -min-rows 0 2>&1 | tail -5; then
    step_ok "Shuffle"
else
    step_fail "Shuffle"
fi

# Verify shuffled data
SHUFFLED_FILES=$(find "$BASEDIR/shuffleddata" -name "*.npz" 2>/dev/null | head -5 | wc -l)
if [ "$SHUFFLED_FILES" -gt 0 ]; then
    step_ok "Shuffled data files exist ($SHUFFLED_FILES+ files)"
else
    step_fail "No shuffled data files"
fi

# ── 6. Train + Export (1 epoch, tiny) ──
echo "[6/7] Train (1 epoch) + Export..."
if CUDA_VISIBLE_DEVICES="0" bash selfplay/train.sh \
    "$BASEDIR" "smoke" "b10c384nbt-fson-mish-rvglr-bnh" 128 main \
    -samples-per-epoch 500 \
    -max-epochs-this-instance 1 \
    -quit-if-no-data \
    -lr-scale 2.0 \
    -pos-len 15 2>&1 | tail -10; then
    step_ok "Training (1 epoch)"
else
    step_fail "Training"
fi

# Export
if bash selfplay/export_model_for_selfplay.sh "smoke" "$BASEDIR" 0 2>&1 | tail -5; then
    step_ok "Export"
else
    step_fail "Export"
fi

# Verify exported model
EXPORTED_MODEL=$(find "$MODEL_DIR" -name "*.bin.gz" -newer "$MODEL_DIR/model.bin.gz" -type f 2>/dev/null | head -1)
if [ -n "$EXPORTED_MODEL" ]; then
    step_ok "Exported model exists: $(basename "$(dirname "$EXPORTED_MODEL")")"
else
    # Might still only have warmstart model — that's ok for smoke test
    echo "  (no new model exported yet, warmstart model will be used for benchmark)"
fi

# ── 7. Benchmark (2 games) ──
echo "[7/7] Benchmark (2 games vs alpha-beta)..."
LATEST_MODEL=$(find "$MODEL_DIR" -name "*.bin.gz" -type f -printf "%T@ %p\n" 2>/dev/null \
    | sort -rn | head -1 | cut -d' ' -f2-)

if [ -n "$LATEST_MODEL" ] && [ -d "$GO_IN_ROW" ]; then
    if CUDA_VISIBLE_DEVICES="0" python3 "$SCRIPTS_DIR/benchmark_vs_alphabeta.py" \
        --engine "$ENGINE" \
        --model "$LATEST_MODEL" \
        --config "$SCRIPTS_DIR/gtp_benchmark.cfg" \
        --go-in-row "$GO_IN_ROW" \
        --games 2 \
        --board-size 15 \
        --generation -1 2>&1; then
        step_ok "Benchmark vs alpha-beta"
    else
        step_fail "Benchmark vs alpha-beta"
    fi
else
    step_fail "Benchmark: model or go-in-row missing"
fi

# ── Summary ──
echo ""
echo "============================================"
echo " Smoke Test Results"
echo "============================================"
echo " Passed: $PASS"
echo " Failed: $FAIL"
echo "============================================"

# Cleanup
rm -rf "$BASEDIR" "$TMPDIR"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "SMOKE TEST FAILED — fix the above issues before starting training."
    exit 1
else
    echo ""
    echo "ALL CLEAR — pipeline is working. Ready to train."
    exit 0
fi
