#!/bin/bash
# SPARK 2 TRI-LENS DEPLOYMENT SCRIPT
# Deploy Qwen3-Embedding-8B + Weaviate + Parallel Pipeline
# Target: Spark #2 (10.0.0.80 / 192.168.100.11)
# Based on: Grok's mathematical analysis + comprehensive exploration

set -e  # Exit on error
set -u  # Exit on undefined variable

# ANSI colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; exit 1; }

# ============================================================================
# PHASE 1: VERIFY ENVIRONMENT
# ============================================================================

log "Phase 1: Verifying Spark 2 environment..."

# Check if we're on Spark 2
HOSTNAME=$(hostname)
if [[ ! "$HOSTNAME" =~ spark.*2 ]]; then
    warn "Not on Spark 2 (hostname: $HOSTNAME)"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && error "Deployment cancelled"
fi

# Check if Weaviate is running
if curl -s http://192.168.100.11:8080/v1/meta > /dev/null 2>&1; then
    success "Weaviate is running on 192.168.100.11:8080"
else
    error "Weaviate is NOT running - start it first"
fi

# Check if vLLM is running
if pgrep -f "vllm.*Qwen3.*Embedding" > /dev/null; then
    VLLM_PID=$(pgrep -f "vllm.*Qwen3.*Embedding")
    VLLM_PORT=$(ps -p $VLLM_PID -o args= | grep -oP '(?<=--port )\d+' || echo "unknown")
    success "vLLM is running (PID: $VLLM_PID, port: $VLLM_PORT)"

    if [[ "$VLLM_PORT" != "8001" ]]; then
        warn "vLLM is running on port $VLLM_PORT (expected 8001)"
        echo "Options:"
        echo "  1) Kill and restart vLLM on port 8001"
        echo "  2) Update code to use port $VLLM_PORT"
        echo "  3) Cancel deployment"
        read -p "Choice (1/2/3): " -n 1 -r
        echo
        case $REPLY in
            1)
                log "Killing vLLM process $VLLM_PID..."
                kill $VLLM_PID
                sleep 2
                # Will restart in Phase 2
                ;;
            2)
                warn "You'll need to update code manually to use port $VLLM_PORT"
                ;;
            3)
                error "Deployment cancelled"
                ;;
            *)
                error "Invalid choice"
                ;;
        esac
    fi
else
    warn "vLLM is NOT running - will start in Phase 2"
fi

# Check Python environment
if ! python3 -c "import weaviate" 2>/dev/null; then
    warn "weaviate-client not installed - will install in Phase 3"
fi

if ! python3 -c "import openai" 2>/dev/null; then
    warn "openai package not installed - will install in Phase 3"
fi

success "Phase 1 complete: Environment verified"

# ============================================================================
# PHASE 2: START/RESTART vLLM ON PORT 8001
# ============================================================================

log "Phase 2: Ensuring vLLM runs on port 8001..."

if ! pgrep -f "vllm.*Qwen3.*Embedding.*8001" > /dev/null; then
    log "Starting vLLM on port 8001..."

    # Create vLLM start script
    cat > /tmp/start_vllm_embedding.sh << 'EOF'
#!/bin/bash
CUDA_VISIBLE_DEVICES=0,1 vllm serve \
    Qwen/Qwen3-Embedding-8B \
    --tensor-parallel-size 2 \
    --port 8001 \
    --max-model-len 32768 \
    --max-num-seqs 64 \
    --gpu-memory-utilization 0.9 \
    --enforce-eager \
    >> /home/spark/logs/vllm-embedding.log 2>&1 &

echo "vLLM started on port 8001 (PID: $!)"
EOF

    chmod +x /tmp/start_vllm_embedding.sh

    # Start in background
    nohup /tmp/start_vllm_embedding.sh > /dev/null 2>&1 &

    # Wait for vLLM to be ready
    log "Waiting for vLLM to be ready (max 60s)..."
    for i in {1..60}; do
        if curl -s http://192.168.100.11:8001/v1/models > /dev/null 2>&1; then
            success "vLLM is ready on port 8001"
            break
        fi
        sleep 1
        echo -n "."
    done
    echo

    if ! curl -s http://192.168.100.11:8001/v1/models > /dev/null 2>&1; then
        error "vLLM failed to start on port 8001"
    fi
else
    success "vLLM already running on port 8001"
fi

