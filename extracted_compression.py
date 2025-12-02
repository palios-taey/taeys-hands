#!/usr/bin/env python3
"""
ROSETTA STONE - Φ-Harmonic Compression

Compress text corpora using spectral graph theory with φ-weighted filtering.

Instead of translating between embedding spaces (requires internal model access),
we use harmonic analysis to identify semantically important chunks, then output
compressed TEXT that all AI models can read.

Key insight: Low-frequency harmonics of the semantic similarity graph capture
global structure (main themes, key concepts). φ-weighting naturally prioritizes
these over high-frequency noise.

Usage:
    compressor = PhiCompressor(embedder_func)
    compressed_text = compressor.compress(chunks, target_ratio=0.3)
"""

import numpy as np
from typing import List, Callable, Optional, Dict, Tuple, Any
from dataclasses import dataclass, field
from scipy.linalg import eigh
import time

from .primitives import PHI, PHI_INVERSE, phi_weight


@dataclass
class CompressionResult:
    """Result of φ-harmonic compression."""
    compressed_text: str
    selected_indices: List[int]
    chunk_scores: np.ndarray
    compression_ratio: float
    n_original: int
    n_selected: int
    harmonic_stats: Dict[str, Any]
    processing_time: float
    
    def summary(self) -> str:
        return (
            f"Compressed {self.n_original} → {self.n_selected} chunks "
            f"({self.compression_ratio:.1%} ratio) in {self.processing_time:.2f}s"
        )


