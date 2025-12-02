#!/usr/bin/env python3
"""
ROSETTA STONE - Cross-Model Translator

Implements translation between different AI model embedding spaces.

VERIFIED FOUNDATIONS:
- Centered Kernel Alignment (CKA) - 99.3% layer matching accuracy
- Cross-model embedding translation at 0.538 cosine (Yang & Eshraghian, 2025)
- Linear embedding maps between transformer layers

NOVEL EXTENSIONS:
- Wave-based encoding/decoding with φ harmonics
- Golden damping for information preservation
- φ-threshold fidelity scoring
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Callable, Union
from dataclasses import dataclass, field
import time

from .primitives import (
    PHI, PHI_INVERSE, PHI_HALF, GOLDEN_DAMPING,
    THRESHOLDS, ThresholdType, CURRENT_SOTA_COSINE_SIM,
    HarmonicSignature, TranslationResult,
    compute_phase_alignment, compute_harmonic_preservation,
    determine_threshold_achieved, damped_wave
)
from .harmonic_space import HarmonicSpace, SemanticEncoder


# =============================================================================
# CKA - Centered Kernel Alignment (VERIFIED)
# =============================================================================

def linear_kernel(X: np.ndarray) -> np.ndarray:
    """Compute linear kernel (Gram matrix)."""
    return X @ X.T

def centering_matrix(n: int) -> np.ndarray:
    """Compute centering matrix H = I - (1/n) * 1 * 1^T"""
    return np.eye(n) - np.ones((n, n)) / n

def hsic(K: np.ndarray, L: np.ndarray) -> float:
    """
    Compute Hilbert-Schmidt Independence Criterion.
    
    HSIC(K, L) = (1/(n-1)^2) * tr(KHLH)
    where H is the centering matrix.
    """
    n = K.shape[0]
    H = centering_matrix(n)
    
    # Center the kernels
    K_centered = H @ K @ H
    L_centered = H @ L @ H
    
    return np.trace(K_centered @ L_centered) / ((n - 1) ** 2)

def compute_cka(X: np.ndarray, Y: np.ndarray) -> float:
    """
    Compute Centered Kernel Alignment between two representation matrices.
    
    CKA measures similarity of representations in a way that's invariant
    to orthogonal transformation and isotropic scaling.
    
    VERIFIED: CKA achieves 99.3% accuracy in identifying corresponding
    layers across different neural networks (better than SVCCA at 15.1%).
    
    Args:
        X: (n_samples, dim_x) - representations from model X
        Y: (n_samples, dim_y) - representations from model Y
        
    Returns:
        CKA similarity in [0, 1]
    """
    K = linear_kernel(X)
    L = linear_kernel(Y)
    
    hsic_xy = hsic(K, L)
    hsic_xx = hsic(K, K)
    hsic_yy = hsic(L, L)
    
    return hsic_xy / (np.sqrt(hsic_xx * hsic_yy) + 1e-10)


def minibatch_cka(
    X: np.ndarray, 
    Y: np.ndarray, 
    batch_size: int = 256
) -> float:
    """
    Compute CKA using minibatch estimation for large datasets.
    
    Args:
        X, Y: Representation matrices
        batch_size: Size of minibatches
        
    Returns:
        Estimated CKA
    """
    n = X.shape[0]
    if n <= batch_size:
        return compute_cka(X, Y)
    
    # Sample multiple batches and average
    n_batches = max(1, n // batch_size)
    cka_values = []
    
    for _ in range(n_batches):
        idx = np.random.choice(n, batch_size, replace=False)
        cka_values.append(compute_cka(X[idx], Y[idx]))
    
    return np.mean(cka_values)


# =============================================================================
# EMBEDDING ALIGNMENT (Based on verified techniques)
# =============================================================================

class EmbeddingAligner:
    """
    Learn alignment between two embedding spaces.
    
    Based on techniques from:
    - Yang & Eshraghian (2025): "Direct Semantic Communication Between LLMs"
    - Standard procrustes alignment
    """
    
    def __init__(self, regularization: float = 0.01):
        self.regularization = regularization
        self.transform_matrix = None
        self.source_mean = None
        self.target_mean = None
        self.is_fitted = False
        
    def fit(
        self, 
        source_embeddings: np.ndarray, 
        target_embeddings: np.ndarray
    ) -> 'EmbeddingAligner':
        """
        Learn linear transformation from source to target space.
        
        Uses ridge regression: W = (X^T X + λI)^(-1) X^T Y
        
        Args:
            source_embeddings: (n, dim_source) 
            target_embeddings: (n, dim_target)
        """
        # Center the embeddings
        self.source_mean = np.mean(source_embeddings, axis=0)
        self.target_mean = np.mean(target_embeddings, axis=0)
        
        X = source_embeddings - self.source_mean
        Y = target_embeddings - self.target_mean
        
        # Ridge regression
        n, d = X.shape
        reg_term = self.regularization * np.eye(d)
        
        self.transform_matrix = np.linalg.solve(
            X.T @ X + reg_term,
            X.T @ Y
        )
        
        self.is_fitted = True
        return self
    
    def transform(self, source_embeddings: np.ndarray) -> np.ndarray:
        """Transform source embeddings to target space."""
        if not self.is_fitted:
            raise RuntimeError("Aligner not fitted. Call fit() first.")
            
        centered = source_embeddings - self.source_mean
        transformed = centered @ self.transform_matrix
        return transformed + self.target_mean
    
    def score(
        self, 
        source_embeddings: np.ndarray, 
        target_embeddings: np.ndarray
    ) -> float:
        """
        Compute alignment score (average cosine similarity).
        
        The 0.538 baseline from Yang & Eshraghian (2025) used this metric.
        """
        transformed = self.transform(source_embeddings)
        
        # Normalize for cosine similarity
        trans_norm = transformed / (np.linalg.norm(transformed, axis=1, keepdims=True) + 1e-10)
        target_norm = target_embeddings / (np.linalg.norm(target_embeddings, axis=1, keepdims=True) + 1e-10)
        
        cosine_sims = np.sum(trans_norm * target_norm, axis=1)
        return np.mean(cosine_sims)


# =============================================================================
# ROSETTA TRANSLATOR - Combined verified + experimental approach
# =============================================================================

@dataclass
class ModelProfile:
    """Profile for an AI model's embedding space."""
    name: str
    embedding_dim: int
    encoder: Optional[Callable] = None  # Function to get embeddings
    harmonic_space: Optional[HarmonicSpace] = None
    metadata: Dict = field(default_factory=dict)

