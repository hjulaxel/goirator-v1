We've pushed a major update to the training pipeline. The model has plateaued at ~50% winrate against the alpha-beta bot after 7 generations of pure self-play. The new code adds an "external opponent" feature: 30% of selfplay games will now pit the NN against the alpha-beta bot from go-in-row, exposing it to tactical positions it can't discover in self-play alone.

Here's what you need to do:

1. STOP the current training gracefully:
   kill $(pgrep -f run_train.sh)
   Wait for it to finish the current step (check with: ps aux | grep katago)

2. EXPORT the best model from the current run so we don't lose it:
   cd /workspace/goirator-v1/python
   bash selfplay/export_model_for_selfplay.sh goirator /workspace/data 0

3. PULL the new code (includes C++ changes):
   cd /workspace/goirator-v1 && git pull
   cd /workspace/go-in-row && git pull

4. REBUILD the C++ engine (new externalplayer.cpp):
   cd /workspace/goirator-v1/cpp/build
   cmake .. -DUSE_BACKEND=CUDA -DBUILD_DISTRIBUTED=0 -DCMAKE_BUILD_TYPE=Release
   make -j$(nproc)

5. RUN the external opponent smoke test:
   cd /workspace/goirator-v1/python/scripts
   bash smoke_test_external.sh --skip-build

6. If smoke test passes, START training with the new pipeline:
   bash run_train.sh 1

7. SET UP monitoring:
   /loop 15m bash /workspace/goirator-v1/python/scripts/check_training.sh

The training will continue from where we left off (existing data + models are preserved). The key change: 30% of selfplay games now use the alpha-beta bot as opponent (depth 3, 2s per move). This runs on CPU in parallel with the GPU selfplay, so overhead is modest. The benchmark after each generation will show if we're improving against alpha-beta.

Watch for: any errors related to ExternalPlayer in the training log, and whether the benchmark winrate starts climbing above 50%.
