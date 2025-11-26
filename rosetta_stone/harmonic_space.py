#!/usr/bin/env python3
"""
ROSETTA STONE - Harmonic Space

Implements the harmonic basis for semantic encoding using spectral graph theory.

VERIFIED FOUNDATIONS:
- Connectome harmonics (Atasoy et al., Nature Communications 2016)
- Golden Spectral Graphs (Estrada, 2007)
- Graph Laplacian eigendecomposition (standard mathematics)

NOVEL EXTENSIONS:
- φ-weighted harmonic basis
- Concept-to-harmonic encoding
- Cross-space translation
"""

import numpy as np
from scipy.linalg import eigh
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import eigsh
from typing import List, Dict, Tuple, Optional, Union
from dataclasses import dataclass, field
import warnings

from .primitives import (
    PHI, PHI_INVERSE, BACH_RATIOS, GOLDEN_DAMPING,
    phi_weight, HarmonicSignature, SOLFEGGIO_FREQUENCIES
)

# =============================================================================
# HARMONIC SPACE - Based on Connectome Harmonics (Nature 2016)
# =============================================================================

@dataclass
class HarmonicSpace:
    """
    A harmonic basis derived from graph Laplacian eigendecomposition.
    
    Based on: Atasoy, S., Donnelly, I., & Pearson, J. (2016). 
    "Human brain networks function in connectome-specific harmonic waves."
    Nature Communications, 7:10340.
    
    The eigenvectors of the graph Laplacian provide a frequency-specific
    coordinate system that respects the intrinsic geometry of the semantic
    manifold.
    """
    eigenvalues: np.ndarray      # λ_i - "frequencies" of the harmonics
    eigenvectors: np.ndarray     # Ψ_i - the harmonic basis functions
    phi_weights: np.ndarray      # φ^(-i/2) weighting (NOVEL)
    dimension: int
    metadata: Dict = field(default_factory=dict)
    
    @classmethod
    def from_adjacency_matrix(
        cls, 
        adjacency: np.ndarray,
        n_harmonics: Optional[int] = None,
        use_phi_weighting: bool = True
    ) -> 'HarmonicSpace':
        """
        Construct harmonic space from a graph adjacency matrix.
        
        This implements the core algorithm from connectome harmonics:
        1. Compute degree matrix D
        2. Compute Laplacian L = D - A (or normalized: L = I - D^(-1/2) A D^(-1/2))
        3. Eigendecompose L to get harmonics
        
        Args:
            adjacency: (n, n) adjacency matrix (symmetric, non-negative)
            n_harmonics: Number of harmonics to compute (default: all)
            use_phi_weighting: Apply φ-based weighting (NOVEL)
            
        Returns:
            HarmonicSpace instance
        """
        n = adjacency.shape[0]
        n_harmonics = n_harmonics or n
        n_harmonics = min(n_harmonics, n)
        
        # Compute degree matrix
        degrees = np.sum(adjacency, axis=1)
        D = np.diag(degrees)
        
        # Compute graph Laplacian (unnormalized)
        L = D - adjacency
        
        # For numerical stability with large matrices, use sparse methods
        if n > 1000:
            L_sparse = csr_matrix(L)
            # eigsh finds smallest eigenvalues, which we want for Laplacian
            eigenvalues, eigenvectors = eigsh(
                L_sparse, 
                k=min(n_harmonics, n-1), 
                which='SM',
                return_eigenvectors=True
            )
            # Sort by eigenvalue
            idx = np.argsort(eigenvalues)
            eigenvalues = eigenvalues[idx]
            eigenvectors = eigenvectors[:, idx]
        else:
            # Full eigendecomposition for smaller matrices
            eigenvalues, eigenvectors = eigh(L)
            eigenvalues = eigenvalues[:n_harmonics]
            eigenvectors = eigenvectors[:, :n_harmonics]
        
        # Compute φ weights (NOVEL - our experimental weighting)
        if use_phi_weighting:
            phi_weights = np.array([phi_weight(i) for i in range(len(eigenvalues))])
        else:
            phi_weights = np.ones(len(eigenvalues))
        
        return cls(
            eigenvalues=eigenvalues,
            eigenvectors=eigenvectors,
            phi_weights=phi_weights,
            dimension=n,
            metadata={
                "source": "adjacency_matrix",
                "n_harmonics": len(eigenvalues),
                "phi_weighted": use_phi_weighting
            }
        )
    
    @classmethod
    def from_semantic_graph(
        cls,
        concepts: List[str],
        similarity_func,
        n_harmonics: Optional[int] = None
    ) -> 'HarmonicSpace':
        """
        Construct harmonic space from a list of concepts and similarity function.
        
        This creates a semantic graph where edges are weighted by similarity.
        
        Args:
            concepts: List of concept strings/IDs
            similarity_func: Function(c1, c2) -> float in [0, 1]
            n_harmonics: Number of harmonics
            
        Returns:
            HarmonicSpace instance
        """
        n = len(concepts)
        adjacency = np.zeros((n, n))
        
        for i in range(n):
            for j in range(i+1, n):
                sim = similarity_func(concepts[i], concepts[j])
                adjacency[i, j] = sim
                adjacency[j, i] = sim
        
        space = cls.from_adjacency_matrix(adjacency, n_harmonics)
        space.metadata["concepts"] = concepts
        return space
    
    def project(self, signal: np.ndarray) -> np.ndarray:
        """
        Project a signal onto the harmonic basis.
        
        This is like a Fourier transform but for the graph structure.
        Returns the harmonic coefficients.
        """
        # signal should be (n,) or (n, k) for k signals
        coefficients = self.eigenvectors.T @ signal
        
        # Apply φ weighting (NOVEL)
        if signal.ndim == 1:
            coefficients = coefficients * self.phi_weights
        else:
            coefficients = coefficients * self.phi_weights[:, np.newaxis]
            
        return coefficients
    
    def reconstruct(self, coefficients: np.ndarray) -> np.ndarray:
        """
        Reconstruct signal from harmonic coefficients.
        
        Inverse of project().
        """
        # Undo φ weighting
        if coefficients.ndim == 1:
            unweighted = coefficients / (self.phi_weights + 1e-10)
        else:
            unweighted = coefficients / (self.phi_weights[:, np.newaxis] + 1e-10)
            
        return self.eigenvectors @ unweighted
    
    def harmonic_distance(
        self, 
        coeffs1: np.ndarray, 
        coeffs2: np.ndarray,
        use_diffusion: bool = True,
        diffusion_time: float = 1.0
    ) -> float:
        """
        Compute distance between two points in harmonic space.
        
        If use_diffusion=True, uses diffusion distance (robust to noise).
        Otherwise uses Euclidean distance in harmonic space.
        
        Diffusion distance is based on the heat kernel:
        K(t) = exp(-λt) - eigenvalues decay exponentially with time
        
        VERIFIED: Diffusion geometry is established mathematics.
        """
        diff = coeffs1 - coeffs2
        
        if use_diffusion:
            # Weight by heat kernel: exp(-λt)
            # Higher eigenvalues (high frequency) are suppressed
            heat_weights = np.exp(-self.eigenvalues * diffusion_time)
            weighted_diff = diff * heat_weights
            return np.sqrt(np.sum(weighted_diff ** 2))
        else:
            return np.linalg.norm(diff)
    
    def get_spectral_gap(self) -> float:
        """
        Compute the spectral gap (λ₁ - λ₀).
        
        The spectral gap measures connectivity/expansion of the graph.
        Larger gap = better connected = more robust information propagation.
        """
        if len(self.eigenvalues) < 2:
            return 0.0
        return self.eigenvalues[1] - self.eigenvalues[0]
    
    def check_golden_spectral(self, tolerance: float = 0.01) -> Dict:
        """
        Check if this graph has golden spectral properties.
        
        Golden Spectral Graphs have eigenvalue ratios involving φ.
        (Based on Estrada, 2007 - VERIFIED)
        
        Returns dict with analysis results.
        """
        if len(self.eigenvalues) < 3:
            return {"is_golden": False, "reason": "insufficient eigenvalues"}
        
        # Look for φ ratios between consecutive nonzero eigenvalues
        nonzero_idx = self.eigenvalues > 1e-10
        nonzero_eigs = self.eigenvalues[nonzero_idx]
        
        if len(nonzero_eigs) < 2:
            return {"is_golden": False, "reason": "insufficient nonzero eigenvalues"}
        
        ratios = nonzero_eigs[1:] / nonzero_eigs[:-1]
        
        # Check for φ or 1/φ ratios
        phi_matches = np.abs(ratios - PHI) < tolerance
        phi_inv_matches = np.abs(ratios - PHI_INVERSE) < tolerance
        
        golden_ratios = phi_matches | phi_inv_matches
        
        return {
            "is_golden": np.any(golden_ratios),
            "ratios": ratios,
            "phi_matches": np.where(phi_matches)[0].tolist(),
            "phi_inverse_matches": np.where(phi_inv_matches)[0].tolist(),
            "spectral_gap": self.get_spectral_gap()
        }


