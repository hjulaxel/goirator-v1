#!/usr/bin/env python3
"""
GTP wrapper for the Alpha-Beta player from go-in-row.
Speaks the Go Text Protocol on stdin/stdout so KataGo selfplay can use it
as an external opponent.

Usage:
    python alphabeta_gtp.py --go-in-row /path/to/go-in-row [--depth 4] [--time 3.0]

Supports: protocol_version, name, version, boardsize, clear_board, play, genmove, quit
"""

import argparse
import sys
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go-in-row", required=True, help="Path to go-in-row repo")
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--time", type=float, default=3.0)
    args = ap.parse_args()

    sys.path.insert(0, args.go_in_row)
    from logic.game_logic import GoRowGame
    from algorithms.alpha_beta import AlphaBetaPlayer

    GTP_COLS = "ABCDEFGHJKLMNOPQRST"

    board_size = 15
    game = GoRowGame(size=board_size)
    player = AlphaBetaPlayer(depth=args.depth, max_time=args.time)

    def gtp_to_rc(move_str):
        letter = move_str[0].upper()
        number = int(move_str[1:])
        c = GTP_COLS.index(letter)
        r = board_size - number
        return (r, c)

    def rc_to_gtp(r, c):
        return f"{GTP_COLS[c]}{board_size - r}"

    def respond(text=""):
        sys.stdout.write(f"= {text}\n\n")
        sys.stdout.flush()

    def error(text=""):
        sys.stdout.write(f"? {text}\n\n")
        sys.stdout.flush()

    while True:
        try:
            line = sys.stdin.readline()
        except EOFError:
            break
        if not line:
            break

        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        # Strip optional numeric ID prefix
        if parts[0].isdigit():
            parts = parts[1:]
        if not parts:
            continue

        cmd = parts[0].lower()

        if cmd == "protocol_version":
            respond("2")
        elif cmd == "name":
            respond("AlphaBeta")
        elif cmd == "version":
            respond("1.0")
        elif cmd == "list_commands":
            respond("protocol_version\nname\nversion\nlist_commands\nboardsize\nclear_board\nplay\ngenmove\nquit")
        elif cmd == "boardsize":
            if len(parts) >= 2:
                board_size = int(parts[1])
            game = GoRowGame(size=board_size)
            player.tt.clear()
            respond()
        elif cmd == "clear_board":
            game = GoRowGame(size=board_size)
            player.tt.clear()
            respond()
        elif cmd == "play":
            if len(parts) < 3:
                error("usage: play <color> <vertex>")
                continue
            move_str = parts[2].upper()
            if move_str == "PASS":
                respond()
                continue
            try:
                r, c = gtp_to_rc(move_str)
                if not game.place_stone(r, c):
                    error(f"illegal move {move_str}")
                else:
                    respond()
            except (ValueError, IndexError) as e:
                error(str(e))
        elif cmd == "genmove":
            move = player.choose_move(game)
            if move is None:
                respond("pass")
            else:
                r, c = move
                game.place_stone(r, c)
                respond(rc_to_gtp(r, c))
        elif cmd == "quit":
            respond()
            break
        elif cmd == "rectangular_boardsize":
            # For non-square boards: rectangular_boardsize X Y
            if len(parts) >= 3:
                x_size = int(parts[1])
                y_size = int(parts[2])
                board_size = max(x_size, y_size)
            game = GoRowGame(size=board_size)
            player.tt.clear()
            respond()
        elif cmd == "komi":
            respond()  # accept but ignore
        else:
            error(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
