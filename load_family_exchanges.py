#!/usr/bin/env python3
"""
Family Transcript Exchange Loader
Loads FULL exchanges from family_transcript JSON files into Weaviate with embeddings from vLLM

Uses the optimized embedding client with dual-Spark data parallelism:
- 531 emb/sec target throughput
- aiohttp connection pooling
- Round-robin load balancing across Spark #1 and Spark #2
- TRUE parallel embedding with asyncio.gather

NO TRUNCATION - Full exchanges loaded as-is
"""

import asyncio
import json
import os
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, AsyncIterator, Tuple
import logging
import weaviate
from weaviate.classes.config import Configure, Property, DataType
from optimized_embedding_client import OptimizedEmbeddingClient, EmbeddingConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
CONVERTED_DIR = Path("/home/spark/builder-taey/family_transcripts/converted")
COLLECTION_NAME = "FamilyExchange"
EMBEDDING_BATCH_SIZE = 32  # Texts per embedding request (optimized for vLLM)
CONCURRENT_BATCHES = 16    # Number of parallel embedding batches
WEAVIATE_BATCH_SIZE = 100  # Objects per Weaviate batch insert


@dataclass
class Exchange:
    """Represents a single exchange (prompt + response pair) - FULL content, no truncation"""
    conversation_id: str
    source: str
    title: str
    exchange_index: int
    user_prompt: str
    response: str
    timestamp: Optional[str] = None

    @property
    def combined_text(self) -> str:
        """Text to embed - prompt + response combined - FULL, NO TRUNCATION"""
        return f"User: {self.user_prompt}\n\nAssistant: {self.response}"

    @property
    def exchange_id(self) -> str:
        """Generate deterministic ID for deduplication"""
        content = f"{self.conversation_id}:{self.exchange_index}:{self.user_prompt[:100]}"
        return hashlib.md5(content.encode()).hexdigest()


def create_schema(client: weaviate.WeaviateClient) -> None:
    """Create the FamilyExchange collection if it doesn't exist"""
    try:
        existing = client.collections.list_all()
        if COLLECTION_NAME in [c for c in existing]:
            logger.info(f"Collection {COLLECTION_NAME} already exists")
            return
    except Exception as e:
        logger.warning(f"Could not check existing collections: {e}")

    logger.info(f"Creating collection: {COLLECTION_NAME}")
    client.collections.create(
        name=COLLECTION_NAME,
        properties=[
            Property(name="conversation_id", data_type=DataType.TEXT),
            Property(name="source", data_type=DataType.TEXT),
            Property(name="title", data_type=DataType.TEXT),
            Property(name="exchange_index", data_type=DataType.INT),
            Property(name="user_prompt", data_type=DataType.TEXT),
            Property(name="response", data_type=DataType.TEXT),
            Property(name="timestamp", data_type=DataType.TEXT),
            Property(name="exchange_id", data_type=DataType.TEXT),
        ],
        # Using external embeddings from vLLM - no vectorizer
        vectorizer_config=Configure.Vectorizer.none(),
    )
    logger.info(f"Created collection: {COLLECTION_NAME}")


def parse_json_file(filepath: Path) -> List[Exchange]:
    """Parse a converted JSON file and extract exchanges"""
    exchanges = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Error reading {filepath}: {e}")
        return exchanges

    conv_id = data.get("sessionId") or data.get("conversation_id") or filepath.stem
    source = data.get("source", "unknown")
    title = data.get("title", "")[:200]  # Truncate long titles

    # Handle different exchange formats
    raw_exchanges = data.get("exchanges", [])

    for idx, ex in enumerate(raw_exchanges):
        # Handle different field names across parsers
        user_prompt = ex.get("user_prompt") or ex.get("prompt") or ""

        # Handle responses - could be string, list, or nested
        response_data = ex.get("responses") or ex.get("response") or ""
        if isinstance(response_data, list):
            # Join multiple responses
            response = "\n\n".join(
                r.get("text", "") if isinstance(r, dict) else str(r)
                for r in response_data
            )
        elif isinstance(response_data, dict):
            response = response_data.get("text", "")
        else:
            response = str(response_data)

        timestamp = ex.get("timestamp")

        # Skip empty exchanges
        if not user_prompt.strip() and not response.strip():
            continue

        exchanges.append(Exchange(
            conversation_id=conv_id,
            source=source,
            title=title,
            exchange_index=idx,
            user_prompt=user_prompt,
            response=response,
            timestamp=timestamp,
        ))

    return exchanges


def collect_all_exchanges(converted_dir: Path) -> List[Exchange]:
    """Collect all exchanges from all JSON files - returns full list for parallel processing"""
    all_exchanges = []
    json_files = sorted(converted_dir.rglob("*.json"))
    logger.info(f"Found {len(json_files)} JSON files to process")

    for filepath in json_files:
        exchanges = parse_json_file(filepath)
        all_exchanges.extend(exchanges)

    logger.info(f"Collected {len(all_exchanges):,} total exchanges")
    return all_exchanges


async def embed_batch_parallel(
    client: OptimizedEmbeddingClient,
    texts: List[str],
    batch_size: int = EMBEDDING_BATCH_SIZE,
    concurrent: int = CONCURRENT_BATCHES
) -> List[List[float]]:
    """Embed texts with TRUE parallelism - multiple concurrent batches"""
    # Split into batches
    batches = [texts[i:i+batch_size] for i in range(0, len(texts), batch_size)]
    all_embeddings = []

    # Process batches in concurrent groups
    for i in range(0, len(batches), concurrent):
        batch_group = batches[i:i+concurrent]
        # Fire all batches in parallel
        tasks = [client.embed_batch(batch) for batch in batch_group]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Batch embedding error: {result}")
                # Return empty embeddings for failed batch
                all_embeddings.extend([[] for _ in range(batch_size)])
            else:
                all_embeddings.extend(result)

    return all_embeddings