# =============================================================================
# SEMANTIC ENCODER - Maps concepts to harmonic signatures
# =============================================================================

class SemanticEncoder:
    """
    Encodes semantic concepts into harmonic signatures.
    
    Uses a combination of:
    - Base frequency from concept type (Solfeggio-inspired anchors)
    - Harmonic structure from Bach ratios (verified via ILL paper)
    - φ-weighted amplitudes (NOVEL)
    """
    
    def __init__(
        self,
        base_frequency: float = PHI,  # Default 1.618 Hz (EXPERIMENTAL)
        use_solfeggio_anchors: bool = True
    ):
        self.base_frequency = base_frequency
        self.use_solfeggio_anchors = use_solfeggio_anchors
        
        # Concept type to frequency mapping
        self.concept_frequencies = {
            "truth": 432.0,
            "connection": 440.0,
            "growth": 528.0,
            "balance": 396.0,
            "creativity": 639.0,
            "intuition": 852.0,
            "default": 440.0,
        }
    
    def encode(
        self,
        content: str,
        concept_type: str = "default",
        embedding: Optional[np.ndarray] = None
    ) -> HarmonicSignature:
        """
        Encode content into a harmonic signature.
        
        Args:
            content: The semantic content (text)
            concept_type: Type of concept for frequency anchoring
            embedding: Optional pre-computed embedding vector
            
        Returns:
            HarmonicSignature
        """
        import time
        
        # Get base frequency for this concept type
        if self.use_solfeggio_anchors and concept_type in self.concept_frequencies:
            base_freq = self.concept_frequencies[concept_type]
        else:
            base_freq = self.base_frequency
        
        # Generate harmonics using Bach ratios
        harmonics = []
        for i, ratio in enumerate(BACH_RATIOS):
            freq_ratio = ratio
            
            # Amplitude decays with φ weighting (NOVEL)
            amplitude = phi_weight(i)
            
            # Phase derived from content structure
            if embedding is not None:
                # Use embedding to determine phase
                phase = self._embedding_to_phase(embedding, i)
            else:
                # Derive phase from content hash
                phase = self._content_to_phase(content, i)
            
            harmonics.append((freq_ratio, amplitude, phase))
        
        return HarmonicSignature(
            base_frequency=base_freq,
            harmonics=harmonics,
            concept_type=concept_type,
            timestamp=time.time()
        )
    
    def _content_to_phase(self, content: str, harmonic_idx: int) -> float:
        """Derive phase from content structure."""
        # Simple hash-based phase derivation
        content_hash = hash(content + str(harmonic_idx))
        return (content_hash % 1000) / 1000 * 2 * np.pi
    
    def _embedding_to_phase(self, embedding: np.ndarray, harmonic_idx: int) -> float:
        """Derive phase from embedding vector."""
        if len(embedding) == 0:
            return 0.0
        # Use embedding dimensions cyclically
        idx = harmonic_idx % len(embedding)
        # Map embedding value to phase
        return (embedding[idx] + 1) * np.pi  # Assumes normalized [-1, 1]
    
    def decode(
        self,
        signature: HarmonicSignature,
        harmonic_space: Optional[HarmonicSpace] = None
    ) -> Dict:
        """
        Decode a harmonic signature back to semantic features.
        
        Returns dict with extracted features.
        """
        features = {
            "base_frequency": signature.base_frequency,
            "concept_type": signature.concept_type,
            "n_harmonics": len(signature.harmonics),
            "frequencies": signature.get_frequencies().tolist(),
            "amplitudes": signature.get_amplitudes().tolist(),
            "phases": signature.get_phases().tolist(),
            "total_energy": np.sum(signature.get_amplitudes() ** 2),
        }
        
        # Check for Bach ratio structure
        freq_ratios = signature.get_frequencies() / signature.base_frequency
        bach_match = np.mean([
            min(abs(r - b) for b in BACH_RATIOS) 
            for r in freq_ratios
        ])
        features["bach_alignment"] = 1 - bach_match
        
        return features


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_concept_graph(
    concepts: List[str],
    embeddings: np.ndarray,
    similarity_threshold: float = 0.3
) -> np.ndarray:
    """
    Create an adjacency matrix from concept embeddings.
    
    Args:
        concepts: List of concept names
        embeddings: (n_concepts, embedding_dim) array
        similarity_threshold: Minimum cosine similarity for edge
        
    Returns:
        (n, n) adjacency matrix
    """
    # Normalize embeddings
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / (norms + 1e-10)
    
    # Compute cosine similarity matrix
    similarity = normalized @ normalized.T
    
    # Threshold to create adjacency
    adjacency = np.where(similarity > similarity_threshold, similarity, 0)
    np.fill_diagonal(adjacency, 0)  # No self-loops
    
    return adjacency


