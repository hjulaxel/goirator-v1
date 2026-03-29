#!/bin/bash -eu
# RunPod pod setup script for Goirator training
# Run this once when the pod starts.
#
# Expected: RunPod pod with PyTorch image, CUDA, and a network volume at /workspace
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/hjulaxel/goirator-v1/main/scripts/runpod_setup.sh | bash

echo "=== Goirator RunPod Setup ==="

# 1. System dependencies
echo "[1/5] Installing system dependencies..."
apt-get update -qq && apt-get install -y -qq cmake build-essential libzip-dev zlib1g-dev > /dev/null 2>&1
echo "  Done."

# 2. Clone repo
echo "[2/5] Cloning goirator-v1..."
if [ ! -d /workspace/goirator-v1 ]; then
    git clone https://github.com/hjulaxel/goirator-v1.git /workspace/goirator-v1
else
    cd /workspace/goirator-v1 && git pull && cd /workspace
    echo "  Repo already exists, pulled latest."
fi

# 3. Build C++ engine
echo "[3/5] Building C++ engine (CUDA backend)..."
cd /workspace/goirator-v1/cpp
mkdir -p build && cd build

cmake .. \
    -DUSE_BACKEND=CUDA \
    -DBUILD_DISTRIBUTED=0 \
    -DCMAKE_BUILD_TYPE=Release \
    > /dev/null 2>&1

make -j$(nproc) 2>&1 | tail -5
echo "  Engine built at: /workspace/goirator-v1/cpp/build/katago"

# 4. Python dependencies
echo "[4/5] Installing Python dependencies..."
pip install -q numpy torch 2>/dev/null
echo "  Done."

# 5. Download warm-start model
echo "[5/5] Downloading warm-start model..."
mkdir -p /workspace/models
cd /workspace/models

if [ ! -f capturego_19x_b18.bin.gz ]; then
    echo "  Downloading CaptureGo b18 model (93MB)..."
    curl -sLO "https://github.com/hzyhhzy/KataGomo/releases/download/CaptureGo_20250509/capturego_19x_b18.bin.gz"
fi

# Set up initial model for selfplay
if [ ! -f model.bin.gz ]; then
    cp capturego_19x_b18.bin.gz model.bin.gz
    echo "  Warm-start model ready: model.bin.gz (CaptureGo b18)"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start training:"
echo "  cd /workspace/goirator-v1/python/scripts"
echo "  bash run_train.sh 1    # for 1 GPU"
echo "  bash run_train.sh 2    # for 2 GPUs"
echo ""
echo "To use the gomoku model instead (partial feature compatibility):"
echo "  cd /workspace/models"
echo "  curl -sLO https://github.com/hzyhhzy/KataGomo/releases/download/Gomoku_20250206/zhizi_renju28b_s1600.bin.gz"
echo "  cp zhizi_renju28b_s1600.bin.gz model.bin.gz"
echo ""
echo "To merge models:"
echo "  cd /workspace/goirator-v1/python"
echo "  python3 warmstart.py merge /workspace/models/capturego_19x_b18.bin.gz /workspace/models/other.bin.gz -o /workspace/models/model.bin.gz"
