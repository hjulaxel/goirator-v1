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
echo "[1/6] Installing system dependencies..."
apt-get update -qq && apt-get install -y -qq cmake build-essential libzip-dev zlib1g-dev > /dev/null 2>&1
echo "  Done."

# 2. Clone repos
echo "[2/6] Cloning repositories..."
if [ ! -d /workspace/goirator-v1 ]; then
    git clone https://github.com/hjulaxel/goirator-v1.git /workspace/goirator-v1
else
    cd /workspace/goirator-v1 && git pull && cd /workspace
    echo "  goirator-v1 already exists, pulled latest."
fi

if [ ! -d /workspace/go-in-row ]; then
    git clone -b model-showdown https://github.com/hjulaxel/go-in-row.git /workspace/go-in-row
else
    cd /workspace/go-in-row && git pull && cd /workspace
    echo "  go-in-row already exists, pulled latest."
fi

# 3. Build C++ engine
echo "[3/6] Building C++ engine (CUDA backend)..."
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
echo "[4/6] Installing Python dependencies..."
pip install -q numpy torch 2>/dev/null
echo "  Done."

# 5. Download warm-start model (Gomoku b10 freestyle 15x15)
echo "[5/6] Downloading warm-start model..."
mkdir -p /workspace/models
cd /workspace/models

if [ ! -f b10_freestyle15x.bin.gz ]; then
    echo "  Downloading Gomoku b10 freestyle 15x model (6MB)..."
    curl -sLO "https://github.com/hzyhhzy/KataGomo/releases/download/gomocup2025/b10_freestyle15x.bin.gz"
fi

# Set up initial model for selfplay
if [ ! -f model.bin.gz ]; then
    cp b10_freestyle15x.bin.gz model.bin.gz
    echo "  Warm-start model ready: model.bin.gz (Gomoku b10 freestyle 15x)"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Commands:"
echo "  Smoke test (recommended first time):"
echo "    cd /workspace/goirator-v1/python/scripts && bash smoke_test.sh --skip-build"
echo ""
echo "  Start training:"
echo "    cd /workspace/goirator-v1/python/scripts && bash run_train.sh 1"
echo ""
echo "  Monitor training:"
echo "    tail -f /workspace/data/run_train.log"
echo ""
echo "  Benchmark results:"
echo "    cat /workspace/data/benchmark_log.txt"
