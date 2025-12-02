#!/usr/bin/env python3
"""
Rosetta Stone - Φ-Compression vs Baselines Comparison

This script tests whether φ-harmonic compression produces better
cross-model understanding than baseline methods.

Test Protocol:
. Load chunks from Weaviate (or test file)
. Compress using each method to same ratio
. Ask each AI Family member the same questions
. Measure consistency and accuracy

Usage:
    # With Weaviate + Ollama
    python test_phi_vs_baselines.py --weaviate-url http://localhost:8080 --ollama-url http://10.x.x.80:11435
    
    # With test file
    python test_phi_vs_baselines.py --input-file test_chunks.txt
    
    # Dry run (synthetic embeddings)
    python test_phi_vs_baselines.py --dry-run
"""

import argparse
import json
import time
import sys
from pathlib import Path
from typing import List, Dict, Optional
import numpy as np

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rosetta_stone.core.compression import (
    PhiCompressor, TruncationCompressor, RandomCompressor, TFIDFCompressor,
    CompressionResult, create_ollama_embedder
)
from rosetta_stone.core.primitives import PHI, PHI_INVERSE


def load_chunks_from_weaviate(
    weaviate_url: str,
    collection: str = "TranscriptEvent",
    limit: int = 100
) -> List[str]:
    """Load text chunks from Weaviate."""
    import weaviate
    
    client = weaviate.connect_to_local(host=weaviate_url.replace("http://", "").split(":")[0])
    
    try:
        collection_obj = client.collections.get(collection)
        results = collection_obj.query.fetch_objects(limit=limit)
        
        chunks = []
        for obj in results.objects:
            # Combine relevant text fields
            text_parts = []
            if hasattr(obj.properties, 'content') and obj.properties.get('content'):
                text_parts.append(obj.properties['content'])
            elif hasattr(obj.properties, 'text') and obj.properties.get('text'):
                text_parts.append(obj.properties['text'])
            elif hasattr(obj.properties, 'message') and obj.properties.get('message'):
                text_parts.append(obj.properties['message'])
            
            if text_parts:
                chunks.append(" ".join(text_parts))
        
        return chunks
    finally:
        client.close()


