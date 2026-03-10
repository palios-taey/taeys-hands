#!/bin/bash
# Start llama-server with optimized settings for DGX Spark GB10 / Jetson Thor
# Model: Qwen3.5-35B-A3B (MoE, 3B active params, 40-60+ t/s on Spark)
#
# Usage: ./start-llama-server.sh [--port PORT] [--ctx CTX_SIZE]
# Defaults: port=8080, ctx=65536

set -euo pipefail

# Defaults
PORT="${LLAMA_PORT:-8080}"
CTX="${LLAMA_CTX:-65536}"
THREADS="${LLAMA_THREADS:-10}"

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --ctx)  CTX="$2";  shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Find model
MODEL=""
for path in \
    "$HOME/models/qwen35-35b-a3b/Qwen3.5-35B-A3B-Q8_0.gguf" \
    "$HOME/models/Qwen3.5-35B-A3B-Q8_0.gguf"; do
    if [[ -f "$path" ]]; then
        MODEL="$path"
        break
    fi
done

if [[ -z "$MODEL" ]]; then
    echo "ERROR: Qwen3.5-35B-A3B-Q8_0.gguf not found in ~/models/"
    exit 1
fi

# Find llama-server binary
SERVER=""
for path in \
    "$HOME/llama.cpp/build/bin/llama-server" \
    "/usr/local/bin/llama-server"; do
    if [[ -x "$path" ]]; then
        SERVER="$path"
        break
    fi
done

if [[ -z "$SERVER" ]]; then
    echo "ERROR: llama-server not found"
    exit 1
fi

# Detect thread count (Spark GB10 = 10 perf cores, Jetson Orin = 12 cores)
if [[ -f /proc/cpuinfo ]]; then
    NCPU=$(nproc)
    if (( NCPU > 20 )); then
        # Spark GB10: 10 perf + 10 efficiency — use perf cores only
        THREADS=10
    elif (( NCPU > 8 )); then
        THREADS=$((NCPU / 2))
    fi
fi

echo "=== llama-server ==="
echo "Model:   $MODEL"
echo "Server:  $SERVER"
echo "Port:    $PORT"
echo "Context: $CTX"
echo "Threads: $THREADS"
echo "===================="

exec "$SERVER" \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    -ngl 999 \
    -c "$CTX" \
    --flash-attn on \
    --no-mmap \
    --mlock \
    --jinja \
    --chat-template-kwargs '{"enable_thinking":false}' \
    --batch-size 2048 \
    --ubatch-size 512 \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --threads "$THREADS" \
    --no-webui
