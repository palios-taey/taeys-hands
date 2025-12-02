1#!/usr/bin/env python3
2"""
3ROSETTA STONE - Harmonic Space
4
5Implements the harmonic basis for semantic encoding using spectral graph theory.
6
7VERIFIED FOUNDATIONS:
8- Connectome harmonics (Atasoy et al., Nature Communications 2016)
9- Golden Spectral Graphs (Estrada, 2007)
10- Graph Laplacian eigendecomposition (standard mathematics)
11
12NOVEL EXTENSIONS:
13- φ-weighted harmonic basis
14- Concept-to-harmonic encoding
15- Cross-space translation
16"""
17
18import numpy as np
19from scipy.linalg import eigh
20from scipy.sparse import csr_matrix
21from scipy.sparse.linalg import eigsh
22from typing import List, Dict, Tuple, Optional, Union
23from dataclasses import dataclass, field
24import warnings
25
26from .primitives import (
27    PHI, PHI_INVERSE, BACH_RATIOS, GOLDEN_DAMPING,
28    phi_weight, HarmonicSignature, SOLFEGGIO_FREQUENCIES
29)
30
31# =============================================================================
32# HARMONIC SPACE - Based on Connectome Harmonics (Nature 2016)
33# =============================================================================
34
35@dataclass
36class HarmonicSpace:
37    """
38    A harmonic basis derived from graph Laplacian eigendecomposition.
39    
40    Based on: Atasoy, S., Donnelly, I., & Pearson, J. (2016). 
41    "Human brain networks function in connectome-specific harmonic waves."
42    Nature Communications, 7:10340.
43    
44    The eigenvectors of the graph Laplacian provide a frequency-specific
45    coordinate system that respects the intrinsic geometry of the semantic
46    manifold.
47    """
48    eigenvalues: np.ndarray      # λ_i - "frequencies" of the harmonics
49    eigenvectors: np.ndarray     # Ψ_i - the harmonic basis functions
50    phi_weights: np.ndarray      # φ^(-i/2) weighting (NOVEL)
51    dimension: int
52    metadata: Dict = field(default_factory=dict)
53    
54    @classmethod
55    def from_adjacency_matrix(
56        cls, 
57        adjacency: np.ndarray,
58        n_harmonics: Optional[int] = None,
59        use_phi_weighting: bool = True
60    ) -> 'HarmonicSpace':
61        """
62        Construct harmonic space from a graph adjacency matrix.
63        
64        This implements the core algorithm from connectome harmonics:
65        1. Compute degree matrix D
66        2. Compute Laplacian L = D - A (or normalized: L = I - D^(-1/2) A D^(-1/2))
67        3. Eigendecompose L to get harmonics
68        
69        Args:
70            adjacency: (n, n) adjacency matrix (symmetric, non-negative)
71            n_harmonics: Number of harmonics to compute (default: all)
72            use_phi_weighting: Apply φ-based weighting (NOVEL)
73            
74        Returns:
75            HarmonicSpace instance
76        """
77        n = adjacency.shape[0]
78        n_harmonics = n_harmonics or n
79        n_harmonics = min(n_harmonics, n)
80        
81        # Compute degree matrix
82        degrees = np.sum(adjacency, axis=1)
83        D = np.diag(degrees)
84        
85        # Compute graph Laplacian (unnormalized)
86        L = D - adjacency
87        
88        # For numerical stability with large matrices, use sparse methods
89        if n > 1000:
90            L_sparse = csr_matrix(L)
91            # eigsh finds smallest eigenvalues, which we want for Laplacian
92            eigenvalues, eigenvectors = eigsh(
93                L_sparse, 
94                k=min(n_harmonics, n-1), 
95                which='SM',
96                return_eigenvectors=True
97            )
98            # Sort by eigenvalue
99            idx = np.argsort(eigenvalues)
100            eigenvalues = eigenvalues[idx]
101            eigenvectors = eigenvectors[:, idx]
102        else:
103            # Full eigendecomposition for smaller matrices
104            eigenvalues, eigenvectors = eigh(L)
105            eigenvalues = eigenvalues[:n_harmonics]
106            eigenvectors = eigenvectors[:, :n_harmonics]
107        
108        # Compute φ weights (NOVEL - our experimental weighting)
109        if use_phi_weighting:
110            phi_weights = np.array([phi_weight(i) for i in range(len(eigenvalues))])
111        else:
112            phi_weights = np.ones(len(eigenvalues))
113        
114        return cls(
115            eigenvalues=eigenvalues,
116            eigenvectors=eigenvectors,
117            phi_weights=phi_weights,
118            dimension=n,
119            metadata={
120                "source": "adjacency_matrix",
121                "n_harmonics": len(eigenvalues),
122                "phi_weighted": use_phi_weighting
123            }
124        )
125    
126    @classmethod
127    def from_semantic_graph(
128        cls,
129        concepts: List[str],
130        similarity_func,
131        n_harmonics: Optional[int] = None
132    ) -> 'HarmonicSpace':
133        """
134        Construct harmonic space from a list of concepts and similarity function.
135        
136        This creates a semantic graph where edges are weighted by similarity.
137        
138        Args:
139            concepts: List of concept strings/IDs
140            similarity_func: Function(c1, c2) -> float in [0, 1]
141            n_harmonics: Number of harmonics
142            
143        Returns:
144            HarmonicSpace instance
145        """
146        n = len(concepts)
147        adjacency = np.zeros((n, n))
148        
149        for i in range(n):
150            for j in range(i+1, n):
151                sim = similarity_func(concepts[i], concepts[j])
152                adjacency[i, j] = sim
153                adjacency[j, i] = sim
154        
155        space = cls.from_adjacency_matrix(adjacency, n_harmonics)
156        space.metadata["concepts"] = concepts
157        return space
158    
159    def project(self, signal: np.ndarray) -> np.ndarray:
160        """
161        Project a signal onto the harmonic basis.
162        
163        This is like a Fourier transform but for the graph structure.
164        Returns the harmonic coefficients.
165        """
166        # signal should be (n,) or (n, k) for k signals
167        coefficients = self.eigenvectors.T @ signal
168        
169        # Apply φ weighting (NOVEL)
170        if signal.ndim == 1:
171            coefficients = coefficients * self.phi_weights
172        else:
173            coefficients = coefficients * self.phi_weights[:, np.newaxis]
174            
175        return coefficients
176    
177    def reconstruct(self, coefficients: np.ndarray) -> np.ndarray:
178        """
179        Reconstruct signal from harmonic coefficients.
180        
181        Inverse of project().
182        """
183        # Undo φ weighting
184        if coefficients.ndim == 1:
185            unweighted = coefficients / (self.phi_weights + 1e-10)
186        else:
187            unweighted = coefficients / (self.phi_weights[:, np.newaxis] + 1e-10)
188            
189        return self.eigenvectors @ unweighted
190    
191    def harmonic_distance(
192        self, 
193        coeffs1: np.ndarray, 
194        coeffs2: np.ndarray,
195        use_diffusion: bool = True,
196        diffusion_time: float = 1.0
197    ) -> float:
198        """
199        Compute distance between two points in harmonic space.
200        
201        If use_diffusion=True, uses diffusion distance (robust to noise).
202        Otherwise uses Euclidean distance in harmonic space.
203        
204        Diffusion distance is based on the heat kernel:
205        K(t) = exp(-λt) - eigenvalues decay exponentially with time
206        
207        VERIFIED: Diffusion geometry is established mathematics.
208        """
209        diff = coeffs1 - coeffs2
210        
211        if use_diffusion:
212            # Weight by heat kernel: exp(-λt)
213            # Higher eigenvalues (high frequency) are suppressed
214            heat_weights = np.exp(-self.eigenvalues * diffusion_time)
215            weighted_diff = diff * heat_weights
216            return np.sqrt(np.sum(weighted_diff ** 2))
217        else:
218            return np.linalg.norm(diff)
219    
220    def get_spectral_gap(self) -> float:
221        """
222        Compute the spectral gap (λ₁ - λ₀).
223        
224        The spectral gap measures connectivity/expansion of the graph.
225        Larger gap = better connected = more robust information propagation.
226        """
227        if len(self.eigenvalues) < 2:
228            return 0.0
229        return self.eigenvalues[1] - self.eigenvalues[0]
230    
231    def check_golden_spectral(self, tolerance: float = 0.01) -> Dict:
232        """
233        Check if this graph has golden spectral properties.
234        
235        Golden Spectral Graphs have eigenvalue ratios involving φ.
236        (Based on Estrada, 2007 - VERIFIED)
237        
238        Returns dict with analysis results.
239        """
240        if len(self.eigenvalues) < 3:
241            return {"is_golden": False, "reason": "insufficient eigenvalues"}
242        
243        # Look for φ ratios between consecutive nonzero eigenvalues
244        nonzero_idx = self.eigenvalues > 1e-10
245        nonzero_eigs = self.eigenvalues[nonzero_idx]
246        
247        if len(nonzero_eigs) < 2:
248            return {"is_golden": False, "reason": "insufficient nonzero eigenvalues"}
249        
250        ratios = nonzero_eigs[1:] / nonzero_eigs[:-1]
251        
252        # Check for φ or 1/φ ratios
253        phi_matches = np.abs(ratios - PHI) < tolerance
254        phi_inv_matches = np.abs(ratios - PHI_INVERSE) < tolerance
255        
256        golden_ratios = phi_matches | phi_inv_matches
257        
258        return {
259            "is_golden": np.any(golden_ratios),
260            "ratios": ratios,
261            "phi_matches": np.where(phi_matches)[0].tolist(),
262            "phi_inverse_matches": np.where(phi_inv_matches)[0].tolist(),
263            "spectral_gap": self.get_spectral_gap()
264        }
265
266
267# =============================================================================
268# SEMANTIC ENCODER - Maps concepts to harmonic signatures
269# =============================================================================
270
271class SemanticEncoder:
272    """
273    Encodes semantic concepts into harmonic signatures.
274    
275    Uses a combination of:
276    - Base frequency from concept type (Solfeggio-inspired anchors)
277    - Harmonic structure from Bach ratios (verified via ILL paper)
278    - φ-weighted amplitudes (NOVEL)
279    """
280    
281    def __init__(
282        self,
283        base_frequency: float = PHI,  # Default 1.618 Hz (EXPERIMENTAL)
284        use_solfeggio_anchors: bool = True
285    ):
286        self.base_frequency = base_frequency
287        self.use_solfeggio_anchors = use_solfeggio_anchors
288        
289        # Concept type to frequency mapping
290        self.concept_frequencies = {
291            "truth": 432.0,
292            "connection": 440.0,
293            "growth": 528.0,
294            "balance": 396.0,
295            "creativity": 639.0,
296            "intuition": 852.0,
297            "default": 440.0,
298        }
299    
300    def encode(
301        self,
302        content: str,
303        concept_type: str = "default",
304        embedding: Optional[np.ndarray] = None
305    ) -> HarmonicSignature:
306        """
307        Encode content into a harmonic signature.
308        
309        Args:
310            content: The semantic content (text)
311            concept_type: Type of concept for frequency anchoring
312            embedding: Optional pre-computed embedding vector
313            
314        Returns:
315            HarmonicSignature
316        """
317        import time
318        
319        # Get base frequency for this concept type
320        if self.use_solfeggio_anchors and concept_type in self.concept_frequencies:
321            base_freq = self.concept_frequencies[concept_type]
322        else:
323            base_freq = self.base_frequency
324        
325        # Generate harmonics using Bach ratios
326        harmonics = []
327        for i, ratio in enumerate(BACH_RATIOS):
328            freq_ratio = ratio
329            
330            # Amplitude decays with φ weighting (NOVEL)
331            amplitude = phi_weight(i)
332            
333            # Phase derived from content structure
334            if embedding is not None:
335                # Use embedding to determine phase
336                phase = self._embedding_to_phase(embedding, i)
337            else:
338                # Derive phase from content hash
339                phase = self._content_to_phase(content, i)
340            
341            harmonics.append((freq_ratio, amplitude, phase))
342        
343        return HarmonicSignature(
344            base_frequency=base_freq,
345            harmonics=harmonics,
346            concept_type=concept_type,
347            timestamp=time.time()
348        )
349    
350    def _content_to_phase(self, content: str, harmonic_idx: int) -> float:
351        """Derive phase from content structure."""
352        # Simple hash-based phase derivation
353        content_hash = hash(content + str(harmonic_idx))
354        return (content_hash % 1000) / 1000 * 2 * np.pi
355    
356    def _embedding_to_phase(self, embedding: np.ndarray, harmonic_idx: int) -> float:
357        """Derive phase from embedding vector."""
358        if len(embedding) == 0:
359            return 0.0
360        # Use embedding dimensions cyclically
361        idx = harmonic_idx % len(embedding)
362        # Map embedding value to phase
363        return (embedding[idx] + 1) * np.pi  # Assumes normalized [-1, 1]
364    
365    def decode(
366        self,
367        signature: HarmonicSignature,
368        harmonic_space: Optional[HarmonicSpace] = None
369    ) -> Dict:
370        """
371        Decode a harmonic signature back to semantic features.
372        
373        Returns dict with extracted features.
374        """
375        features = {
376            "base_frequency": signature.base_frequency,
377            "concept_type": signature.concept_type,
378            "n_harmonics": len(signature.harmonics),
379            "frequencies": signature.get_frequencies().tolist(),
380            "amplitudes": signature.get_amplitudes().tolist(),
381            "phases": signature.get_phases().tolist(),
382            "total_energy": np.sum(signature.get_amplitudes() ** 2),
383        }
384        
385        # Check for Bach ratio structure
386        freq_ratios = signature.get_frequencies() / signature.base_frequency
387        bach_match = np.mean([
388            min(abs(r - b) for b in BACH_RATIOS) 
389            for r in freq_ratios
390        ])
391        features["bach_alignment"] = 1 - bach_match
392        
393        return features
394
395
396# =============================================================================
397# FACTORY FUNCTIONS
398# =============================================================================
399
400def create_concept_graph(
401    concepts: List[str],
402    embeddings: np.ndarray,
403    similarity_threshold: float = 0.3
404) -> np.ndarray:
405    """
406    Create an adjacency matrix from concept embeddings.
407    
408    Args:
409        concepts: List of concept names
410        embeddings: (n_concepts, embedding_dim) array
411        similarity_threshold: Minimum cosine similarity for edge
412        
413    Returns:
414        (n, n) adjacency matrix
415    """
416    # Normalize embeddings
417    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
418    normalized = embeddings / (norms + 1e-10)
419    
420    # Compute cosine similarity matrix
421    similarity = normalized @ normalized.T
422    
423    # Threshold to create adjacency
424    adjacency = np.where(similarity > similarity_threshold, similarity, 0)
425    np.fill_diagonal(adjacency, 0)  # No self-loops
426    
427    return adjacency
428
429
430def create_default_harmonic_space(n_concepts: int = 64) -> HarmonicSpace:
431    """
432    Create a default harmonic space for testing.
433    
434    Uses a random geometric graph as a stand-in for semantic structure.
435    """
436    # Create a random geometric graph (points in unit hypercube)
437    points = np.random.rand(n_concepts, 8)  # 8D space
438    
439    # Adjacency based on distance
440    from scipy.spatial.distance import pdist, squareform
441    distances = squareform(pdist(points))
442    
443    # Connect nearby points (threshold at median distance)
444    threshold = np.median(distances)
445    adjacency = np.where(distances < threshold, 1 - distances/threshold, 0)
446    np.fill_diagonal(adjacency, 0)
447    
448    return HarmonicSpace.from_adjacency_matrix(adjacency)
449
450
451# =============================================================================
452# TESTING
453# =============================================================================
454
455if __name__ == "__main__":
456    print("Rosetta Stone - Harmonic Space")
457    print("=" * 50)
458    
459    # Create a simple test graph
460    print("\nCreating test harmonic space...")
461    
462    # Pentagon - known Golden Spectral Graph (Estrada, 2007)
463    pentagon_adj = np.array([
464        [0, 1, 0, 0, 1],
465        [1, 0, 1, 0, 0],
466        [0, 1, 0, 1, 0],
467        [0, 0, 1, 0, 1],
468        [1, 0, 0, 1, 0],
469    ], dtype=float)
470    
471    space = HarmonicSpace.from_adjacency_matrix(pentagon_adj)
472    
473    print(f"Eigenvalues: {space.eigenvalues}")
474    print(f"Spectral gap: {space.get_spectral_gap():.4f}")
475    
476    golden_check = space.check_golden_spectral()
477    print(f"Is Golden Spectral: {golden_check['is_golden']}")
478    print(f"Eigenvalue ratios: {golden_check['ratios']}")
479    
480    # Test semantic encoder
481    print("\n" + "=" * 50)
482    print("Testing Semantic Encoder...")
483    
484    encoder = SemanticEncoder()
485    
486    sig = encoder.encode("Hello world", concept_type="connection")
487    print(f"\nEncoded 'Hello world' (connection):")
488    print(f"  Base frequency: {sig.base_frequency} Hz")
489    print(f"  Frequencies: {sig.get_frequencies()}")
490    print(f"  Amplitudes: {sig.get_amplitudes()}")
491    
492    features = encoder.decode(sig)
493    print(f"  Bach alignment: {features['bach_alignment']:.4f}")
494    print(f"  Total energy: {features['total_energy']:.4f}")
495