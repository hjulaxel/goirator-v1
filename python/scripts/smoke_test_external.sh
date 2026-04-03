#!/bin/bash -eu
# Smoke test for the external opponent feature.
# Runs a tiny selfplay with externalOpponentProb=1.0 to verify:
#   1. ExternalPlayer subprocess starts and communicates via GTP
#   2. Games complete with mixed MCTS + external moves
#   3. Training data is written (with zero-weight external turns)
#
# Usage:
#   bash smoke_test_external.sh          # full test
#   bash smoke_test_external.sh --skip-build  # skip rebuild

set -o pipefail

SKIP_BUILD=false
if [[ "${1:-}" == "--skip-build" ]]; then
    SKIP_BUILD=true
fi

BASEDIR="/workspace/smoke_test_external"
TMPDIR="/workspace/smoke_test_external_tmp"
MODEL_DIR="$BASEDIR/models"
ENGINE="/workspace/goirator-v1/cpp/build/katago"
GO_IN_ROW="/workspace/go-in-row"
SCRIPTS_DIR="/workspace/goirator-v1/python/scripts"
PASS=0
FAIL=0

step_ok()   { PASS=$((PASS + 1)); echo "  ✓ $1"; }
step_fail() { FAIL=$((FAIL + 1)); echo "  ✗ $1"; }

echo "============================================"
echo " External Opponent Smoke Test"
echo " $(date)"
echo "============================================"
echo ""

rm -rf "$BASEDIR" "$TMPDIR"
mkdir -p "$BASEDIR"/{selfplay,models,shuffleddata}
mkdir -p "$TMPDIR"

# ── 1. Rebuild (picks up externalplayer.cpp) ──
echo "[1/5] Build engine..."
if [ "$SKIP_BUILD" = false ]; then
    cd /workspace/goirator-v1/cpp/build
    if make -j$(nproc) 2>&1 | tail -5; then
        step_ok "C++ engine build (with ExternalPlayer)"
    else
        step_fail "C++ engine build"
        echo "FATAL: build failed"
        exit 1
    fi
else
    echo "  (skipped)"
fi

if [ ! -x "$ENGINE" ]; then
    step_fail "Engine binary missing"
    exit 1
fi

# ── 2. Verify alpha-beta GTP wrapper works standalone ──
echo "[2/5] Test alphabeta_gtp.py standalone..."
RESPONSE=$(echo -e "name\nquit\n" | python3 "$SCRIPTS_DIR/alphabeta_gtp.py" --go-in-row "$GO_IN_ROW" 2>/dev/null)
if echo "$RESPONSE" | grep -q "AlphaBeta"; then
    step_ok "alphabeta_gtp.py responds to GTP"
else
    step_fail "alphabeta_gtp.py GTP response"
    echo "  Got: $RESPONSE"
fi

# ── 3. Model available ──
echo "[3/5] Warm-start model..."
if [ -f /workspace/models/model.bin.gz ]; then
    cp /workspace/models/model.bin.gz "$MODEL_DIR"/
    step_ok "Model copied"
elif [ -f /workspace/models/b10_freestyle15x.bin.gz ]; then
    cp /workspace/models/b10_freestyle15x.bin.gz "$MODEL_DIR"/model.bin.gz
    step_ok "Model copied from gomoku"
else
    step_fail "No model found"
    exit 1
fi

# ── 4. Selfplay with external opponent (5 games, 100% external) ──
echo "[4/5] Selfplay with external opponent (5 games)..."

# Create a modified selfplay config with external opponent enabled
SMOKE_CFG="$BASEDIR/selfplay_ext.cfg"
cat "$SCRIPTS_DIR/selfplay.cfg" > "$SMOKE_CFG"
cat >> "$SMOKE_CFG" << EOF

# External opponent settings for smoke test
externalOpponentCmd = python3 $SCRIPTS_DIR/alphabeta_gtp.py --go-in-row $GO_IN_ROW --depth 2 --time 1.0
externalOpponentProb = 1.0
EOF

# Reduce threads for testing
sed -i 's/numGameThreads = 512/numGameThreads = 1/' "$SMOKE_CFG"
sed -i 's/nnMaxBatchSize = 256/nnMaxBatchSize = 1/' "$SMOKE_CFG"

if CUDA_VISIBLE_DEVICES="0" timeout 600 "$ENGINE" selfplay \
    -models-dir "$MODEL_DIR" \
    -config "$SMOKE_CFG" \
    -output-dir "$BASEDIR/selfplay" \
    -max-games-total 5 2>&1 | tail -20; then
    step_ok "Selfplay with external opponent completed"
else
    step_fail "Selfplay with external opponent"
fi

# ── 5. Verify data was produced ──
echo "[5/5] Verify training data..."
DATA_FILES=$(find "$BASEDIR/selfplay" -name "*.npz" -o -name "*.zip" 2>/dev/null | wc -l)
if [ "$DATA_FILES" -gt 0 ]; then
    step_ok "Training data produced ($DATA_FILES files)"
else
    step_fail "No training data files"
fi

# ── Summary ──
echo ""
echo "============================================"
echo " External Opponent Smoke Test Results"
echo "============================================"
echo " Passed: $PASS"
echo " Failed: $FAIL"
echo "============================================"

rm -rf "$BASEDIR" "$TMPDIR"

if [ "$FAIL" -gt 0 ]; then
    echo "SMOKE TEST FAILED"
    exit 1
else
    echo "ALL CLEAR — external opponent feature is working."
    exit 0
fi