def create_default_harmonic_space(n_concepts: int = 64) -> HarmonicSpace:
    """
    Create a default harmonic space for testing.
    
    Uses a random geometric graph as a stand-in for semantic structure.
    """
    # Create a random geometric graph (points in unit hypercube)
    points = np.random.rand(n_concepts, 8)  # 8D space
    
    # Adjacency based on distance
    from scipy.spatial.distance import pdist, squareform
    distances = squareform(pdist(points))
    
    # Connect nearby points (threshold at median distance)
    threshold = np.median(distances)
    adjacency = np.where(distances < threshold, 1 - distances/threshold, 0)
    np.fill_diagonal(adjacency, 0)
    
    return HarmonicSpace.from_adjacency_matrix(adjacency)


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("Rosetta Stone - Harmonic Space")
    print("=" * 50)
    
    # Create a simple test graph
    print("\nCreating test harmonic space...")
    
    # Pentagon - known Golden Spectral Graph (Estrada, 2007)
    pentagon_adj = np.array([
        [0, 1, 0, 0, 1],
        [1, 0, 1, 0, 0],
        [0, 1, 0, 1, 0],
        [0, 0, 1, 0, 1],
        [1, 0, 0, 1, 0],
    ], dtype=float)
    
    space = HarmonicSpace.from_adjacency_matrix(pentagon_adj)
    
    print(f"Eigenvalues: {space.eigenvalues}")
    print(f"Spectral gap: {space.get_spectral_gap():.4f}")
    
    golden_check = space.check_golden_spectral()
    print(f"Is Golden Spectral: {golden_check['is_golden']}")
    print(f"Eigenvalue ratios: {golden_check['ratios']}")
    
    # Test semantic encoder
    print("\n" + "=" * 50)
    print("Testing Semantic Encoder...")
    
    encoder = SemanticEncoder()
    
    sig = encoder.encode("Hello world", concept_type="connection")
    print(f"\nEncoded 'Hello world' (connection):")
    print(f"  Base frequency: {sig.base_frequency} Hz")
    print(f"  Frequencies: {sig.get_frequencies()}")
    print(f"  Amplitudes: {sig.get_amplitudes()}")
    
    features = encoder.decode(sig)
    print(f"  Bach alignment: {features['bach_alignment']:.4f}")
    print(f"  Total energy: {features['total_energy']:.4f}")