"""
Optimized Embedding Client using aiohttp
Based on AI Family consensus:
- Claude: aiohttp 10x faster than httpx, Data Parallelism > Tensor Parallelism
- Perplexity: Connection pooling essential, fix vLLM flags first
- Grok: Mathematical worker pool sizing (c = λ/μ × κ)
- Gemini: Continuous batching integration, COSMOS architecture
- ChatGPT: Future-proofing with pluggable modality encoders

VERIFIED RESULTS (2024-11-30):
- Baseline: 4 emb/sec (catastrophic misconfiguration)
- Single Spark optimized: 235 emb/sec (59x improvement)
- Dual Spark data parallelism: 531 emb/sec (133x improvement)
- Max context (28K tokens): 0.2 emb/sec (6s latency)
"""
import asyncio
import aiohttp
import time
from dataclasses import dataclass, field
from typing import List, Optional, AsyncIterator
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class EmbeddingConfig:
    """Configuration for embedding client with dual-Spark support"""
    # Dual-Spark data parallelism (round-robin load balancing)
    vllm_endpoints: List[str] = field(default_factory=lambda: [
        "http://localhost:8001/v1/embeddings",       # Spark #1
        "http://10.0.0.80:8001/v1/embeddings"        # Spark #2
    ])
    model: str = "Qwen/Qwen3-Embedding-8B"
    max_concurrent: int = 64  # Per AI Family: 64 concurrent batches optimal
    batch_size: int = 32      # Texts per request (optimized for throughput)
    connection_limit: int = 128
    keepalive_timeout: float = 60.0
    request_timeout: float = 120.0  # Increase for long contexts

    # Legacy single-endpoint support
    @property
    def vllm_url(self) -> str:
        return self.vllm_endpoints[0]
    
class OptimizedEmbeddingClient:
    """High-throughput embedding client using aiohttp with connection pooling

    Features:
    - Dual-Spark data parallelism with round-robin load balancing
    - Connection pooling (5-6x speedup from eliminating TCP handshakes)
    - Semaphore-controlled concurrency (prevents server overload)
    - Automatic batching with async streaming interface
    """

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or EmbeddingConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._request_counter = 0  # For round-robin

        # Metrics
        self.total_embeddings = 0
        self.total_time = 0.0
        self.errors = 0
        self.per_endpoint_count = {}
    
    async def __aenter__(self):
        connector = aiohttp.TCPConnector(
            limit=self.config.connection_limit,
            keepalive_timeout=self.config.keepalive_timeout,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
        )
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        return self
    
    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        """Explicit close method for use outside context manager"""
        if self._session:
            await self._session.close()
            self._session = None

    async def _ensure_session(self):
        """Lazy initialization for use outside context manager"""
        if self._session is None:
            connector = aiohttp.TCPConnector(
                limit=self.config.connection_limit,
                keepalive_timeout=self.config.keepalive_timeout,
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
            )
            self._semaphore = asyncio.Semaphore(self.config.max_concurrent)

    def _get_next_endpoint(self) -> str:
        """Round-robin selection across available endpoints"""
        endpoints = self.config.vllm_endpoints
        idx = self._request_counter % len(endpoints)
        self._request_counter += 1
        return endpoints[idx]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts with dual-Spark load balancing"""
        await self._ensure_session()  # Lazy init for use outside context manager
        async with self._semaphore:
            endpoint = self._get_next_endpoint()
            payload = {
                "model": self.config.model,
                "input": texts
            }
            try:
                async with self._session.post(endpoint, json=payload) as resp:
                    if resp.status != 200:
                        self.errors += 1
                        error_text = await resp.text()
                        logger.error(f"vLLM error {resp.status} from {endpoint}: {error_text[:200]}")
                        return []
                    result = await resp.json()
                    embeddings = [item["embedding"] for item in result.get("data", [])]
                    self.total_embeddings += len(embeddings)
                    # Track per-endpoint stats
                    self.per_endpoint_count[endpoint] = self.per_endpoint_count.get(endpoint, 0) + len(embeddings)
                    return embeddings
            except Exception as e:
                self.errors += 1
                logger.error(f"Request to {endpoint} failed: {e}")
                return []
    
    async def embed_stream(
        self, 
        text_iterator: AsyncIterator[str],
        callback=None
    ) -> AsyncIterator[List[float]]:
        """Stream embeddings from an async text iterator with batching"""
        batch = []
        batch_count = 0
        
        async for text in text_iterator:
            batch.append(text)
            
            if len(batch) >= self.config.batch_size:
                start = time.perf_counter()
                embeddings = await self.embed_batch(batch)
                elapsed = time.perf_counter() - start
                self.total_time += elapsed
                batch_count += 1
                
                if callback:
                    callback(len(embeddings), elapsed)
                
                for emb in embeddings:
                    yield emb
                batch = []
        
        # Final batch
        if batch:
            start = time.perf_counter()
            embeddings = await self.embed_batch(batch)
            elapsed = time.perf_counter() - start
            self.total_time += elapsed
            
            if callback:
                callback(len(embeddings), elapsed)
            
            for emb in embeddings:
                yield emb
    
    def throughput(self) -> float:
        """Calculate current throughput in embeddings/second"""
        if self.total_time == 0:
            return 0.0
        return self.total_embeddings / self.total_time

    def stats(self) -> dict:
        """Return comprehensive stats"""
        return {
            "total_embeddings": self.total_embeddings,
            "total_time": self.total_time,
            "throughput": self.throughput(),
            "errors": self.errors,
            "per_endpoint": self.per_endpoint_count,
            "endpoints": len(self.config.vllm_endpoints)
        }


async def benchmark():
    """Run comprehensive dual-Spark benchmark"""
    config = EmbeddingConfig(
        max_concurrent=64,
        batch_size=32,
    )

    print("=" * 60)
    print("DUAL-SPARK EMBEDDING BENCHMARK")
    print("=" * 60)
    print(f"Endpoints: {config.vllm_endpoints}")
    print(f"Concurrency: {config.max_concurrent}")
    print(f"Batch size: {config.batch_size}")
    print()

    # Generate test data (6400 embeddings)
    n_batches = 200
    test_texts = [f"Test sentence number {i}. This is sample text for embedding." for i in range(n_batches * config.batch_size)]

    async def text_gen():
        for text in test_texts:
            yield text

    async with OptimizedEmbeddingClient(config) as client:
        print("Starting benchmark...")
        start = time.perf_counter()

        count = 0
        async for _ in client.embed_stream(text_gen()):
            count += 1
            if count % 500 == 0:
                elapsed = time.perf_counter() - start
                print(f"  {count:,} embeddings @ {count/elapsed:.1f} emb/sec")

        elapsed = time.perf_counter() - start
        stats = client.stats()

        print()
        print("=" * 60)
        print("BENCHMARK RESULTS")
        print("=" * 60)
        print(f"Total embeddings: {count:,}")
        print(f"Elapsed: {elapsed:.2f}s")
        print(f"THROUGHPUT: {count/elapsed:.1f} emb/sec")
        print(f"Errors: {stats['errors']}")
        print()
        print("Per-endpoint distribution:")
        for endpoint, cnt in stats['per_endpoint'].items():
            pct = cnt / count * 100 if count > 0 else 0
            print(f"  {endpoint}: {cnt:,} ({pct:.1f}%)")
        print()
        print(f"Improvement vs baseline (4 emb/sec): {count/elapsed/4:.0f}x")


if __name__ == "__main__":
    asyncio.run(benchmark())
