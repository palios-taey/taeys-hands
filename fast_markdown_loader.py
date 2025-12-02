#!/usr/bin/env python3
"""
Fast Markdown Loader - Uses fast_transcript_loader infrastructure
Leverages Qwen3 tokenizer and parallel embedding from existing optimized code.
"""

import asyncio
import hashlib
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import logging
import aiohttp
import weaviate
from weaviate.classes.config import Configure, Property, DataType

# Import from fast_transcript_loader (the optimized implementation)
from fast_transcript_loader import (
    get_tokenizer,
    count_tokens,
    chunk_large_text,
    batch_items_by_tokens,
    VLLM_ENDPOINTS,
    MAX_TOKENS_PER_BATCH,
    MAX_TOKENS_PER_TEXT,
    CHUNK_OVERLAP_TOKENS,
    MODEL_NAME,
)

# Parallel batch processing - match fast_transcript_loader for 10+ emb/sec
PARALLEL_GROUP = 8  # Fire 8 batches at once (~200K tokens max)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

COLLECTION_NAME = "MarkdownDocument"

# File filtering - exclude backups, caches, etc.
EXCLUDE_PATTERNS = [
    'node_modules', '.cache', '__pycache__', '.venv', 'site-packages',
    'nemo-env', '.git', '.npm', '.local/share', '.cargo',
    '.ipynb_checkpoints', 'backup', 'backups', '-backup-', '_backup_',
    '.Trash', '.trash', 'archive_', '_archive', '/archive/', 'Archives',
    'h200-backup'
]


def should_exclude(filepath: str) -> bool:
    """Check if file should be excluded."""
    for pattern in EXCLUDE_PATTERNS:
        if pattern in filepath:
            return True
    return False


def find_local_md_files(base_path: str, source_name: str, skip_backup_exclusions: bool = False) -> List[Tuple[str, str]]:
    """Find all .md files in a local path."""
    files = []
    base = Path(base_path)
    if not base.exists():
        logger.warning(f"Path does not exist: {base_path}")
        return files

    # Minimal exclusions for expansion-local (we WANT backup content)
    MINIMAL_EXCLUDE = ['node_modules', '.cache', '__pycache__', '.venv', 'site-packages',
                       'nemo-env', '.git', '.npm', '.cargo', '.Trash', 'heartbeat']

    for filepath in base.rglob("*.md"):
        str_path = str(filepath)
        if skip_backup_exclusions:
            # Only apply minimal exclusions
            if any(p in str_path for p in MINIMAL_EXCLUDE):
                continue
        elif should_exclude(str_path):
            continue
        files.append((str_path, source_name))

    logger.info(f"Found {len(files)} .md files in {base_path}")
    return files


def find_remote_md_files(host: str, user: str, remote_path: str, source_name: str) -> List[Tuple[str, str]]:
    """Find .md files on remote host via SSH."""
    files = []
    exclude_args = " ".join([f"-not -path '*/{p}/*'" for p in EXCLUDE_PATTERNS[:10]])
    cmd = f"ssh {user}@{host} \"find {remote_path} -name '*.md' -type f {exclude_args} 2>/dev/null\""

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
        for line in result.stdout.strip().split('\n'):
            if line:
                files.append((f"{user}@{host}:{line}", source_name))
        logger.info(f"Found {len(files)} .md files on {host}:{remote_path}")
    except Exception as e:
        logger.error(f"Error scanning remote host {host}: {e}")

    return files


