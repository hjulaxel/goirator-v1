#!/usr/bin/env python3
"""
Benchmark a KataGo (goirator) model against the Alpha-Beta player from go-in-row.

Plays N games via a GTP bridge, alternating colors each game for fairness.
Reports win/loss stats overall and per-color to separate model strength
from first-player advantage.

Usage:
    python benchmark_vs_alphabeta.py \
        --engine /path/to/katago \
        --model  /path/to/model.bin.gz \
        --config /path/to/gtp_benchmark.cfg \
        --go-in-row /path/to/go-in-row \
        --games 20 --board-size 15
"""

import argparse
import subprocess
import sys
import os
import time

GTP_COLS = "ABCDEFGHJKLMNOPQRST"  # I is skipped per GTP convention


# ── Coordinate conversion ─────────────────────────────────────────────
def rc_to_gtp(r, c, board_size):
    """(row, col) with (0,0)=top-left  →  GTP string like 'D11'."""
    return f"{GTP_COLS[c]}{board_size - r}"


def gtp_to_rc(move_str, board_size):
    """GTP string like 'D11'  →  (row, col) with (0,0)=top-left."""
    letter = move_str[0].upper()
    number = int(move_str[1:])
    return (board_size - number, GTP_COLS.index(letter))


# ── GTP subprocess wrapper ────────────────────────────────────────────
class GTPEngine:
    def __init__(self, cmd):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def send(self, command):
        """Send a GTP command; return (ok: bool, response: str)."""
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()
        lines = []
        while True:
            line = self.proc.stdout.readline()
            if not line:  # EOF — engine crashed
                return False, "engine EOF"
            stripped = line.rstrip("\n")
            if stripped == "" and lines:
                break
            if stripped != "":
                lines.append(stripped)
        response = "\n".join(lines)
        if response.startswith("= "):
            return True, response[2:]
        if response.startswith("="):
            return True, response[1:]
        if response.startswith("? "):
            return False, response[2:]
        if response.startswith("?"):
            return False, response[1:]
        return True, response

    def close(self):
        try:
            self.proc.stdin.write("quit\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


# ── Play one game ─────────────────────────────────────────────────────
def play_game(engine, ab_player, board_size, katago_color):
    """
    Play a full game.  Returns 'katago', 'alphabeta', or 'draw'.
    katago_color: 'B' or 'W'.
    """
    from logic.game_logic import GoRowGame

    game = GoRowGame(size=board_size)
    engine.send(f"boardsize {board_size}")
    engine.send("clear_board")
    engine.send("komi 7")

    colors = ["B", "W"]
    max_moves = board_size * board_size

    for move_num in range(max_moves):
        current_color = colors[move_num % 2]
        is_katago_turn = current_color == katago_color

        if is_katago_turn:
            ok, resp = engine.send(f"genmove {current_color}")
            if not ok:
                return "alphabeta"
            move_str = resp.strip()
            if move_str.lower() == "resign":
                return "alphabeta"
            if move_str.lower() == "pass":
                continue
            r, c = gtp_to_rc(move_str, board_size)
            if not game.place_stone(r, c):
                print(f"  WARN: KataGo move {move_str} ({r},{c}) illegal in GoRowGame")
                return "alphabeta"
        else:
            move = ab_player.choose_move(game)
            if move is None:
                return "katago"
            r, c = move
            game.place_stone(r, c)
            gtp_move = rc_to_gtp(r, c, board_size)
            ok, _ = engine.send(f"play {current_color} {gtp_move}")
            if not ok:
                print(f"  WARN: Alpha-beta move {gtp_move} rejected by KataGo GTP")

        winner = game.check_win()
        if winner != 0:
            winning_color = "B" if winner == 1 else "W"
            return "katago" if winning_color == katago_color else "alphabeta"

    return "draw"


# ── Main ──────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Benchmark KataGo vs Alpha-Beta")
    ap.add_argument("--engine", required=True, help="Path to katago binary")
    ap.add_argument("--model", required=True, help="Path to model .bin.gz")
    ap.add_argument("--config", required=True, help="Path to GTP config file")
    ap.add_argument("--go-in-row", required=True, help="Path to go-in-row repo root")
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--board-size", type=int, default=15)
    ap.add_argument("--ab-depth", type=int, default=4, help="Alpha-beta search depth")
    ap.add_argument("--ab-time", type=float, default=5.0, help="Alpha-beta time limit (s)")
    ap.add_argument("--generation", type=int, default=-1, help="Generation label for logging")
    args = ap.parse_args()

    # Make go-in-row importable
    sys.path.insert(0, args.go_in_row)
    from algorithms.alpha_beta import AlphaBetaPlayer

    # Launch KataGo GTP
    cmd = [args.engine, "gtp", "-config", args.config, "-model", args.model]
    print(f"[benchmark] Starting KataGo: {' '.join(cmd)}")
    engine = GTPEngine(cmd)

    # Warmup — wait for engine to load
    ok, resp = engine.send("name")
    if ok:
        print(f"[benchmark] Engine ready: {resp.strip()}")
    else:
        print(f"[benchmark] Engine failed to start: {resp}")
        sys.exit(1)

    ab = AlphaBetaPlayer(depth=args.ab_depth, max_time=args.ab_time)

    # Per-color tracking
    katago_wins_as_B = 0
    katago_wins_as_W = 0
    games_as_B = 0
    games_as_W = 0
    draws = 0

    gen_label = f"gen {args.generation}" if args.generation >= 0 else "baseline"
    print(f"\n[benchmark] {gen_label}: KataGo vs Alpha-Beta "
          f"({args.games} games, {args.board_size}x{args.board_size})")
    print("=" * 60)

    for i in range(args.games):
        katago_color = "B" if i % 2 == 0 else "W"
        ab.tt.clear()  # fresh TT per game

        print(f"  Game {i+1}/{args.games} (KataGo={katago_color})", end=" ... ", flush=True)
        t0 = time.time()
        result = play_game(engine, ab, args.board_size, katago_color)
        elapsed = time.time() - t0

        if result == "katago":
            if katago_color == "B":
                katago_wins_as_B += 1
            else:
                katago_wins_as_W += 1
            print(f"KataGo wins  ({elapsed:.0f}s)")
        elif result == "alphabeta":
            print(f"Alpha-Beta wins  ({elapsed:.0f}s)")
        else:
            draws += 1
            print(f"Draw  ({elapsed:.0f}s)")

        if katago_color == "B":
            games_as_B += 1
        else:
            games_as_W += 1

    engine.close()

    total_katago = katago_wins_as_B + katago_wins_as_W
    total_games = args.games
    winrate = total_katago / total_games * 100 if total_games > 0 else 0
    wr_as_B = katago_wins_as_B / games_as_B * 100 if games_as_B > 0 else 0
    wr_as_W = katago_wins_as_W / games_as_W * 100 if games_as_W > 0 else 0

    print("=" * 60)
    print(f"[benchmark] {gen_label} result: "
          f"KataGo {total_katago} - {total_games - total_katago - draws} Alpha-Beta "
          f"({draws} draws)  winrate={winrate:.0f}%")
    print(f"[benchmark]   as Black: {katago_wins_as_B}/{games_as_B} ({wr_as_B:.0f}%)  "
          f"as White: {katago_wins_as_W}/{games_as_W} ({wr_as_W:.0f}%)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