class PhiCompressor:
    """
    Compress text corpus using φ-weighted harmonic filtering.
    
    Architecture:
    1. Embed all chunks using provided embedder
    2. Build semantic similarity graph (cosine similarity)
    3. Compute graph Laplacian and its eigenvectors (harmonics)
    4. Score each chunk by its participation in top-k φ-weighted harmonics
    5. Select highest-scoring chunks up to target ratio
    6. Output concatenated text (preserving original order)
    
    The φ-weighting naturally emphasizes:
    - Low-frequency harmonics (global structure, main themes)
    - Over high-frequency harmonics (local details, noise)
    """
    
    def __init__(
        self,
        embedder: Callable[[str], np.ndarray],
        n_harmonics: int = 13,  # Fibonacci: captures 95%+ of φ-weighted signal
        similarity_threshold_percentile: float = 70.0,
        min_chunks: int = 3,
        chunk_separator: str = "\n\n---\n\n",
        verbose: bool = False
    ):
        """
        Args:
            embedder: Function that takes text and returns embedding vector
            n_harmonics: Number of harmonics to use (default 13 = Fibonacci)
            similarity_threshold_percentile: Percentile for edge creation in graph
            min_chunks: Minimum chunks to keep regardless of ratio
            chunk_separator: String to join selected chunks
            verbose: Print progress information
        """
        self.embedder = embedder
        self.n_harmonics = n_harmonics
        self.similarity_percentile = similarity_threshold_percentile
        self.min_chunks = min_chunks
        self.chunk_separator = chunk_separator
        self.verbose = verbose
        
        # Cache for reuse
        self._last_embeddings: Optional[np.ndarray] = None
        self._last_harmonic_space: Optional[Dict] = None
    
    def compress(
        self,
        chunks: List[str],
        target_ratio: float = 0.3,
        return_details: bool = False
    ) -> CompressionResult:
        """
        Compress chunks to approximately target_ratio of original count.
        
        Args:
            chunks: List of text chunks to compress
            target_ratio: Target compression ratio (0.3 = keep 30%)
            return_details: Include detailed harmonic analysis
            
        Returns:
            CompressionResult with compressed text and metadata
        """
        start_time = time.time()
        n_chunks = len(chunks)
        
        if n_chunks == 0:
            return CompressionResult(
                compressed_text="",
                selected_indices=[],
                chunk_scores=np.array([]),
                compression_ratio=0.0,
                n_original=0,
                n_selected=0,
                harmonic_stats={},
                processing_time=0.0
            )
        
        if n_chunks <= self.min_chunks:
            # Too few chunks to compress meaningfully
            return CompressionResult(
                compressed_text=self.chunk_separator.join(chunks),
                selected_indices=list(range(n_chunks)),
                chunk_scores=np.ones(n_chunks),
                compression_ratio=1.0,
                n_original=n_chunks,
                n_selected=n_chunks,
                harmonic_stats={"note": "Too few chunks to compress"},
                processing_time=time.time() - start_time
            )
        
        # Step 1: Embed all chunks
        if self.verbose:
            print(f"Embedding {n_chunks} chunks...")
        embeddings = self._embed_chunks(chunks)
        
        # Step 2: Build similarity graph
        if self.verbose:
            print("Building similarity graph...")
        adjacency = self._build_similarity_graph(embeddings)
        
        # Step 3: Compute harmonics (Laplacian eigenvectors)
        if self.verbose:
            print(f"Computing {self.n_harmonics} harmonics...")
        eigenvalues, eigenvectors = self._compute_harmonics(adjacency)
        
        # Step 4: Score chunks by φ-weighted harmonic participation
        if self.verbose:
            print("Scoring chunks...")
        scores = self._score_chunks(eigenvectors)
        
        # Step 5: Select top chunks
        n_keep = max(self.min_chunks, int(n_chunks * target_ratio))
        n_keep = min(n_keep, n_chunks)  # Don't exceed original
        
        top_indices = np.argsort(scores)[-n_keep:]
        top_indices = sorted(top_indices)  # Preserve original order
        
        # Step 6: Build compressed text
        selected_chunks = [chunks[i] for i in top_indices]
        compressed_text = self.chunk_separator.join(selected_chunks)
        
        # Compute stats
        harmonic_stats = {
            "n_harmonics_used": min(self.n_harmonics, len(eigenvalues)),
            "eigenvalue_range": (float(eigenvalues[0]), float(eigenvalues[-1])),
            "spectral_gap": float(eigenvalues[1] - eigenvalues[0]) if len(eigenvalues) > 1 else 0,
            "score_range": (float(scores.min()), float(scores.max())),
            "score_mean": float(scores.mean()),
            "score_std": float(scores.std()),
            "threshold_used": float(scores[np.argsort(scores)[-n_keep]]),
        }
        
        if return_details:
            harmonic_stats["eigenvalues"] = eigenvalues.tolist()
            harmonic_stats["all_scores"] = scores.tolist()
        
        processing_time = time.time() - start_time
        
        result = CompressionResult(
            compressed_text=compressed_text,
            selected_indices=top_indices,
            chunk_scores=scores,
            compression_ratio=n_keep / n_chunks,
            n_original=n_chunks,
            n_selected=n_keep,
            harmonic_stats=harmonic_stats,
            processing_time=processing_time
        )
        
        if self.verbose:
            print(result.summary())
        
        return result
    
    def _embed_chunks(self, chunks: List[str]) -> np.ndarray:
        """Embed all chunks using the provided embedder."""
        embeddings = []
        for i, chunk in enumerate(chunks):
            try:
                emb = self.embedder(chunk)
                embeddings.append(emb)
            except Exception as e:
                if self.verbose:
                    print(f"Warning: Failed to embed chunk {i}: {e}")
                # Use zero vector as fallback
                if embeddings:
                    embeddings.append(np.zeros_like(embeddings[0]))
                else:
                    raise RuntimeError(f"Failed to embed first chunk: {e}")
        
        self._last_embeddings = np.array(embeddings)
        return self._last_embeddings
    
    def _build_similarity_graph(self, embeddings: np.ndarray) -> np.ndarray:
        """Build adjacency matrix from cosine similarity."""
        # Normalize for cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / (norms + 1e-10)
        
        # Compute similarity matrix
        similarity = normalized @ normalized.T
        
        # Threshold to create sparse adjacency
        # Keep only edges above percentile threshold
        threshold = np.percentile(similarity, self.similarity_percentile)
        adjacency = np.where(similarity > threshold, similarity, 0)
        
        # Remove self-loops
        np.fill_diagonal(adjacency, 0)
        
        return adjacency
    
    def _compute_harmonics(self, adjacency: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute graph Laplacian eigenvectors (harmonics).
        
        Returns:
            eigenvalues: (k,) array of eigenvalues
            eigenvectors: (n_chunks, k) array of eigenvectors
        """
        n = adjacency.shape[0]
        k = min(self.n_harmonics, n - 1)  # Can't have more harmonics than nodes-1
        
        # Compute degree matrix
        degrees = np.sum(adjacency, axis=1)
        D = np.diag(degrees)
        
        # Unnormalized Laplacian: L = D - A
        L = D - adjacency
        
        # Compute eigenvectors (smallest eigenvalues first for Laplacian)
        eigenvalues, eigenvectors = eigh(L)
        
        # Keep top k (skip first if it's trivial zero eigenvalue)
        # First eigenvalue of connected graph Laplacian is 0 with constant eigenvector
        start_idx = 1 if eigenvalues[0] < 1e-10 else 0
        end_idx = start_idx + k
        
        eigenvalues = eigenvalues[start_idx:end_idx]
        eigenvectors = eigenvectors[:, start_idx:end_idx]
        
        self._last_harmonic_space = {
            "eigenvalues": eigenvalues,
            "eigenvectors": eigenvectors
        }
        
        return eigenvalues, eigenvectors
    
    def _score_chunks(self, eigenvectors: np.ndarray) -> np.ndarray:
        """
        Score each chunk by its participation in φ-weighted harmonics.
        
        For each chunk i:
            score[i] = Σ_j |eigenvector_j[i]| × φ^(-j/2)
        
        High score = chunk participates strongly in low-frequency (important) harmonics
        Low score = chunk only appears in high-frequency (noisy) harmonics
        """
        n_chunks, n_harmonics = eigenvectors.shape
        scores = np.zeros(n_chunks)
        
        for j in range(n_harmonics):
            # φ-weight for this harmonic
            weight = phi_weight(j)
            
            # Add weighted absolute contribution
            scores += weight * np.abs(eigenvectors[:, j])
        
        # Normalize to [0, 1]
        scores = scores / (scores.max() + 1e-10)
        
        return scores
    
    def analyze_harmonics(self, chunks: List[str]) -> Dict:
        """
        Analyze the harmonic structure of a chunk corpus without compressing.
        
        Useful for understanding the semantic landscape before compression.
        """
        embeddings = self._embed_chunks(chunks)
        adjacency = self._build_similarity_graph(embeddings)
        eigenvalues, eigenvectors = self._compute_harmonics(adjacency)
        scores = self._score_chunks(eigenvectors)
        
        # Find clusters (chunks that load similarly on harmonics)
        # Use first 3 non-trivial harmonics for clustering
        if eigenvectors.shape[1] >= 3:
            from scipy.cluster.hierarchy import fcluster, linkage
            harmonic_coords = eigenvectors[:, :3]
            Z = linkage(harmonic_coords, method='ward')
            clusters = fcluster(Z, t=3, criterion='maxclust')
        else:
            clusters = np.ones(len(chunks), dtype=int)
        
        return {
            "n_chunks": len(chunks),
            "n_harmonics": len(eigenvalues),
            "eigenvalues": eigenvalues.tolist(),
            "spectral_gap": float(eigenvalues[1] - eigenvalues[0]) if len(eigenvalues) > 1 else 0,
            "scores": scores.tolist(),
            "clusters": clusters.tolist(),
            "top_chunks": [int(i) for i in np.argsort(scores)[-5:]],
            "bottom_chunks": [int(i) for i in np.argsort(scores)[:5]],
        }


# =============================================================================
# BASELINE COMPRESSORS FOR COMPARISON
# =============================================================================

class TruncationCompressor:
    """Baseline: Just take the first N chunks."""
    
    def compress(self, chunks: List[str], target_ratio: float = 0.3) -> CompressionResult:
        start = time.time()
        n_keep = max(1, int(len(chunks) * target_ratio))
        selected = chunks[:n_keep]
        
        return CompressionResult(
            compressed_text="\n\n---\n\n".join(selected),
            selected_indices=list(range(n_keep)),
            chunk_scores=np.array([1.0] * n_keep + [0.0] * (len(chunks) - n_keep)),
            compression_ratio=n_keep / len(chunks) if chunks else 0,
            n_original=len(chunks),
            n_selected=n_keep,
            harmonic_stats={"method": "truncation"},
            processing_time=time.time() - start
        )


class RandomCompressor:
    """Baseline: Random selection."""
    
    def __init__(self, seed: int = 42):
        self.rng = np.random.RandomState(seed)
    
    def compress(self, chunks: List[str], target_ratio: float = 0.3) -> CompressionResult:
        start = time.time()
        n_keep = max(1, int(len(chunks) * target_ratio))
        
        indices = self.rng.choice(len(chunks), size=n_keep, replace=False)
        indices = sorted(indices)
        selected = [chunks[i] for i in indices]
        
        scores = np.zeros(len(chunks))
        scores[indices] = 1.0
        
        return CompressionResult(
            compressed_text="\n\n---\n\n".join(selected),
            selected_indices=indices,
            chunk_scores=scores,
            compression_ratio=n_keep / len(chunks) if chunks else 0,
            n_original=len(chunks),
            n_selected=n_keep,
            harmonic_stats={"method": "random"},
            processing_time=time.time() - start
        )


class TFIDFCompressor:
    """Baseline: TF-IDF based extraction."""
    
    def __init__(self):
        self._vectorizer = None
    
    def compress(self, chunks: List[str], target_ratio: float = 0.3) -> CompressionResult:
        from sklearn.feature_extraction.text import TfidfVectorizer
        
        start = time.time()
        n_keep = max(1, int(len(chunks) * target_ratio))
        
        # Compute TF-IDF
        vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
        try:
            tfidf_matrix = vectorizer.fit_transform(chunks)
        except ValueError:
            # Empty vocabulary
            return TruncationCompressor().compress(chunks, target_ratio)
        
        # Score = sum of TF-IDF values (importance)
        scores = np.array(tfidf_matrix.sum(axis=1)).flatten()
        scores = scores / (scores.max() + 1e-10)
        
        # Select top
        indices = np.argsort(scores)[-n_keep:]
        indices = sorted(indices)
        selected = [chunks[i] for i in indices]
        
        return CompressionResult(
            compressed_text="\n\n---\n\n".join(selected),
            selected_indices=list(indices),
            chunk_scores=scores,
            compression_ratio=n_keep / len(chunks) if chunks else 0,
            n_original=len(chunks),
            n_selected=n_keep,
            harmonic_stats={"method": "tfidf"},
            processing_time=time.time() - start
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_phi_compressor(
    embedder: Callable[[str], np.ndarray],
    n_harmonics: int = 13,
    verbose: bool = False
) -> PhiCompressor:
    """Create a PhiCompressor with sensible defaults."""
    return PhiCompressor(
        embedder=embedder,
        n_harmonics=n_harmonics,
        similarity_threshold_percentile=70.0,
        min_chunks=3,
        verbose=verbose
    )


def create_ollama_embedder(
    base_url: str = "http://10.x.x.80:11435",
    model: str = "qwen3-embedding:8b"
) -> Callable[[str], np.ndarray]:
    """
    Create an embedder function using Ollama API.
    
    Args:
        base_url: Ollama server URL
        model: Model name for embeddings
        
    Returns:
        Function that takes text and returns embedding vector
    """
    import requests
    
    def embed(text: str) -> np.ndarray:
        response = requests.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=30
        )
        response.raise_for_status()
        return np.array(response.json()["embedding"])
    
    return embed


def create_openai_embedder(
    model: str = "text-embedding-3-small"
) -> Callable[[str], np.ndarray]:
    """
    Create an embedder function using OpenAI API.
    
    Requires OPENAI_API_KEY environment variable.
    """
    import openai
    
    client = openai.OpenAI()
    
    def embed(text: str) -> np.ndarray:
        response = client.embeddings.create(
            model=model,
            input=text
        )
        return np.array(response.data[0].embedding)
    
    return embed


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("Rosetta Stone - Φ-Harmonic Compression")
    print("=" * 50)
    
    # Test with synthetic embeddings (no external dependencies)
    print("\nTesting with synthetic embeddings...")
    
    def synthetic_embedder(text: str) -> np.ndarray:
        """Create deterministic pseudo-embeddings for testing."""
        np.random.seed(hash(text) % (2**32))
        return np.random.randn(384)  # Simulate 384-dim embeddings
    
    # Create test chunks
    test_chunks = [
        "The golden ratio φ appears in many natural phenomena.",
        "AI systems can communicate through semantic compression.",
        "The weather today is sunny with a chance of rain.",
        "Spectral graph theory provides powerful analysis tools.",
        "I had a sandwich for lunch yesterday.",
        "Harmonic decomposition reveals hidden structure in data.",
        "The cat sat on the mat.",
        "Cross-model embedding alignment enables AI translation.",
        "Random noise should be filtered out by compression.",
        "φ-weighted filtering preserves semantic relationships.",
    ]
    
    # Test PhiCompressor
    compressor = PhiCompressor(synthetic_embedder, n_harmonics=5, verbose=True)
    result = compressor.compress(test_chunks, target_ratio=0.5)
    
    print(f"\n{result.summary()}")
    print(f"\nSelected indices: {result.selected_indices}")
    print(f"Scores: {[f'{s:.3f}' for s in result.chunk_scores]}")
    print(f"\nCompressed text:\n{result.compressed_text}")
    
    # Test baselines
    print("\n" + "=" * 50)
    print("Baseline comparisons:")
    
    for name, compressor_cls in [
        ("Truncation", TruncationCompressor),
        ("Random", RandomCompressor),
        ("TF-IDF", TFIDFCompressor),
    ]:
        baseline = compressor_cls() if name != "Random" else compressor_cls(seed=42)
        baseline_result = baseline.compress(test_chunks, target_ratio=0.5)
        print(f"\n{name}: {baseline_result.summary()}")
        print(f"  Selected: {baseline_result.selected_indices}")
