#!/usr/bin/env python3
"""
Test PhiCompressor on actual Weaviate TranscriptEvent data.
Objective comparison: Phi vs Truncation vs Random vs TF-IDF.
"""

import sys
import numpy as np
import weaviate
from sklearn.feature_extraction.text import TfidfVectorizer
import time

# Import PhiCompressor
sys.path.insert(0, '/Users/REDACTED/taey-hands')
from rosetta_stone.core.compression import PhiCompressor, CompressionResult
from rosetta_stone.core.primitives import PHI, PHI_INVERSE

def fetch_weaviate_data(limit=100):
    """Fetch actual TranscriptEvent data from Weaviate."""
    print(f"Connecting to Weaviate at 10.x.x.80:8080...")
    client = weaviate.connect_to_custom(
        http_host="10.x.x.80",
        http_port=8080,
        http_secure=False,
        grpc_host="10.x.x.80",
        grpc_port=50051,
        grpc_secure=False
    )

    try:
        # Query TranscriptEvents with embeddings
        collection = client.collections.get("TranscriptEvent")
        result = collection.query.fetch_objects(
            limit=limit,
            include_vector=True
        )

        texts = [obj.properties.get('text', '') for obj in result.objects]
        embeddings = np.array([obj.vector['default'] for obj in result.objects])

        print(f"✓ Fetched {len(texts)} events with {embeddings.shape[1]}-dim embeddings")
        return texts, embeddings
    finally:
        client.close()

def dummy_embedder(texts):
    """Dummy embedder - we already have embeddings from Weaviate."""
    # This won't actually be called since we're testing with pre-computed embeddings
    return np.random.randn(len(texts), 4096)

def truncation_compress(texts, ratio=0.3):
    """Baseline: Just take first N% of texts."""
    n_keep = max(1, int(len(texts) * ratio))
    return texts[:n_keep], list(range(n_keep))

def random_compress(texts, ratio=0.3):
    """Baseline: Random selection."""
    n_keep = max(1, int(len(texts) * ratio))
    indices = np.random.choice(len(texts), n_keep, replace=False)
    indices = sorted(indices)
    return [texts[i] for i in indices], indices

def tfidf_compress(texts, ratio=0.3):
    """Baseline: TF-IDF importance scoring."""
    n_keep = max(1, int(len(texts) * ratio))

    # Compute TF-IDF matrix
    vectorizer = TfidfVectorizer(max_features=1000)
    tfidf_matrix = vectorizer.fit_transform(texts)

    # Score each text by sum of its TF-IDF values
    scores = np.array(tfidf_matrix.sum(axis=1)).flatten()

    # Select top-scoring texts
    indices = np.argsort(scores)[-n_keep:]
    indices = sorted(indices)

    return [texts[i] for i in indices], indices

def phi_compress(texts, embeddings, ratio=0.3):
    """φ-harmonic compression using spectral graph theory."""
    start = time.time()

    # PhiCompressor expects an embedder function, but we'll hack it to use our pre-computed embeddings
    compressor = PhiCompressor(dummy_embedder)

    # Manually set embeddings and compute similarity graph
    compressor.embeddings_cache = embeddings
    n = len(embeddings)

    # Compute cosine similarity matrix
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / (norms + 1e-8)
    similarity = normalized @ normalized.T

    # Convert to adjacency matrix (threshold negative similarities)
    adjacency = np.maximum(similarity, 0)

    # Compute Laplacian eigendecomposition
    D = np.diag(np.sum(adjacency, axis=1))
    L = D - adjacency
    eigenvalues, eigenvectors = np.linalg.eigh(L)

    # φ-weighting: weight eigenvectors by φ^(-k/2)
    weights = np.array([PHI ** (-k/2) for k in range(n)])
    harmonic_basis = eigenvectors * weights

    # Project each chunk onto harmonic basis
    chunk_harmonics = harmonic_basis.T  # Each row is harmonic component

    # Score chunks by weighted harmonic content (low frequencies = global structure)
    chunk_scores = np.sum(np.abs(chunk_harmonics), axis=0)

    # Select top chunks
    n_keep = max(1, int(n * ratio))
    indices = np.argsort(chunk_scores)[-n_keep:]
    indices = sorted(indices)

    elapsed = time.time() - start

    return [texts[i] for i in indices], indices, chunk_scores, elapsed

def evaluate_compression(original_texts, selected_texts, selected_indices, embeddings, method_name):
    """Evaluate compression quality."""
    n_original = len(original_texts)
    n_selected = len(selected_texts)
    ratio = n_selected / n_original

    # Semantic coverage: How much of the embedding space is covered?
    original_centroid = embeddings.mean(axis=0)
    selected_embeddings = embeddings[selected_indices]
    selected_centroid = selected_embeddings.mean(axis=0)

    # Cosine similarity between centroids
    centroid_sim = np.dot(original_centroid, selected_centroid) / (
        np.linalg.norm(original_centroid) * np.linalg.norm(selected_centroid) + 1e-8
    )

    # Variance preservation: How much variance is retained?
    original_variance = np.var(embeddings, axis=0).sum()
    selected_variance = np.var(selected_embeddings, axis=0).sum()
    variance_ratio = selected_variance / (original_variance + 1e-8)

    # Diversity: Average pairwise distance
    def avg_pairwise_distance(vecs):
        n = len(vecs)
        if n < 2:
            return 0
        dists = []
        for i in range(n):
            for j in range(i+1, n):
                dists.append(np.linalg.norm(vecs[i] - vecs[j]))
        return np.mean(dists)

    original_diversity = avg_pairwise_distance(embeddings)
    selected_diversity = avg_pairwise_distance(selected_embeddings)
    diversity_ratio = selected_diversity / (original_diversity + 1e-8)

    print(f"\n{method_name}:")
    print(f"  Compression: {n_original} → {n_selected} ({ratio:.1%})")
    print(f"  Centroid similarity: {centroid_sim:.4f}")
    print(f"  Variance preservation: {variance_ratio:.4f}")
    print(f"  Diversity ratio: {diversity_ratio:.4f}")

    return {
        'method': method_name,
        'n_selected': n_selected,
        'ratio': ratio,
        'centroid_sim': centroid_sim,
        'variance_ratio': variance_ratio,
        'diversity_ratio': diversity_ratio
    }

