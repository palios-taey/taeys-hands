#!/usr/bin/env python3
"""
Fast Transcript Loader - Built on optimized_embedding_client.py

NO WRAPPERS. NO SERIAL PIPELINES. PURE PARALLEL.
NO TRUNCATION - Chunks large exchanges with overlap and linking.

Uses asyncio.gather() for TRUE parallel batch processing.
Target: 500+ emb/sec on dual-Spark setup.
"""

import asyncio
import json
import time
import hashlib
import uuid as uuid_module
from pathlib import Path
from typing import List, Dict, Any, Tuple
import weaviate

from optimized_embedding_client import OptimizedEmbeddingClient, EmbeddingConfig

# =============================================================================
# CONFIGURATION
# =============================================================================

CONVERTED_DIR = Path("/home/spark/builder-taey/family_transcripts/converted")
PLATFORMS = ['claude_chat', 'claude_code', 'chatgpt', 'gemini', 'grok', 'perplexity']

# Weaviate on Spark #2
WEAVIATE_HOST = "10.0.0.80"
WEAVIATE_PORT = 8080
COLLECTION_NAME = "TranscriptEvent"

# Parallel processing - THESE ARE THE KEY SETTINGS
MEGA_BATCH_SIZE = 512       # Texts to process in one parallel burst
CONCURRENT_BATCHES = 16     # How many embed_batch() calls to fire simultaneously
EMBEDDING_BATCH_SIZE = 32   # Texts per single vLLM request
WEAVIATE_BATCH_SIZE = 200   # Objects per Weaviate insert

# Token limits - NO TRUNCATION, chunk with overlap instead
# vLLM limit is 32,768 - use 30K with actual token counting (no estimation errors)
MAX_TOKENS_PER_BATCH = 30000  # Keep under 32K vLLM limit
MAX_TOKENS_PER_TEXT = 30000   # Chunk files larger than this
CHUNK_OVERLAP_TOKENS = 2000   # Overlap for context preservation
VLLM_HARD_LIMIT = 32000       # Absolute max - safety check

# =============================================================================
# TOKENIZER (Qwen3 for accurate counts)
# =============================================================================

_tokenizer = None

def get_tokenizer():
    """Lazy load Qwen3 tokenizer."""
    global _tokenizer
    if _tokenizer is None:
        print("Loading Qwen3 tokenizer...")
        from transformers import AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-Embedding-8B", trust_remote_code=True)
        print(f"Tokenizer loaded. Vocab size: {_tokenizer.vocab_size:,}")
    return _tokenizer

def count_tokens(text: str) -> int:
    """Count tokens using Qwen3 tokenizer."""
    return len(get_tokenizer().encode(text, add_special_tokens=False))


# =============================================================================
# CHUNKING (Preserve meaning with overlap)
# =============================================================================

def chunk_large_text(text: str, max_tokens: int = MAX_TOKENS_PER_TEXT,
                     overlap_tokens: int = CHUNK_OVERLAP_TOKENS) -> List[Tuple[str, int, int]]:
    """
    Chunk large text with overlap for context preservation.

    NO TRUNCATION - every word is preserved.
    Uses ACTUAL Qwen3 token counts, not estimates.

    Returns: List of (chunk_text, chunk_index, total_chunks)
    """
    tokenizer = get_tokenizer()
    tokens = tokenizer.encode(text, add_special_tokens=False)
    total_tokens = len(tokens)

    if total_tokens <= max_tokens:
        return [(text, 0, 1)]

    # Chunk by actual tokens
    chunks = []
    start_idx = 0

    while start_idx < total_tokens:
        end_idx = min(start_idx + max_tokens, total_tokens)

        # Get chunk tokens and decode back to text
        chunk_tokens = tokens[start_idx:end_idx]
        chunk_text = tokenizer.decode(chunk_tokens)

        # Verify chunk is under limit (should always be true now)
        actual_count = len(chunk_tokens)
        if actual_count > VLLM_HARD_LIMIT:
            # Safety: if still too large, use smaller chunk
            end_idx = start_idx + VLLM_HARD_LIMIT - 1000  # Safety margin
            chunk_tokens = tokens[start_idx:end_idx]
            chunk_text = tokenizer.decode(chunk_tokens)

        chunks.append(chunk_text)

        # Next chunk starts with overlap (by tokens)
        if end_idx < total_tokens:
            start_idx = end_idx - overlap_tokens
        else:
            break

    # Return with indices
    total = len(chunks)
    return [(chunk, idx, total) for idx, chunk in enumerate(chunks)]