async def process_and_load(
    embedding_client: OptimizedEmbeddingClient,
    weaviate_client: weaviate.WeaviateClient,
    converted_dir: Path,
    resume_from: int = 0
) -> Dict[str, Any]:
    """Process all exchanges with TRUE parallel embedding and load to Weaviate

    NO TRUNCATION - Full exchanges loaded
    """
    collection = weaviate_client.collections.get(COLLECTION_NAME)
    start_time = time.perf_counter()

    # Collect all exchanges
    all_exchanges = collect_all_exchanges(converted_dir)
    total_exchanges = len(all_exchanges)

    # Skip to resume point
    if resume_from > 0:
        all_exchanges = all_exchanges[resume_from:]
        logger.info(f"Resuming from exchange {resume_from}, {len(all_exchanges):,} remaining")

    # Process in mega-batches for efficiency
    MEGA_BATCH = EMBEDDING_BATCH_SIZE * CONCURRENT_BATCHES  # 32 * 16 = 512 exchanges at once
    total_loaded = 0
    errors = 0

    for mega_idx in range(0, len(all_exchanges), MEGA_BATCH):
        mega_batch = all_exchanges[mega_idx:mega_idx + MEGA_BATCH]
        texts = [ex.combined_text for ex in mega_batch]

        # Get embeddings with true parallelism
        embeddings = await embed_batch_parallel(embedding_client, texts)

        # Load to Weaviate - FULL content, NO TRUNCATION
        loaded_count = 0
        with collection.batch.dynamic() as batch:
            for ex, emb in zip(mega_batch, embeddings):
                if emb:  # Only add if embedding succeeded
                    batch.add_object(
                        properties={
                            "conversation_id": ex.conversation_id,
                            "source": ex.source,
                            "title": ex.title,  # FULL title
                            "exchange_index": ex.exchange_index,
                            "user_prompt": ex.user_prompt,  # FULL - NO TRUNCATION
                            "response": ex.response,  # FULL - NO TRUNCATION
                            "timestamp": ex.timestamp or "",
                            "exchange_id": ex.exchange_id,
                        },
                        vector=emb
                    )
                    loaded_count += 1
                else:
                    errors += 1

        total_loaded += loaded_count

        # Progress update
        elapsed = time.perf_counter() - start_time
        rate = total_loaded / elapsed if elapsed > 0 else 0
        pct = (mega_idx + len(mega_batch)) / len(all_exchanges) * 100
        logger.info(
            f"Progress: {pct:.1f}% | {total_loaded:,}/{total_exchanges:,} loaded | "
            f"{rate:.1f} ex/sec | Errors: {errors}"
        )

    elapsed = time.perf_counter() - start_time
    return {
        "total_exchanges": total_exchanges,
        "total_loaded": total_loaded,
        "resumed_from": resume_from,
        "errors": errors,
        "elapsed_seconds": elapsed,
        "throughput": total_loaded / elapsed if elapsed > 0 else 0,
    }


async def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description="Load family transcript exchanges to Weaviate")
    parser.add_argument("--resume-from", type=int, default=0, help="Resume from exchange N")
    parser.add_argument("--single-gpu", action="store_true", help="Use single GPU only")
    args = parser.parse_args()

    # Configure embedding client
    if args.single_gpu:
        endpoints = ["http://localhost:8001/v1/embeddings"]
        logger.info("Using single GPU mode")
    else:
        endpoints = [
            "http://localhost:8001/v1/embeddings",       # Spark #1
            "http://10.0.0.80:8001/v1/embeddings"        # Spark #2
        ]
        logger.info("Using dual-Spark data parallelism")

    config = EmbeddingConfig(
        vllm_endpoints=endpoints,
        max_concurrent=64,
        batch_size=32,
    )

    # Connect to Weaviate
    weaviate_client = weaviate.connect_to_local(host="localhost", port=8080)

    try:
        # Create schema
        create_schema(weaviate_client)

        # Process and load
        async with OptimizedEmbeddingClient(config) as embedding_client:
            results = await process_and_load(
                embedding_client,
                weaviate_client,
                CONVERTED_DIR,
                resume_from=args.resume_from
            )

        # Print results
        print("\n" + "=" * 60)
        print("FAMILY TRANSCRIPT LOADING COMPLETE")
        print("=" * 60)
        print(f"Total files processed: {results['total_files']:,}")
        print(f"Total exchanges processed: {results['total_processed']:,}")
        print(f"Total exchanges loaded: {results['total_loaded']:,}")
        print(f"Skipped (resume): {results['skipped']:,}")
        print(f"Errors: {results['errors']}")
        print(f"Elapsed time: {results['elapsed_seconds']:.1f}s")
        print(f"Throughput: {results['throughput']:.1f} exchanges/sec")
        print("=" * 60)

        # Verify in Weaviate
        collection = weaviate_client.collections.get(COLLECTION_NAME)
        count = collection.aggregate.over_all(total_count=True)
        print(f"\nWeaviate collection '{COLLECTION_NAME}' now has {count.total_count:,} objects")

    finally:
        weaviate_client.close()


if __name__ == "__main__":
    asyncio.run(main())