def main():
    print("=" * 80)
    print("OBJECTIVE TEST: PhiCompressor vs Baselines on Weaviate Data")
    print("=" * 80)

    # Fetch data
    texts, embeddings = fetch_weaviate_data(limit=100)

    print(f"\nOriginal corpus: {len(texts)} texts, {embeddings.shape[1]} dims")
    print(f"Sample text: {texts[0][:100]}...")

    target_ratio = 0.3
    print(f"\nTarget compression ratio: {target_ratio:.1%}")

    results = []

    # Test 1: Truncation (baseline)
    print("\n" + "-" * 80)
    print("Testing TRUNCATION baseline...")
    selected, indices = truncation_compress(texts, target_ratio)
    result = evaluate_compression(texts, selected, indices, embeddings, "Truncation")
    results.append(result)

    # Test 2: Random (baseline)
    print("\n" + "-" * 80)
    print("Testing RANDOM baseline...")
    selected, indices = random_compress(texts, target_ratio)
    result = evaluate_compression(texts, selected, indices, embeddings, "Random")
    results.append(result)

    # Test 3: TF-IDF (baseline)
    print("\n" + "-" * 80)
    print("Testing TF-IDF baseline...")
    try:
        selected, indices = tfidf_compress(texts, target_ratio)
        result = evaluate_compression(texts, selected, indices, embeddings, "TF-IDF")
        results.append(result)
    except ValueError as e:
        print(f"⚠ TF-IDF skipped: {e}")
        print("(Text data may be empty or contain only stop words)")

    # Test 4: φ-Harmonic (our method)
    print("\n" + "-" * 80)
    print("Testing φ-HARMONIC compression...")
    selected, indices, scores, elapsed = phi_compress(texts, embeddings, target_ratio)
    result = evaluate_compression(texts, selected, indices, embeddings, "φ-Harmonic")
    result['time'] = elapsed
    results.append(result)
    print(f"  Processing time: {elapsed:.2f}s")

    # Summary comparison
    print("\n" + "=" * 80)
    print("SUMMARY COMPARISON")
    print("=" * 80)
    print(f"{'Method':<15} {'Centroid':<12} {'Variance':<12} {'Diversity':<12}")
    print("-" * 80)
    for r in results:
        print(f"{r['method']:<15} {r['centroid_sim']:<12.4f} {r['variance_ratio']:<12.4f} {r['diversity_ratio']:<12.4f}")

    # Determine winner
    print("\n" + "=" * 80)
    print("OBJECTIVE ANALYSIS")
    print("=" * 80)

    # Best centroid similarity (semantic coherence)
    best_centroid = max(results, key=lambda x: x['centroid_sim'])
    print(f"Best centroid similarity: {best_centroid['method']} ({best_centroid['centroid_sim']:.4f})")

    # Best variance preservation (information retention)
    best_variance = max(results, key=lambda x: x['variance_ratio'])
    print(f"Best variance preservation: {best_variance['method']} ({best_variance['variance_ratio']:.4f})")

    # Best diversity (coverage)
    best_diversity = max(results, key=lambda x: x['diversity_ratio'])
    print(f"Best diversity: {best_diversity['method']} ({best_diversity['diversity_ratio']:.4f})")

    # Composite score (equal weighting)
    for r in results:
        r['composite'] = (r['centroid_sim'] + r['variance_ratio'] + r['diversity_ratio']) / 3

    best_overall = max(results, key=lambda x: x['composite'])
    print(f"\nBest overall (composite): {best_overall['method']} ({best_overall['composite']:.4f})")

    # φ-Harmonic specific insights
    phi_result = [r for r in results if r['method'] == 'φ-Harmonic'][0]
    print(f"\nφ-Harmonic performance vs best baseline:")
    baseline_best_composite = max([r['composite'] for r in results if r['method'] != 'φ-Harmonic'])
    improvement = ((phi_result['composite'] - baseline_best_composite) / baseline_best_composite) * 100
    print(f"  Composite score: {phi_result['composite']:.4f} vs {baseline_best_composite:.4f}")
    print(f"  Improvement: {improvement:+.2f}%")

    if improvement > 0:
        print("\n✓ φ-Harmonic compression OUTPERFORMS baselines")
    elif improvement > -5:
        print("\n≈ φ-Harmonic compression COMPETITIVE with baselines")
    else:
        print("\n✗ φ-Harmonic compression UNDERPERFORMS baselines")

if __name__ == "__main__":
    main()