# =============================================================================
# TRANSCRIPT LOADING (NO TRUNCATION - chunks with overlap and linking)
# =============================================================================

def load_all_transcripts() -> List[Dict[str, Any]]:
    """Load ALL transcript exchanges into memory. NO TRUNCATION.

    Large exchanges (>30K tokens) are chunked with overlap for context.
    Each chunk tracks chunk_index/total_chunks for linking.
    """
    all_items = []
    chunked_count = 0
    total_chunks_created = 0

    for platform in PLATFORMS:
        platform_dir = CONVERTED_DIR / platform
        if not platform_dir.exists():
            continue

        for json_file in sorted(platform_dir.glob('*.json')):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)

                session_id = data.get('sessionId', json_file.stem)
                title = data.get('title', 'Untitled')[:200]
                converter = data.get('converter', 'unknown').replace('_parser', '')

                for i, exchange in enumerate(data.get('exchanges', [])):
                    # Build text - handle both formats
                    text_parts = []

                    # Try 'user_prompt' first, then 'prompt' (claude_code uses 'prompt')
                    user_prompt = exchange.get('user_prompt', '') or exchange.get('prompt', '')
                    if user_prompt:
                        text_parts.append(f"User: {user_prompt}")

                    # Try 'responses' (list) first, then 'response' (string)
                    responses = exchange.get('responses', [])
                    if responses:
                        for response in responses:
                            response_text = response.get('text', '') if isinstance(response, dict) else str(response)
                            if response_text:
                                text_parts.append(f"Assistant: {response_text}")
                    else:
                        # Fall back to 'response' as string
                        response_text = exchange.get('response', '')
                        if response_text:
                            text_parts.append(f"Assistant: {response_text}")

                    if not text_parts:
                        continue

                    text = "\n\n".join(text_parts)
                    if len(text) < 100:
                        continue

                    # NO TRUNCATION - chunk large texts with overlap instead
                    # Generate base UUID from original exchange for linking
                    base_hash = hashlib.sha256(f"{session_id}:{i}".encode()).hexdigest()
                    base_uuid = str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, base_hash))

                    # Chunk if needed (preserves all content with overlap)
                    chunks = chunk_large_text(text)

                    if len(chunks) > 1:
                        chunked_count += 1
                        total_chunks_created += len(chunks)

                    for chunk_text, chunk_idx, total_chunks in chunks:
                        # UUID includes chunk index for dedup
                        content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
                        uuid = str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, content_hash))

                        all_items.append({
                            'uuid': uuid,
                            'text': chunk_text,
                            'token_count': count_tokens(chunk_text),
                            'properties': {
                                'session_id': str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, session_id)),
                                'conversation_id': session_id,
                                'title': title,
                                'platform': converter,
                                'exchange_index': i,
                                'timestamp': exchange.get('timestamp', ''),
                                'content': chunk_text,
                                'content_preview': chunk_text[:200],
                                # Chunk linking
                                'chunk_index': chunk_idx,
                                'total_chunks': total_chunks,
                                'original_exchange_uuid': base_uuid,
                            }
                        })
            except Exception as e:
                print(f"Error loading {json_file}: {e}")
                continue

    if chunked_count > 0:
        print(f"      Chunked {chunked_count} large exchanges into {total_chunks_created} chunks (with overlap)")

    return all_items


