#!/bin/bash -eu
# Goirator training loop for RunPod
# Usage: bash run_train.sh [NUM_GPUS]
#
# Automatically runs detached (via nohup) so it survives terminal disconnects.
# Log: /workspace/data/run_train.log
#
# This runs on a RunPod pod with the repo cloned to /workspace/goirator-v1
# and the warm-start model at /workspace/models/model.bin.gz

# Auto-detach: if not already running under nohup, re-exec with nohup
if [ -z "${GOIRATOR_NOHUP:-}" ]; then
    export GOIRATOR_NOHUP=1
    mkdir -p /workspace/data
    echo "Training launched in background. Monitor with:"
    echo "  tail -f /workspace/data/run_train.log"
    nohup bash "$0" "$@" > /workspace/data/run_train.log 2>&1 &
    echo "PID: $!"
    exit 0
fi

NUM_GPUS="${1:-1}"
BASEDIR="/workspace/data"
TMPDIR="/workspace/tmp"
MODEL_DIR="$BASEDIR/models"
ENGINE="/workspace/goirator-v1/cpp/build/katago"

# Model config: b10c384nbt is a good balance of strength vs training speed
# ~5-20 RTX 4090-days for a solid model
MODEL_NAME="goirator"
MODEL_KIND="b10c384nbt-fson-mish-rvglr-bnh"
BATCH_SIZE=128
SELFPLAY_GAMES=10000

# Create directory structure
mkdir -p "$BASEDIR"/{selfplay,models,shuffleddata}
mkdir -p "$TMPDIR"

# Copy warm-start model if available
if [ -f /workspace/models/model.bin.gz ] && [ ! -f "$MODEL_DIR"/model.bin.gz ]; then
    cp /workspace/models/model.bin.gz "$MODEL_DIR"/
    echo "Warm-start model copied to $MODEL_DIR"
fi

echo "============================================"
echo "Goirator Training Loop"
echo "GPUs: $NUM_GPUS"
echo "Model: $MODEL_NAME ($MODEL_KIND)"
echo "Batch size: $BATCH_SIZE"
echo "Selfplay games per generation: $SELFPLAY_GAMES"
echo "============================================"

cd /workspace/goirator-v1/python

GPU_LIST=$(seq -s, 0 $((NUM_GPUS - 1)))

GENERATION=0
while true; do
    GENERATION=$((GENERATION + 1))
    echo ""
    echo "========== Generation $GENERATION =========="
    echo "Started at $(date)"

    # 1. Self-play
    echo "[1/4] Running self-play ($SELFPLAY_GAMES games)..."
    CUDA_VISIBLE_DEVICES="$GPU_LIST" "$ENGINE" selfplay \
        -models-dir "$MODEL_DIR" \
        -config /workspace/goirator-v1/python/scripts/selfplay.cfg \
        -output-dir "$BASEDIR/selfplay" \
        -max-games-total "$SELFPLAY_GAMES"

    # 2. Shuffle
    echo "[2/4] Shuffling training data..."
    cd /workspace/goirator-v1/python
    bash selfplay/shuffle.sh "$BASEDIR" "$TMPDIR" 4 "$BATCH_SIZE" \
        -keep-target-rows 1200000 \
        -min-rows 100000

    # 3. Train
    echo "[3/4] Training neural network..."
    CUDA_VISIBLE_DEVICES="$GPU_LIST" bash selfplay/train.sh \
        "$BASEDIR" "$MODEL_NAME" "$MODEL_KIND" "$BATCH_SIZE" main \
        -samples-per-epoch 1000000 \
        -lr-scale 2.0 \
        -pos-len 15

    # 4. Export
    echo "[4/4] Exporting model..."
    bash selfplay/export_model_for_selfplay.sh "$MODEL_NAME" "$BASEDIR" 0

    echo "Generation $GENERATION complete at $(date)"
done
