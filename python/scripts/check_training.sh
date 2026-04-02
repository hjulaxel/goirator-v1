#!/bin/bash
# Quick health check for goirator training.
# Designed to be called by Claude Code periodically.
# Exits 0 = healthy, 1 = problem detected.

BASEDIR="/workspace/data"
LOGFILE="$BASEDIR/run_train.log"
TRAIN_LOG="$BASEDIR/train/goirator/stdout.txt"
BENCHMARK_LOG="$BASEDIR/benchmark_log.txt"

echo "=== Goirator Training Health Check ==="
echo "Time: $(date)"
echo ""

# 1. Is training process running?
PID=$(pgrep -f "run_train.sh" 2>/dev/null | head -1)
if [ -n "$PID" ]; then
    echo "[OK] Training process running (PID $PID)"
else
    echo "[WARN] Training process NOT running!"
fi

# 2. Current generation (from run_train.log)
if [ -f "$LOGFILE" ]; then
    LAST_GEN=$(grep -o "Generation [0-9]*" "$LOGFILE" | tail -1)
    LAST_STEP=$(grep -E "^\[" "$LOGFILE" | tail -1)
    echo "[INFO] $LAST_GEN — last step: $LAST_STEP"

    # Check for errors in last 50 lines
    ERRORS=$(tail -50 "$LOGFILE" | grep -ci "error\|exception\|fatal\|traceback" || true)
    if [ "$ERRORS" -gt 0 ]; then
        echo "[WARN] Found $ERRORS error lines in recent log:"
        tail -50 "$LOGFILE" | grep -i "error\|exception\|fatal\|traceback" | tail -5
    fi
else
    echo "[WARN] No training log found at $LOGFILE"
fi

# 3. Training loss (from train stdout)
if [ -f "$TRAIN_LOG" ]; then
    echo ""
    echo "--- Latest training metrics ---"
    grep -E "samp|loss|epoch" "$TRAIN_LOG" | tail -3
fi

# 4. Selfplay data growth
SELFPLAY_COUNT=$(find "$BASEDIR/selfplay" -name "*.npz" -o -name "*.zip" 2>/dev/null | wc -l)
echo ""
echo "[INFO] Selfplay data files: $SELFPLAY_COUNT"

# 5. Models
MODEL_COUNT=$(find "$BASEDIR/models" -name "*.bin.gz" 2>/dev/null | wc -l)
echo "[INFO] Models in models dir: $MODEL_COUNT"

# 6. Benchmark results
if [ -f "$BENCHMARK_LOG" ]; then
    echo ""
    echo "--- Benchmark results ---"
    grep "result:" "$BENCHMARK_LOG" | tail -5
fi

# 7. Disk usage
echo ""
echo "[INFO] Disk usage: $(du -sh "$BASEDIR" 2>/dev/null | cut -f1)"
echo "[INFO] Free disk: $(df -h /workspace 2>/dev/null | tail -1 | awk '{print $4}')"

# 8. GPU status
echo ""
echo "--- GPU ---"
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader 2>/dev/null || echo "nvidia-smi not available"

echo ""
echo "=== Health check complete ==="