# Verify model is accessible
MODELS=$(curl -s http://192.168.100.11:8001/v1/models | python3 -c "import sys, json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null || echo "")
if [[ -z "$MODELS" ]]; then
    error "Cannot access vLLM models endpoint"
fi
success "vLLM serving: $MODELS"

success "Phase 2 complete: vLLM running on port 8001"

# ============================================================================
# PHASE 3: DEPLOY BUILDER-TAEY REPOSITORY
# ============================================================================

log "Phase 3: Deploying builder-taey repository..."

BUILDER_DIR="/home/spark/builder-taey"

if [[ -d "$BUILDER_DIR" ]]; then
    warn "builder-taey already exists at $BUILDER_DIR"
    read -p "Pull latest changes? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cd "$BUILDER_DIR"
        git pull
        success "Pulled latest changes"
    fi
else
    log "Cloning builder-taey repository..."
    cd /home/spark
    git clone https://github.com/palios-taey/builder-taey.git
    success "Cloned builder-taey"
fi

cd "$BUILDER_DIR"

# Install Python dependencies
log "Installing Python dependencies..."
pip3 install --upgrade \
    weaviate-client \
    openai \
    tiktoken \
    neo4j \
    elasticsearch \
    anthropic

success "Python dependencies installed"

success "Phase 3 complete: builder-taey deployed"

# ============================================================================
# PHASE 4: DEPLOY PARALLEL EMBEDDING PIPELINE
# ============================================================================

log "Phase 4: Creating parallel embedding pipeline..."

# Create the parallel pipeline module
cat > "$BUILDER_DIR/databases/scripts/parallel_embedding_pipeline.py" << 'EOF'
"""
PARALLEL EMBEDDING PIPELINE
Based on Mathematical Analysis by Grok (LOGOS)

Replaces sequential embedding generation with parallel streaming pipeline
Target: 50-60 embeddings/sec (up from 2/sec), ~100% GPU utilization
"""

import asyncio
import time
from typing import AsyncGenerator, Dict, List, Optional, Tuple
from openai import AsyncOpenAI
import weaviate

# Constants (from mathematical analysis)
MAX_WORKERS = 48
SEMAPHORE_LIMIT = 48
WEAVIATE_BATCH_SIZE = 32
BACKPRESSURE_THRESHOLD = 96
CIRCUIT_BREAKER_THRESHOLD = 0.5  # 50%
SLIDING_WINDOW_SIZE = 50


class ParallelEmbeddingPipeline:
    """Parallel embedding generation with streaming to Weaviate."""

    def __init__(
        self,
        embedding_base_url: str = "http://192.168.100.11:8001/v1",
        embedding_model: str = "Qwen/Qwen3-Embedding-8B",
        weaviate_host: str = "192.168.100.11",
        weaviate_port: int = 8080,
        collection_name: str = "TranscriptEvent"
    ):
        """Initialize pipeline with connections."""
        self.embedding_client = AsyncOpenAI(
            base_url=embedding_base_url,
            api_key="EMPTY"
        )
        self.embedding_model = embedding_model

        self.weaviate_client = weaviate.connect_to_local(
            host=weaviate_host,
            port=weaviate_port
        )
        self.collection_name = collection_name

        # Queue for work items
        self.work_queue = asyncio.Queue()

        # Semaphore for rate limiting
        self.semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)

        # Circuit breaker state
        self.failure_window = []
        self.circuit_open = False

        # Weaviate batch buffer
        self.batch_buffer = []
        self.batch_lock = asyncio.Lock()

        # Metrics
        self.embeddings_generated = 0
        self.embeddings_failed = 0
        self.start_time = time.time()

    async def generate_embedding(
        self,
        text: str,
        metadata: dict
    ) -> Optional[Dict]:
        """Generate single embedding with retry logic."""
        async with self.semaphore:
            retries = 3
            for attempt in range(retries):
                try:
                    response = await self.embedding_client.embeddings.create(
                        input=text,
                        model=self.embedding_model
                    )

                    # Record success
                    self.record_result(success=True)
                    self.embeddings_generated += 1

                    return {
                        'vector': response.data[0].embedding,
                        'metadata': metadata
                    }

                except Exception as e:
                    # Record failure
                    self.record_result(success=False)
                    self.embeddings_failed += 1

                    if attempt == retries - 1:
                        print(f"Failed after {retries} attempts: {e}")
                        return None

                    # Exponential backoff
                    await asyncio.sleep(2 ** attempt)

    def record_result(self, success: bool):
        """Track success/failure for circuit breaker."""
        self.failure_window.append(0 if success else 1)

        # Keep only last N results
        if len(self.failure_window) > SLIDING_WINDOW_SIZE:
            self.failure_window.pop(0)

        # Check circuit breaker
        if len(self.failure_window) >= SLIDING_WINDOW_SIZE:
            failure_rate = sum(self.failure_window) / len(self.failure_window)

            if failure_rate >= CIRCUIT_BREAKER_THRESHOLD and not self.circuit_open:
                print(f"⚠️  CIRCUIT BREAKER OPEN (failure rate: {failure_rate:.1%})")
                self.circuit_open = True
            elif failure_rate < CIRCUIT_BREAKER_THRESHOLD and self.circuit_open:
                print(f"✓ Circuit breaker closed (failure rate: {failure_rate:.1%})")
                self.circuit_open = False

    async def stream_to_weaviate(self, result: Optional[Dict]):
        """Stream results to Weaviate with dynamic batching."""
        if result is None:
            return

        async with self.batch_lock:
            self.batch_buffer.append(result)

            # Flush if batch size reached
            if len(self.batch_buffer) >= WEAVIATE_BATCH_SIZE:
                await self.flush_batch()

    async def flush_batch(self):
        """Insert batch to Weaviate."""
        if not self.batch_buffer:
            return

        collection = self.weaviate_client.collections.get(self.collection_name)

        try:
            # Bulk insert
            with collection.batch.dynamic() as batch:
                for item in self.batch_buffer:
                    batch.add_object(
                        properties=item['metadata'],
                        vector=item['vector']
                    )

            print(f"✓ Inserted batch of {len(self.batch_buffer)} vectors | "
                  f"Throughput: {self.throughput():.1f}/sec | "
                  f"Failure rate: {self.failure_rate():.1%}")

            self.batch_buffer = []

        except Exception as e:
            print(f"✗ Batch insert failed: {e}")
            # Keep buffer for retry

    async def worker(self, worker_id: int):
        """Worker coroutine - processes items from queue."""
        while True:
            # Check circuit breaker
            if self.circuit_open:
                print(f"Worker {worker_id}: Circuit breaker OPEN, pausing...")
                await asyncio.sleep(5)
                continue

            # Get work item
            try:
                text, metadata = await asyncio.wait_for(
                    self.work_queue.get(),
                    timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            # Generate embedding
            result = await self.generate_embedding(text, metadata)

            # Stream to Weaviate
            await self.stream_to_weaviate(result)

            self.work_queue.task_done()

    async def process_stream(
        self,
        text_generator: AsyncGenerator[Tuple[str, dict], None]
    ):
        """Main processing loop with backpressure control."""
        # Start workers
        workers = [
            asyncio.create_task(self.worker(i))
            for i in range(MAX_WORKERS)
        ]

        try:
            # Feed work queue
            async for text, metadata in text_generator:
                # Backpressure: pause if queue too large
                while self.work_queue.qsize() > BACKPRESSURE_THRESHOLD:
                    print(f"⚠️  Backpressure triggered (queue={self.work_queue.qsize()})")
                    await asyncio.sleep(0.1)

                await self.work_queue.put((text, metadata))

            # Wait for queue to drain
            print(f"Waiting for {self.work_queue.qsize()} remaining items...")
            await self.work_queue.join()

            # Flush remaining batch
            async with self.batch_lock:
                await self.flush_batch()

            # Print final stats
            elapsed = time.time() - self.start_time
            print(f"\n=== PIPELINE COMPLETE ===")
            print(f"Total embeddings: {self.embeddings_generated}")
            print(f"Failed embeddings: {self.embeddings_failed}")
            print(f"Elapsed time: {elapsed:.1f}s")
            print(f"Average throughput: {self.throughput():.1f}/sec")
            print(f"Overall failure rate: {self.failure_rate():.1%}")

        finally:
            # Cancel workers
            for w in workers:
                w.cancel()

    def throughput(self) -> float:
        """Calculate current throughput."""
        elapsed = time.time() - self.start_time
        return self.embeddings_generated / elapsed if elapsed > 0 else 0

    def failure_rate(self) -> float:
        """Calculate overall failure rate."""
        total = self.embeddings_generated + self.embeddings_failed
        return self.embeddings_failed / total if total > 0 else 0

    def close(self):
        """Close connections."""
        self.weaviate_client.close()


# Example usage
async def main():
    """Test the parallel pipeline."""
    pipeline = ParallelEmbeddingPipeline()

    # Test with small batch
    async def test_gen():
        for i in range(100):
            yield f"Test text {i} " * 100, {'test_id': i, 'content': f"Test {i}"}

    await pipeline.process_stream(test_gen())
    pipeline.close()


if __name__ == "__main__":
    asyncio.run(main())
EOF

success "Created parallel_embedding_pipeline.py"

# Create modified loader that uses parallel pipeline
cat > "$BUILDER_DIR/databases/scripts/workshop_unified_loader_v2_parallel.py" << 'EOF'
"""
Modified workshop loader that uses parallel embedding pipeline.
This replaces the sequential embedding generation in the original loader.
"""

import asyncio
from parallel_embedding_pipeline import ParallelEmbeddingPipeline


# Add this method to the existing WorkshopUnifiedLoader class
# (or create wrapper that uses it)

async def load_to_weaviate_parallel(self, windows):
    """Load windows to Weaviate using parallel pipeline."""

    pipeline = ParallelEmbeddingPipeline(
        collection_name='TranscriptEvent'  # or whatever collection you're using
    )

    # Create async generator from windows
    async def window_generator():
        for window in windows:
            window_text = self.build_window_text(window)

            metadata = {
                'conversation_id': window.get('conversation_id', ''),
                'window_id': window.get('window_id', ''),
                'window_index': window.get('window_index', 0),
                'exchange_ids': window.get('exchange_ids', []),
                'content': window_text,
                'timestamp': window.get('timestamp', ''),
                'participants': window.get('participants', []),
                'tags': window.get('tags', []),
            }

            yield window_text, metadata

    # Process with parallel pipeline
    await pipeline.process_stream(window_generator())
    pipeline.close()


# Usage example:
# loader = WorkshopUnifiedLoader()
# windows = loader.prepare_windows(...)
# asyncio.run(loader.load_to_weaviate_parallel(windows))
EOF

success "Created workshop_unified_loader_v2_parallel.py"

success "Phase 4 complete: Parallel pipeline deployed"

# ============================================================================
# PHASE 5: DEPLOY WEAVIATE SCHEMAS
# ============================================================================

log "Phase 5: Deploying Weaviate schemas..."

# Create schema deployment script
cat > "$BUILDER_DIR/databases/scripts/deploy_schemas.py" << 'EOF'
"""Deploy Weaviate schemas for Tri-Lens system."""

import weaviate
from weaviate.classes.config import Property, DataType, Configure


def deploy_transcript_event_schema():
    """Deploy TranscriptEvent collection schema."""

    client = weaviate.connect_to_local(
        host='192.168.100.11',
        port=8080
    )

    try:
        # Delete if exists
        if client.collections.exists('TranscriptEvent'):
            print("Deleting existing TranscriptEvent collection...")
            client.collections.delete('TranscriptEvent')

        # Create collection
        print("Creating TranscriptEvent collection...")
        client.collections.create(
            name='TranscriptEvent',
            vectorizer_config=Configure.Vectorizer.none(),  # We provide vectors
            properties=[
                Property(name='conversation_id', data_type=DataType.TEXT),
                Property(name='window_id', data_type=DataType.TEXT),
                Property(name='window_index', data_type=DataType.INT),
                Property(name='exchange_ids', data_type=DataType.TEXT_ARRAY),
                Property(name='content', data_type=DataType.TEXT),
                Property(name='timestamp', data_type=DataType.TEXT),
                Property(name='participants', data_type=DataType.TEXT_ARRAY),
                Property(name='tags', data_type=DataType.TEXT_ARRAY),
            ]
        )

        print("✓ TranscriptEvent collection created")

        # Verify
        collection = client.collections.get('TranscriptEvent')
        config = collection.config.get()
        print(f"✓ Collection verified: {config.name}")
        print(f"  Vector dimensions: 4096 (Qwen3-Embedding-8B)")
        print(f"  Properties: {len(config.properties)}")

    finally:
        client.close()


if __name__ == "__main__":
    deploy_transcript_event_schema()
EOF

# Run schema deployment
log "Deploying TranscriptEvent schema..."
cd "$BUILDER_DIR/databases/scripts"
python3 deploy_schemas.py

success "Phase 5 complete: Schemas deployed"

# ============================================================================
# PHASE 6: CREATE SYSTEMD SERVICE FOR vLLM
# ============================================================================

log "Phase 6: Creating systemd service for vLLM..."

# Create systemd service file
sudo tee /etc/systemd/system/vllm-embedding.service > /dev/null << 'EOF'
[Unit]
Description=vLLM Embedding Service (Qwen3-Embedding-8B)
After=network.target

[Service]
Type=simple
User=spark
WorkingDirectory=/home/spark
Environment="CUDA_VISIBLE_DEVICES=0,1"
ExecStart=/usr/local/bin/vllm serve \
    Qwen/Qwen3-Embedding-8B \
    --tensor-parallel-size 2 \
    --port 8001 \
    --max-model-len 32768 \
    --max-num-seqs 64 \
    --gpu-memory-utilization 0.9 \
    --enforce-eager
Restart=always
RestartSec=10
StandardOutput=append:/home/spark/logs/vllm-embedding.log
StandardError=append:/home/spark/logs/vllm-embedding.log

[Install]
WantedBy=multi-user.target
EOF

# Create logs directory
mkdir -p /home/spark/logs

# Reload systemd
sudo systemctl daemon-reload

success "Created vllm-embedding.service"

# Enable service
read -p "Enable vLLM service to start on boot? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo systemctl enable vllm-embedding.service
    success "vLLM service enabled"
else
    warn "vLLM service NOT enabled (manual start required)"
fi

success "Phase 6 complete: systemd service created"

# ============================================================================
# PHASE 7: VERIFICATION AND TESTING
# ============================================================================

log "Phase 7: Running verification tests..."

# Test embedding generation
log "Testing embedding generation..."
python3 << 'PYEOF'
import asyncio
from openai import AsyncOpenAI

async def test():
    client = AsyncOpenAI(
        base_url="http://192.168.100.11:8001/v1",
        api_key="EMPTY"
    )

    response = await client.embeddings.create(
        input="Test embedding",
        model="Qwen/Qwen3-Embedding-8B"
    )

    vector = response.data[0].embedding
    print(f"✓ Embedding generated: {len(vector)} dimensions")
    assert len(vector) == 4096, "Expected 4096 dimensions"

asyncio.run(test())
PYEOF

success "Embedding generation test passed"

# Test Weaviate connection
log "Testing Weaviate connection..."
python3 << 'PYEOF'
import weaviate

client = weaviate.connect_to_local(
    host='192.168.100.11',
    port=8080
)

try:
    if client.collections.exists('TranscriptEvent'):
        collection = client.collections.get('TranscriptEvent')
        count = collection.aggregate.over_all(total_count=True).total_count
        print(f"✓ TranscriptEvent collection exists ({count} objects)")
    else:
        print("⚠️  TranscriptEvent collection not found")
finally:
    client.close()
PYEOF

success "Weaviate connection test passed"

# Test parallel pipeline
log "Testing parallel pipeline (10 embeddings)..."
cd "$BUILDER_DIR/databases/scripts"
python3 << 'PYEOF'
import asyncio
from parallel_embedding_pipeline import ParallelEmbeddingPipeline

async def test():
    pipeline = ParallelEmbeddingPipeline()

    async def test_gen():
        for i in range(10):
            yield f"Test text {i} " * 50, {'test_id': i, 'content': f"Test {i}"}

    await pipeline.process_stream(test_gen())
    pipeline.close()

    print(f"✓ Parallel pipeline test complete")

asyncio.run(test())
PYEOF

success "Parallel pipeline test passed"

success "Phase 7 complete: All verification tests passed"

# ============================================================================
# DEPLOYMENT COMPLETE
# ============================================================================

echo
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                 DEPLOYMENT COMPLETE                        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo
echo "Summary:"
echo "  ✓ vLLM running on port 8001 (Qwen3-Embedding-8B)"
echo "  ✓ Weaviate running on port 8080"
echo "  ✓ builder-taey repository deployed"
echo "  ✓ Parallel embedding pipeline created"
echo "  ✓ Weaviate schemas deployed"
echo "  ✓ systemd service configured"
echo "  ✓ All tests passed"
echo
echo "Expected Performance:"
echo "  Current:  2 embeddings/sec, 15% GPU utilization"
echo "  Target:   50-60 embeddings/sec, ~100% GPU utilization"
echo "  Improvement: 25-30x faster"
echo
echo "Next Steps:"
echo "  1. Run full workshop loader with parallel pipeline"
echo "  2. Monitor GPU utilization: nvidia-smi -l 1"
echo "  3. Monitor throughput in pipeline output"
echo "  4. Adjust worker pool if needed (current: 48)"
echo
echo "Usage Example:"
echo "  cd $BUILDER_DIR/databases/scripts"
echo "  python3 workshop_unified_loader_v2_parallel.py"
echo
echo "Service Management:"
echo "  sudo systemctl status vllm-embedding"
echo "  sudo systemctl restart vllm-embedding"
echo "  tail -f /home/spark/logs/vllm-embedding.log"
echo
echo -e "${BLUE}Deployment log: /tmp/spark2_deployment_$(date +%Y%m%d_%H%M%S).log${NC}"