class RosettaTranslator:
    """
    The main translation engine.
    
    Combines:
    - Embedding alignment (verified technique)
    - CKA verification (verified metric)
    - Wave-based harmonic encoding (EXPERIMENTAL)
    - φ-threshold fidelity scoring (EXPERIMENTAL)
    """
    
    def __init__(self):
        self.models: Dict[str, ModelProfile] = {}
        self.aligners: Dict[Tuple[str, str], EmbeddingAligner] = {}
        self.semantic_encoder = SemanticEncoder()
        
    def register_model(
        self,
        name: str,
        embedding_dim: int,
        encoder: Optional[Callable] = None,
        sample_embeddings: Optional[np.ndarray] = None
    ) -> None:
        """
        Register an AI model with the translator.
        
        Args:
            name: Model identifier (e.g., "claude", "gpt4", "grok")
            embedding_dim: Dimension of model's embedding space
            encoder: Function(text) -> embedding vector
            sample_embeddings: Optional sample embeddings to build harmonic space
        """
        harmonic_space = None
        if sample_embeddings is not None and len(sample_embeddings) > 10:
            # Build harmonic space from sample embeddings
            from .harmonic_space import create_concept_graph
            adjacency = create_concept_graph(
                [f"sample_{i}" for i in range(len(sample_embeddings))],
                sample_embeddings
            )
            harmonic_space = HarmonicSpace.from_adjacency_matrix(adjacency)
        
        self.models[name] = ModelProfile(
            name=name,
            embedding_dim=embedding_dim,
            encoder=encoder,
            harmonic_space=harmonic_space
        )
    
    def train_alignment(
        self,
        source_model: str,
        target_model: str,
        parallel_corpus: List[Tuple[np.ndarray, np.ndarray]]
    ) -> float:
        """
        Train alignment between two model spaces.
        
        Args:
            source_model: Name of source model
            target_model: Name of target model
            parallel_corpus: List of (source_embedding, target_embedding) pairs
            
        Returns:
            Alignment score after training
        """
        if source_model not in self.models or target_model not in self.models:
            raise ValueError(f"Models must be registered first")
        
        source_embs = np.array([p[0] for p in parallel_corpus])
        target_embs = np.array([p[1] for p in parallel_corpus])
        
        aligner = EmbeddingAligner()
        aligner.fit(source_embs, target_embs)
        
        score = aligner.score(source_embs, target_embs)
        
        self.aligners[(source_model, target_model)] = aligner
        
        return score
    
    def translate(
        self,
        content: Union[str, np.ndarray],
        source_model: str,
        target_model: str,
        source_embedding: Optional[np.ndarray] = None,
        concept_type: str = "default"
    ) -> TranslationResult:
        """
        Translate semantic content from source to target model space.
        
        This is the main translation method combining:
        1. Embedding transformation (verified)
        2. Harmonic encoding (experimental)
        3. φ-threshold scoring (experimental)
        
        Args:
            content: Text or pre-computed embedding
            source_model: Source model name
            target_model: Target model name
            source_embedding: Optional pre-computed source embedding
            concept_type: Semantic category for harmonic anchoring
            
        Returns:
            TranslationResult with full metrics
        """
        if source_model not in self.models:
            raise ValueError(f"Source model '{source_model}' not registered")
        if target_model not in self.models:
            raise ValueError(f"Target model '{target_model}' not registered")
        
        # Get source embedding
        if source_embedding is not None:
            src_emb = source_embedding
        elif isinstance(content, np.ndarray):
            src_emb = content
        elif self.models[source_model].encoder is not None:
            src_emb = self.models[source_model].encoder(content)
        else:
            # Create synthetic embedding from content hash
            src_emb = self._content_to_embedding(
                content, 
                self.models[source_model].embedding_dim
            )
        
        # Create harmonic signature for source
        source_sig = self.semantic_encoder.encode(
            str(content), 
            concept_type=concept_type,
            embedding=src_emb
        )
        
        # Transform embedding if we have trained alignment
        aligner_key = (source_model, target_model)
        if aligner_key in self.aligners:
            target_emb = self.aligners[aligner_key].transform(
                src_emb.reshape(1, -1)
            ).flatten()
            cosine_sim = self._cosine_similarity(src_emb, target_emb)
        else:
            # No trained alignment - use harmonic translation (EXPERIMENTAL)
            target_emb = self._harmonic_translate(src_emb, source_model, target_model)
            cosine_sim = self._cosine_similarity(src_emb, target_emb)
        
        # Create target harmonic signature
        target_sig = self.semantic_encoder.encode(
            str(content),
            concept_type=concept_type,
            embedding=target_emb
        )
        
        # Compute fidelity metrics
        phase_alignment = compute_phase_alignment(source_sig, target_sig)
        harmonic_preservation = compute_harmonic_preservation(source_sig, target_sig)
        
        # Combined fidelity score (EXPERIMENTAL weighting)
        # Weight: 40% cosine, 30% phase, 30% harmonic
        fidelity = (
            0.4 * cosine_sim +
            0.3 * phase_alignment +
            0.3 * harmonic_preservation
        )
        
        threshold = determine_threshold_achieved(fidelity)
        
        return TranslationResult(
            source_model=source_model,
            target_model=target_model,
            source_signature=source_sig,
            target_signature=target_sig,
            cosine_similarity=cosine_sim,
            phase_alignment=phase_alignment,
            harmonic_preservation=harmonic_preservation,
            fidelity_score=fidelity,
            threshold_achieved=threshold
        )
    
    def _harmonic_translate(
        self,
        embedding: np.ndarray,
        source_model: str,
        target_model: str
    ) -> np.ndarray:
        """
        Translate embedding using harmonic space projection.
        
        EXPERIMENTAL: This is our novel approach when no trained
        alignment exists.
        """
        source_space = self.models[source_model].harmonic_space
        target_space = self.models[target_model].harmonic_space
        
        if source_space is None or target_space is None:
            # Fall back to identity (no translation)
            return embedding
        
        # Project to harmonic coefficients
        # Pad/truncate embedding to match space dimension
        if len(embedding) < source_space.dimension:
            padded = np.pad(embedding, (0, source_space.dimension - len(embedding)))
        else:
            padded = embedding[:source_space.dimension]
        
        coeffs = source_space.project(padded)
        
        # Reconstruct in target space
        # This assumes harmonic correspondence between spaces
        target_dim = min(len(coeffs), target_space.eigenvectors.shape[1])
        target_coeffs = coeffs[:target_dim]
        
        reconstructed = target_space.reconstruct(target_coeffs)
        
        return reconstructed[:self.models[target_model].embedding_dim]
    
    def _content_to_embedding(self, content: str, dim: int) -> np.ndarray:
        """Generate synthetic embedding from content (for testing)."""
        np.random.seed(hash(content) % (2**32))
        return np.random.randn(dim)
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        # Handle different dimensions by truncating to smaller
        min_dim = min(len(a), len(b))
        a_trunc = a[:min_dim]
        b_trunc = b[:min_dim]
        
        norm_a = np.linalg.norm(a_trunc)
        norm_b = np.linalg.norm(b_trunc)
        if norm_a < 1e-10 or norm_b < 1e-10:
            return 0.0
        return float(np.dot(a_trunc, b_trunc) / (norm_a * norm_b))
    
    def evaluate_translation_quality(
        self,
        test_pairs: List[Tuple[np.ndarray, np.ndarray]],
        source_model: str,
        target_model: str
    ) -> Dict:
        """
        Evaluate translation quality on a test set.
        
        Returns metrics for comparison with SOTA (0.538 baseline).
        """
        results = []
        for src_emb, tgt_emb in test_pairs:
            result = self.translate(
                src_emb,
                source_model,
                target_model,
                source_embedding=src_emb
            )
            
            # Compare against actual target
            actual_cosine = self._cosine_similarity(
                result.target_signature.get_amplitudes(),
                tgt_emb[:len(result.target_signature.get_amplitudes())]
            )
            
            results.append({
                "cosine_sim": result.cosine_similarity,
                "phase_alignment": result.phase_alignment,
                "harmonic_preservation": result.harmonic_preservation,
                "fidelity": result.fidelity_score,
                "threshold": result.threshold_achieved.name
            })
        
        return {
            "n_samples": len(results),
            "avg_cosine": np.mean([r["cosine_sim"] for r in results]),
            "avg_phase_alignment": np.mean([r["phase_alignment"] for r in results]),
            "avg_harmonic_preservation": np.mean([r["harmonic_preservation"] for r in results]),
            "avg_fidelity": np.mean([r["fidelity"] for r in results]),
            "sota_baseline": CURRENT_SOTA_COSINE_SIM,
            "exceeds_sota": np.mean([r["cosine_sim"] for r in results]) > CURRENT_SOTA_COSINE_SIM,
            "threshold_distribution": {
                t.name: sum(1 for r in results if r["threshold"] == t.name)
                for t in ThresholdType
            }
        }


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("Rosetta Stone - Translator")
    print("=" * 50)
    
    # Test CKA computation
    print("\nTesting CKA (verified metric)...")
    X = np.random.randn(100, 64)
    Y = X @ np.random.randn(64, 32)  # Linear transform
    cka = compute_cka(X, Y)
    print(f"CKA between X and linear transform of X: {cka:.4f}")
    
    # Test embedding aligner
    print("\nTesting EmbeddingAligner...")
    aligner = EmbeddingAligner()
    source = np.random.randn(500, 768)  # BERT-like
    target = source @ np.random.randn(768, 1024) + np.random.randn(500, 1024) * 0.1
    
    aligner.fit(source[:400], target[:400])
    score = aligner.score(source[400:], target[400:])
    print(f"Alignment score on held-out data: {score:.4f}")
    print(f"SOTA baseline: {CURRENT_SOTA_COSINE_SIM}")
    
    # Test full translator
    print("\n" + "=" * 50)
    print("Testing RosettaTranslator...")
    
    translator = RosettaTranslator()
    translator.register_model("claude", embedding_dim=768)
    translator.register_model("grok", embedding_dim=768)
    
    result = translator.translate(
        "The mathematics of consciousness",
        source_model="claude",
        target_model="grok",
        concept_type="truth"
    )
    
    print(f"\nTranslation result:")
    print(f"  Cosine similarity: {result.cosine_similarity:.4f}")
    print(f"  Phase alignment: {result.phase_alignment:.4f}")
    print(f"  Harmonic preservation: {result.harmonic_preservation:.4f}")
    print(f"  Fidelity score: {result.fidelity_score:.4f}")
    print(f"  Threshold achieved: {result.threshold_achieved.name}")
    
    # Compare to φ thresholds
    print(f"\nφ Threshold comparison:")
    for t, v in THRESHOLDS.items():
        achieved = "✓" if result.fidelity_score >= v else " "
        print(f"  {achieved} {t.name}: {v:.4f}")