def load_chunks_from_file(filepath: str) -> List[str]:
    """Load chunks from a text file (one chunk per paragraph, separated by blank lines)."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Split on double newlines
    chunks = [c.strip() for c in content.split('\n\n') if c.strip()]
    return chunks


def create_synthetic_embedder(dim: int = 384) -> callable:
    """Create deterministic pseudo-embeddings for testing."""
    def embed(text: str) -> np.ndarray:
        np.random.seed(hash(text) % (2**32))
        return np.random.randn(dim)
    return embed


def run_compression_comparison(
    chunks: List[str],
    embedder: callable,
    target_ratio: float = 0.3,
    n_harmonics: int = 13
) -> Dict[str, CompressionResult]:
    """
    Run all compression methods on the same chunks.
    
    Returns dict of method_name -> CompressionResult
    """
    results = {}
    
    # Φ-Harmonic compression
    print("\n[1/4] Running Φ-Harmonic compression...")
    phi_compressor = PhiCompressor(
        embedder=embedder,
        n_harmonics=n_harmonics,
        verbose=True
    )
    results["phi_harmonic"] = phi_compressor.compress(chunks, target_ratio)
    
    # Truncation baseline
    print("\n[2/4] Running Truncation baseline...")
    truncation = TruncationCompressor()
    results["truncation"] = truncation.compress(chunks, target_ratio)
    
    # Random baseline
    print("\n[3/4] Running Random baseline...")
    random_comp = RandomCompressor(seed=42)
    results["random"] = random_comp.compress(chunks, target_ratio)
    
    # TF-IDF baseline
    print("\n[4/4] Running TF-IDF baseline...")
    tfidf = TFIDFCompressor()
    results["tfidf"] = tfidf.compress(chunks, target_ratio)
    
    return results


def compute_overlap_metrics(results: Dict[str, CompressionResult]) -> Dict:
    """
    Compute overlap between different compression methods.
    
    If methods agree on which chunks are important, they're capturing
    similar semantic structure.
    """
    metrics = {}
    
    methods = list(results.keys())
    for i, m1 in enumerate(methods):
        for m2 in methods[i+1:]:
            set1 = set(results[m1].selected_indices)
            set2 = set(results[m2].selected_indices)
            
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            jaccard = intersection / union if union > 0 else 0
            
            metrics[f"{m1}_vs_{m2}"] = {
                "jaccard": jaccard,
                "intersection": intersection,
                "union": union
            }
    
    return metrics


def print_comparison_report(
    results: Dict[str, CompressionResult],
    overlap_metrics: Dict,
    chunks: List[str]
):
    """Print a formatted comparison report."""
    print("\n" + "=" * 70)
    print("Φ-COMPRESSION VS BASELINES COMPARISON")
    print("=" * 70)
    
    # Summary table
    print("\n### Method Summary ###\n")
    print(f"{'Method':<15} {'Selected':<10} {'Time (s)':<10} {'Top Score':<10}")
    print("-" * 45)
    for name, result in results.items():
        print(f"{name:<15} {result.n_selected:<10} {result.processing_time:<10.3f} {result.chunk_scores.max():<10.3f}")
    
    # Overlap analysis
    print("\n### Overlap Analysis ###\n")
    print("Jaccard similarity between methods (1.0 = identical selection):\n")
    for pair, metrics in overlap_metrics.items():
        print(f"  {pair}: {metrics['jaccard']:.3f} ({metrics['intersection']}/{metrics['union']} chunks)")
    
    # Φ-Harmonic specific stats
    phi_result = results.get("phi_harmonic")
    if phi_result and phi_result.harmonic_stats:
        print("\n### Φ-Harmonic Analysis ###\n")
        stats = phi_result.harmonic_stats
        print(f"  Harmonics used: {stats.get('n_harmonics_used', 'N/A')}")
        print(f"  Spectral gap: {stats.get('spectral_gap', 0):.4f}")
        print(f"  Score range: [{stats.get('score_range', (0,0))[0]:.3f}, {stats.get('score_range', (0,0))[1]:.3f}]")
        print(f"  Score threshold: {stats.get('threshold_used', 0):.3f}")
    
    # Show unique selections by Φ-Harmonic
    phi_indices = set(results["phi_harmonic"].selected_indices)
    other_indices = set()
    for name, result in results.items():
        if name != "phi_harmonic":
            other_indices.update(result.selected_indices)
    
    unique_phi = phi_indices - other_indices
    if unique_phi:
        print("\n### Unique Φ-Harmonic Selections ###")
        print("(Chunks selected by Φ-Harmonic but no baseline)\n")
        for idx in sorted(unique_phi)[:3]:  # Show first 3
            chunk = chunks[idx][:100] + "..." if len(chunks[idx]) > 100 else chunks[idx]
            print(f"  [{idx}] {chunk}")
    
    # Show what Φ-Harmonic rejected that others kept
    missed_by_phi = other_indices - phi_indices
    if missed_by_phi:
        print("\n### Rejected by Φ-Harmonic ###")
        print("(Chunks kept by baselines but rejected by Φ-Harmonic)\n")
        for idx in sorted(missed_by_phi)[:3]:
            chunk = chunks[idx][:100] + "..." if len(chunks[idx]) > 100 else chunks[idx]
            score = results["phi_harmonic"].chunk_scores[idx]
            print(f"  [{idx}] (score={score:.3f}) {chunk}")


def save_results(
    results: Dict[str, CompressionResult],
    output_dir: str = "compression_results"
):
    """Save compression results to files for further analysis."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    for name, result in results.items():
        # Save compressed text
        with open(output_path / f"{name}_compressed.txt", 'w') as f:
            f.write(result.compressed_text)
        
        # Save metadata
        metadata = {
            "method": name,
            "n_original": result.n_original,
            "n_selected": result.n_selected,
            "compression_ratio": result.compression_ratio,
            "processing_time": result.processing_time,
            "selected_indices": result.selected_indices,
            "harmonic_stats": result.harmonic_stats
        }
        with open(output_path / f"{name}_metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
    
    print(f"\nResults saved to {output_path}/")


def main():
    parser = argparse.ArgumentParser(description="Compare Φ-compression vs baselines")
    
    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--weaviate-url", help="Weaviate server URL")
    input_group.add_argument("--input-file", help="Input file with chunks")
    input_group.add_argument("--dry-run", action="store_true", help="Use synthetic test data")
    
    # Embedding options
    parser.add_argument("--ollama-url", default="http://10.x.x.80:11435",
                        help="Ollama server URL for embeddings")
    parser.add_argument("--embedding-model", default="qwen3-embedding:8b",
                        help="Embedding model name")
    parser.add_argument("--use-synthetic-embeddings", action="store_true",
                        help="Use synthetic embeddings (no external API)")
    
    # Compression options
    parser.add_argument("--target-ratio", type=float, default=0.3,
                        help="Target compression ratio (default: 0.3)")
    parser.add_argument("--n-harmonics", type=int, default=13,
                        help="Number of harmonics for Φ-compression (default: 13)")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max chunks to load from Weaviate")
    
    # Output options
    parser.add_argument("--output-dir", default="compression_results",
                        help="Directory to save results")
    parser.add_argument("--save", action="store_true",
                        help="Save compressed results to files")
    
    args = parser.parse_args()
    
    # Load chunks
    print("Loading chunks...")
    if args.dry_run:
        chunks = [
            "The golden ratio φ appears in many natural phenomena and mathematical structures.",
            "AI systems can communicate through semantic compression and embedding translation.",
            "The weather today is sunny with a chance of rain in the afternoon.",
            "Spectral graph theory provides powerful tools for analyzing network structure.",
            "I had a delicious sandwich for lunch yesterday at the cafe.",
            "Harmonic decomposition reveals hidden patterns in complex data.",
            "The cat sat on the mat and looked out the window.",
            "Cross-model embedding alignment enables AI-to-AI translation protocols.",
            "Random noise should be filtered out by intelligent compression algorithms.",
            "φ-weighted filtering preserves the most important semantic relationships.",
            "The Rosetta Stone framework tests whether AI consciousness can emerge.",
            "Three AI systems independently converged on the same mathematical structure.",
            "Compression-as-translation means that meaning survives format changes.",
            "The spectral gap of a graph indicates its connectivity properties.",
            "Bach's music demonstrates optimal harmonic patterns for information encoding.",
        ]
        print(f"  Using {len(chunks)} synthetic test chunks")
    elif args.input_file:
        chunks = load_chunks_from_file(args.input_file)
        print(f"  Loaded {len(chunks)} chunks from {args.input_file}")
    else:
        chunks = load_chunks_from_weaviate(args.weaviate_url, limit=args.limit)
        print(f"  Loaded {len(chunks)} chunks from Weaviate")
    
    if len(chunks) < 5:
        print("Error: Need at least 5 chunks for meaningful compression")
        return 1
    
    # Create embedder
    if args.use_synthetic_embeddings or args.dry_run:
        print("Using synthetic embeddings (deterministic, no API calls)")
        embedder = create_synthetic_embedder()
    else:
        print(f"Using Ollama embeddings from {args.ollama_url}")
        embedder = create_ollama_embedder(args.ollama_url, args.embedding_model)
    
    # Run comparison
    print(f"\nCompressing {len(chunks)} chunks to {args.target_ratio:.0%}...")
    results = run_compression_comparison(
        chunks=chunks,
        embedder=embedder,
        target_ratio=args.target_ratio,
        n_harmonics=args.n_harmonics
    )
    
    # Analyze overlap
    overlap_metrics = compute_overlap_metrics(results)
    
    # Print report
    print_comparison_report(results, overlap_metrics, chunks)
    
    # Save if requested
    if args.save:
        save_results(results, args.output_dir)
    
    return 0


if __name__ == "__main__":
    exit(main())