# =============================================================================
# TOKEN-AWARE BATCHING (ensures each vLLM request < 28K tokens)
# =============================================================================

def batch_items_by_tokens(items: List[Dict], max_tokens: int = MAX_TOKENS_PER_BATCH) -> List[List[Dict]]:
    """
    Batch items by token count to ensure each batch fits within vLLM limits.

    NO fixed item count - batches are sized by tokens.
    """
    batches = []
    current_batch = []
    current_tokens = 0

    for item in items:
        item_tokens = item.get('token_count', 1000)  # Default estimate if missing

        # If single item exceeds limit, it goes in its own batch
        if item_tokens > max_tokens:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            batches.append([item])  # Single item batch
            continue

        # Check if adding this item would exceed limit
        if current_tokens + item_tokens > max_tokens:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(item)
        current_tokens += item_tokens

    # Don't forget the last batch
    if current_batch:
        batches.append(current_batch)

    return batches


# =============================================================================
# PARALLEL EMBEDDING (RAW AIOHTTP - FAST, 256 connections)
# =============================================================================

import aiohttp

# Both Sparks now running V0 scheduler (VLLM_USE_V1=0) - stable
VLLM_ENDPOINTS = [
    "http://localhost:8001/v1/embeddings",      # Spark #1 (V0 scheduler)
    "http://10.0.0.80:8001/v1/embeddings"       # Spark #2 (V0 scheduler)
]
MODEL_NAME = "Qwen/Qwen3-Embedding-8B"


async def embed_one_batch(
    session: aiohttp.ClientSession,
    texts: List[str],
    endpoint: str
) -> List[List[float]]:
    """Embed a single batch via HTTP POST."""
    payload = {"model": MODEL_NAME, "input": texts}
    try:
        async with session.post(endpoint, json=payload) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                print(f"vLLM error {resp.status} from {endpoint}: {error_text[:200]}")
                return [None] * len(texts)
            result = await resp.json()
            return [item["embedding"] for item in result["data"]]
    except Exception as e:
        print(f"Request error on {endpoint}: {e}")
        return [None] * len(texts)


async def embed_token_batches(
    session: aiohttp.ClientSession,
    batches: List[List[Dict]]
) -> List[List[float]]:
    """
    Embed token-bounded batches using RAW parallel HTTP.

    Fires ALL batches at once across both endpoints.
    Each batch is already sized by tokens to fit within vLLM limits.
    """
    # Fire ALL batches in parallel - round-robin endpoints
    tasks = []
    for i, batch in enumerate(batches):
        texts = [item['text'] for item in batch]
        endpoint = VLLM_ENDPOINTS[i % len(VLLM_ENDPOINTS)]
        tasks.append(embed_one_batch(session, texts, endpoint))

    results = await asyncio.gather(*tasks)

    # Flatten results (preserves order)
    all_embeddings = []
    for batch_result in results:
        all_embeddings.extend(batch_result)

    return all_embeddings


# Legacy function for backwards compatibility
async def embed_mega_batch_raw(
    session: aiohttp.ClientSession,
    texts: List[str]
) -> List[List[float]]:
    """
    LEGACY: Embed a mega-batch using RAW parallel HTTP.
    Prefer embed_token_batches() for token-aware batching.
    """
    # Split into small batches by fixed count (legacy behavior)
    batches = [
        texts[i:i + EMBEDDING_BATCH_SIZE]
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE)
    ]

    # Fire ALL batches in parallel - round-robin endpoints
    tasks = []
    for i, batch in enumerate(batches):
        endpoint = VLLM_ENDPOINTS[i % len(VLLM_ENDPOINTS)]
        tasks.append(embed_one_batch(session, batch, endpoint))

    results = await asyncio.gather(*tasks)

    # Flatten results
    all_embeddings = []
    for batch_result in results:
        all_embeddings.extend(batch_result)

    return all_embeddings