def read_local_file(filepath: str) -> Optional[str]:
    """Read content from local file."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading {filepath}: {e}")
        return None


def read_remote_file(remote_path: str) -> Optional[str]:
    """Read content from remote file via SSH."""
    try:
        user_host, path = remote_path.split(':')
        cmd = f"ssh {user_host} 'cat \"{path}\"'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception as e:
        logger.error(f"Error reading remote {remote_path}: {e}")
        return None


def create_schema(client: weaviate.WeaviateClient) -> None:
    """Create MarkdownDocument collection if needed."""
    try:
        existing = client.collections.list_all()
        if COLLECTION_NAME in existing:
            logger.info(f"Collection {COLLECTION_NAME} already exists")
            return
    except Exception as e:
        logger.warning(f"Could not check existing collections: {e}")

    logger.info(f"Creating collection: {COLLECTION_NAME}")
    client.collections.create(
        name=COLLECTION_NAME,
        properties=[
            Property(name="filepath", data_type=DataType.TEXT),
            Property(name="filename", data_type=DataType.TEXT),
            Property(name="source_machine", data_type=DataType.TEXT),
            Property(name="content", data_type=DataType.TEXT),
            Property(name="content_preview", data_type=DataType.TEXT),
            Property(name="content_hash", data_type=DataType.TEXT),
            Property(name="file_size", data_type=DataType.INT),
            Property(name="chunk_index", data_type=DataType.INT),
            Property(name="total_chunks", data_type=DataType.INT),
            Property(name="token_count", data_type=DataType.INT),
        ],
        vectorizer_config=Configure.Vectorizer.none(),
    )


def load_existing_uuids(client: weaviate.WeaviateClient) -> set:
    """Load existing content hashes for dedup."""
    hashes = set()
    try:
        collection = client.collections.get(COLLECTION_NAME)
        for obj in collection.iterator(include_vector=False, return_properties=["content_hash"]):
            if obj.properties.get("content_hash"):
                hashes.add(obj.properties["content_hash"])
        logger.info(f"Loaded {len(hashes)} existing content hashes")
    except Exception as e:
        logger.warning(f"Could not load existing hashes: {e}")
    return hashes


def load_and_prepare_items(
    file_list: List[Tuple[str, str]],
    existing_hashes: set
) -> Tuple[List[Dict], int, int]:
    """
    Load all markdown files, chunk large ones, prepare items with token counts.
    Uses Qwen3 tokenizer from fast_transcript_loader.
    """
    print(f"\n[1/4] Loading markdown files with Qwen3 tokenizer...")

    # Force tokenizer load
    get_tokenizer()

    items = []
    skipped = 0
    errors = 0
    chunked_count = 0
    total_chunks = 0

    for idx, (filepath, source_name) in enumerate(file_list):
        if idx % 100 == 0:
            print(f"      Loading {idx}/{len(file_list)}...")

        # Read file
        if filepath.startswith(('mira@', 'spark@')):
            content = read_remote_file(filepath)
            actual_path = filepath.split(':')[1]
        else:
            content = read_local_file(filepath)
            actual_path = filepath

        if content is None or not content.strip():
            errors += 1
            continue

        # Generate content hash for dedup
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        if content_hash in existing_hashes:
            skipped += 1
            continue

        filename = Path(actual_path).name
        file_size = len(content)

        # Chunk if needed (uses Qwen3 tokenizer internally)
        chunks = chunk_large_text(content)

        if len(chunks) > 1:
            chunked_count += 1
            total_chunks += len(chunks)

        for chunk_text, chunk_idx, chunk_total in chunks:
            token_count = count_tokens(chunk_text)

            # Generate unique hash for this chunk
            chunk_hash = hashlib.sha256(
                f"{actual_path}:{chunk_idx}:{chunk_text[:100]}".encode()
            ).hexdigest()

            if chunk_hash in existing_hashes:
                continue

            items.append({
                'text': chunk_text,
                'token_count': token_count,
                'properties': {
                    'filepath': actual_path,
                    'filename': filename,
                    'source_machine': source_name,
                    'content': chunk_text,
                    'content_preview': chunk_text[:500],
                    'content_hash': chunk_hash,
                    'file_size': file_size,
                    'chunk_index': chunk_idx,
                    'total_chunks': chunk_total,
                    'token_count': token_count,
                },
                'uuid': str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_hash))
            })
            existing_hashes.add(chunk_hash)

    total_tokens = sum(item['token_count'] for item in items)
    print(f"      Chunked {chunked_count} large files into {total_chunks} chunks")
    print(f"      Loaded {len(items)} items ({total_tokens:,} tokens)")
    print(f"      Skipped {skipped} duplicates, {errors} errors")

    return items, skipped, errors


async def embed_one_batch(
    session: aiohttp.ClientSession,
    texts: List[str],
    endpoint: str
) -> List[List[float]]:
    """Embed a single batch via HTTP POST - matches fast_transcript_loader."""
    payload = {"model": MODEL_NAME, "input": texts}
    try:
        async with session.post(endpoint, json=payload) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"vLLM error {resp.status} from {endpoint}: {error_text[:200]}")
                return [None] * len(texts)
            result = await resp.json()
            return [item["embedding"] for item in result["data"]]
    except Exception as e:
        logger.error(f"Request error on {endpoint}: {e}")
        return [None] * len(texts)


async def embed_token_batches(
    session: aiohttp.ClientSession,
    batches: List[List[Dict]]
) -> List[List[float]]:
    """
    Embed token-bounded batches using RAW parallel HTTP.
    Fires ALL batches at once across both endpoints.
    """
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


async def embed_and_insert(
    batches: List[List[Dict]],
    weaviate_client: weaviate.WeaviateClient,
) -> Tuple[int, int]:
    """
    Embed batches and insert to Weaviate using parallel HTTP.
    Matches fast_transcript_loader architecture for 10+ emb/sec.
    """
    collection = weaviate_client.collections.get(COLLECTION_NAME)

    # Match fast_transcript_loader: 256 connections
    connector = aiohttp.TCPConnector(limit=256, keepalive_timeout=60.0)
    timeout = aiohttp.ClientTimeout(total=300.0)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        total_loaded = 0
        total_errors = 0
        start_time = time.perf_counter()

        # Process in parallel groups (8 batches at once)
        for group_start in range(0, len(batches), PARALLEL_GROUP):
            group_end = min(group_start + PARALLEL_GROUP, len(batches))
            group_batches = batches[group_start:group_end]

            # Get embeddings with parallel HTTP (all batches in group at once)
            batch_start = time.perf_counter()
            embeddings = await embed_token_batches(session, group_batches)
            batch_time = time.perf_counter() - batch_start

            # Flatten batch items for pairing with embeddings
            group_items = [item for batch in group_batches for item in batch]

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
                        total_errors += 1
            weaviate_time = time.perf_counter() - weaviate_start

            total_loaded += loaded

            # Progress (matches transcript loader format)
            elapsed = time.perf_counter() - start_time
            rate = total_loaded / elapsed if elapsed > 0 else 0
            pct = (group_end / len(batches)) * 100
            group_tokens = sum(sum(item.get('token_count', 0) for item in b) for b in group_batches)
            print(f"      {pct:5.1f}% | {total_loaded:,} loaded | {rate:.0f} emb/sec | "
                  f"{group_tokens:,} tokens | embed: {batch_time:.1f}s, weaviate: {weaviate_time:.1f}s | errors: {total_errors}")

    return total_loaded, total_errors


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fast markdown loader")
    parser.add_argument("--spark1", action="store_true", help="Load from /home/spark")
    parser.add_argument("--expansion", action="store_true", help="Load from /media/spark/Expansion")
    parser.add_argument("--mira", action="store_true", help="Load from mira via SSH")
    parser.add_argument("--mira-local", action="store_true", help="Load from synced mira files at /tmp/mira_md_files")
    parser.add_argument("--expansion-local", action="store_true", help="Load from synced expansion files at /home/spark/data/expansion_md (includes backups)")
    parser.add_argument("--all", action="store_true", help="Load from all sources")
    parser.add_argument("--dry-run", action="store_true", help="Just count files")
    args = parser.parse_args()

    if not any([args.spark1, args.expansion, args.mira, args.mira_local, args.expansion_local, args.all]):
        args.all = True

    print("=" * 70)
    print("FAST MARKDOWN LOADER (Qwen3 tokenizer, parallel embedding)")
    print("=" * 70)
    print(f"Max tokens per batch: {MAX_TOKENS_PER_BATCH:,}")
    print(f"Max tokens per text: {MAX_TOKENS_PER_TEXT:,}")
    print(f"Chunk overlap: {CHUNK_OVERLAP_TOKENS:,} tokens")
    print(f"Endpoints: {VLLM_ENDPOINTS}")
    print("=" * 70)

    # Collect files
    file_list = []
    if args.spark1 or args.all:
        file_list.extend(find_local_md_files("/home/spark", "spark1"))
    if args.expansion or args.all:
        file_list.extend(find_local_md_files("/media/spark/Expansion", "expansion"))
    if args.mira or args.all:
        file_list.extend(find_remote_md_files("10.0.0.163", "mira", "/home/mira", "mira"))
    if args.mira_local:
        file_list.extend(find_local_md_files("/tmp/mira_md_files", "mira"))
    if args.expansion_local:
        file_list.extend(find_local_md_files("/home/spark/data/expansion_md", "expansion", skip_backup_exclusions=True))

    print(f"\nTotal files to process: {len(file_list)}")

    if args.dry_run:
        print("\nDRY RUN - not loading")
        return

    # Connect to Weaviate
    print("\n[2/4] Connecting to Weaviate...")
    weaviate_client = weaviate.connect_to_custom(
        http_host='10.0.0.80',
        http_port=8080,
        http_secure=False,
        grpc_host='10.0.0.80',
        grpc_port=50051,
        grpc_secure=False,
    )

    try:
        create_schema(weaviate_client)
        existing_hashes = load_existing_uuids(weaviate_client)

        # Load and prepare items
        items, skipped, load_errors = load_and_prepare_items(file_list, existing_hashes)

        if not items:
            print("\nNo new items to load!")
            return

        # Create token-bounded batches
        print(f"\n[3/4] Creating token-bounded batches...")
        batches = batch_items_by_tokens(items, MAX_TOKENS_PER_BATCH)

        batch_sizes = [len(b) for b in batches]
        batch_tokens = [sum(item['token_count'] for item in b) for b in batches]
        print(f"      {len(batches)} batches")
        print(f"      Tokens: avg={sum(batch_tokens)//len(batches):,}, max={max(batch_tokens):,}")
        print(f"      Items: avg={sum(batch_sizes)//len(batches)}, max={max(batch_sizes)}")

        # Embed and insert
        print(f"\n[4/4] Processing embeddings (parallel)...")
        start = time.perf_counter()
        loaded, errors = await embed_and_insert(batches, weaviate_client)
        elapsed = time.perf_counter() - start

        # Results
        print("\n" + "=" * 60)
        print("COMPLETE")
        print("=" * 60)
        print(f"Total processed: {len(items):,}")
        print(f"Total loaded: {loaded:,}")
        print(f"Skipped (duplicates): {skipped:,}")
        print(f"Errors: {errors + load_errors}")
        print(f"Time: {elapsed:.1f}s")
        print(f"THROUGHPUT: {loaded/elapsed:.0f} emb/sec")
        print("=" * 60)

        # Verify
        collection = weaviate_client.collections.get(COLLECTION_NAME)
        count = collection.aggregate.over_all(total_count=True)
        print(f"\nWeaviate '{COLLECTION_NAME}' now has {count.total_count:,} objects")

    finally:
        weaviate_client.close()


if __name__ == "__main__":
    asyncio.run(main())