# Keep old version for reference
async def embed_mega_batch(
    client: OptimizedEmbeddingClient,
    texts: List[str]
) -> List[List[float]]:
    """OLD version using OptimizedEmbeddingClient (slower due to semaphore)."""
    batches = [
        texts[i:i + EMBEDDING_BATCH_SIZE]
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE)
    ]

    all_embeddings = []
    for i in range(0, len(batches), CONCURRENT_BATCHES):
        batch_group = batches[i:i + CONCURRENT_BATCHES]
        tasks = [client.embed_batch(batch) for batch in batch_group]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                all_embeddings.extend([None] * EMBEDDING_BATCH_SIZE)
            else:
                all_embeddings.extend(result)

    return all_embeddings


# =============================================================================
# MAIN PROCESSING
# =============================================================================

async def process_transcripts():
    """Process all transcripts with maximum parallelism.

    Features:
    - NO TRUNCATION: Large exchanges chunked with overlap
    - Token-aware batching: Each vLLM request < 28K tokens
    - FAST: 256 connections, asyncio.gather for parallel
    - Chunk linking: chunk_index/total_chunks/original_exchange_uuid
    """

    print("=" * 70)
    print("FAST TRANSCRIPT LOADER (NO TRUNCATION)")
    print("=" * 70)
    print(f"Max tokens per batch: {MAX_TOKENS_PER_BATCH:,}")
    print(f"Max tokens per text: {MAX_TOKENS_PER_TEXT:,}")
    print(f"Chunk overlap: {CHUNK_OVERLAP_TOKENS:,} tokens")
    print(f"Endpoints: {VLLM_ENDPOINTS}")
    print("=" * 70)

    # Load all transcripts (with chunking for large exchanges)
    print("\n[1/5] Loading transcripts with token counting...")
    start = time.perf_counter()
    all_items = load_all_transcripts()
    load_time = time.perf_counter() - start
    total_tokens = sum(item.get('token_count', 0) for item in all_items)
    print(f"      Loaded {len(all_items):,} items ({total_tokens:,} tokens) in {load_time:.1f}s")

    if not all_items:
        print("No items to process!")
        return

    # Connect to Weaviate
    print("\n[2/5] Connecting to Weaviate...")
    weaviate_client = weaviate.connect_to_custom(
        http_host=WEAVIATE_HOST,
        http_port=WEAVIATE_PORT,
        http_secure=False,
        grpc_host=WEAVIATE_HOST,
        grpc_port=50051,
        grpc_secure=False,
    )
    collection = weaviate_client.collections.get(COLLECTION_NAME)

    # Load existing UUIDs for dedup
    print("      Loading existing UUIDs for dedup...")
    existing_uuids = set()
    for obj in collection.iterator():
        existing_uuids.add(str(obj.uuid))
    print(f"      Found {len(existing_uuids):,} existing objects")

    # Filter out duplicates
    new_items = [item for item in all_items if item['uuid'] not in existing_uuids]
    print(f"      New items to process: {len(new_items):,}")

    if not new_items:
        print("\nAll items already loaded!")
        weaviate_client.close()
        return

    # Create token-bounded batches
    print("\n[3/5] Creating token-bounded batches...")
    batches = batch_items_by_tokens(new_items, MAX_TOKENS_PER_BATCH)
    batch_tokens = [sum(item.get('token_count', 0) for item in b) for b in batches]
    batch_sizes = [len(b) for b in batches]
    print(f"      {len(batches)} batches")
    print(f"      Tokens: avg={sum(batch_tokens)//len(batches):,}, max={max(batch_tokens):,}")
    print(f"      Items:  avg={sum(batch_sizes)//len(batches)}, max={max(batch_sizes)}")

    # Configure raw aiohttp session (256 connections - FAST)
    print("\n[4/5] Initializing aiohttp session...")
    connector = aiohttp.TCPConnector(limit=256, keepalive_timeout=60.0)
    timeout = aiohttp.ClientTimeout(total=300.0)

    # Process batches with parallel embedding
    print("\n[5/5] Processing embeddings (parallel)...")
    total_embedded = 0
    total_loaded = 0
    errors = 0
    start_time = time.perf_counter()

    # Process in groups of batches to allow progress updates
    # Reduced from 64 to 8 to avoid overwhelming vLLM with massive token loads
    PARALLEL_GROUP = 8  # Fire 8 batches at once (~200K tokens max)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for group_start in range(0, len(batches), PARALLEL_GROUP):
            group_end = min(group_start + PARALLEL_GROUP, len(batches))
            batch_group = batches[group_start:group_end]

            # Get embeddings with parallel HTTP (all batches in group at once)
            batch_start = time.perf_counter()
            embeddings = await embed_token_batches(session, batch_group)
            batch_time = time.perf_counter() - batch_start

            # Flatten batch items for pairing with embeddings
            group_items = [item for batch in batch_group for item in batch]

            # Load to Weaviate
            weaviate_start = time.perf_counter()
            loaded = 0
            with collection.batch.dynamic() as weaviate_batch:
                for item, emb in zip(group_items, embeddings):
                    if emb is not None:
                        weaviate_batch.add_object(
                            uuid=item['uuid'],
                            properties=item['properties'],
                            vector=emb
                        )
                        loaded += 1
                    else:
                        errors += 1
            weaviate_time = time.perf_counter() - weaviate_start

            total_embedded += len(group_items)
            total_loaded += loaded

            # Progress
            elapsed = time.perf_counter() - start_time
            rate = total_embedded / elapsed if elapsed > 0 else 0
            pct = total_embedded / len(new_items) * 100
            group_tokens = sum(sum(item.get('token_count', 0) for item in b) for b in batch_group)

            print(f"      {pct:5.1f}% | {total_embedded:,}/{len(new_items):,} | "
                  f"{rate:.0f} emb/sec | {group_tokens:,} tokens | "
                  f"embed: {batch_time:.1f}s, weaviate: {weaviate_time:.1f}s | errors: {errors}")

    # Final stats
    elapsed = time.perf_counter() - start_time

    print("\n" + "=" * 60)
    print("COMPLETE")
    print("=" * 60)
    print(f"Total processed: {total_embedded:,}")
    print(f"Total loaded to Weaviate: {total_loaded:,}")
    print(f"Errors: {errors}")
    print(f"Time: {elapsed:.1f}s")
    print(f"THROUGHPUT: {total_embedded / elapsed:.0f} emb/sec")
    print("=" * 60)

    # Verify
    count = collection.aggregate.over_all(total_count=True)
    print(f"\nWeaviate '{COLLECTION_NAME}' now has {count.total_count:,} objects")

    weaviate_client.close()


async def benchmark():
    """Quick benchmark to verify throughput using RAW parallel HTTP."""
    print("=" * 60)
    print("THROUGHPUT BENCHMARK (RAW AIOHTTP)")
    print("=" * 60)

    # Generate test data - short texts for max throughput
    n_texts = 2048
    test_texts = [f"test {i}" for i in range(n_texts)]

    print(f"Texts: {n_texts}")
    print(f"Batch size: {EMBEDDING_BATCH_SIZE}")
    print(f"Endpoints: {VLLM_ENDPOINTS}")
    print()

    connector = aiohttp.TCPConnector(limit=256, keepalive_timeout=60.0)
    timeout = aiohttp.ClientTimeout(total=120.0)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        start = time.perf_counter()

        embeddings = await embed_mega_batch_raw(session, test_texts)

        elapsed = time.perf_counter() - start
        success = sum(1 for e in embeddings if e is not None)

        print(f"Embedded: {success:,}")
        print(f"Time: {elapsed:.2f}s")
        print(f"THROUGHPUT: {success / elapsed:.0f} emb/sec")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "benchmark":
        asyncio.run(benchmark())
    else:
        asyncio.run(process_transcripts())
