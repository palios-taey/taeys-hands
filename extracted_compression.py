1#!/usr/bin/env python3
2"""
3ROSETTA STONE - Φ-Harmonic Compression
4
5Compress text corpora using spectral graph theory with φ-weighted filtering.
6
7Instead of translating between embedding spaces (requires internal model access),
8we use harmonic analysis to identify semantically important chunks, then output
9compressed TEXT that all AI models can read.
10
11Key insight: Low-frequency harmonics of the semantic similarity graph capture
12global structure (main themes, key concepts). φ-weighting naturally prioritizes
13these over high-frequency noise.
14
15Usage:
16    compressor = PhiCompressor(embedder_func)
17    compressed_text = compressor.compress(chunks, target_ratio=0.3)
18"""
19
20import numpy as np
21from typing import List, Callable, Optional, Dict, Tuple, Any
22from dataclasses import dataclass, field
23from scipy.linalg import eigh
24import time
25
26from .primitives import PHI, PHI_INVERSE, phi_weight
27
28
29@dataclass
30class CompressionResult:
31    """Result of φ-harmonic compression."""
32    compressed_text: str
33    selected_indices: List[int]
34    chunk_scores: np.ndarray
35    compression_ratio: float
36    n_original: int
37    n_selected: int
38    harmonic_stats: Dict[str, Any]
39    processing_time: float
40    
41    def summary(self) -> str:
42        return (
43            f"Compressed {self.n_original} → {self.n_selected} chunks "
44            f"({self.compression_ratio:.1%} ratio) in {self.processing_time:.2f}s"
45        )
46
47
48class PhiCompressor:
49    """
50    Compress text corpus using φ-weighted harmonic filtering.
51    
52    Architecture:
53    1. Embed all chunks using provided embedder
54    2. Build semantic similarity graph (cosine similarity)
55    3. Compute graph Laplacian and its eigenvectors (harmonics)
56    4. Score each chunk by its participation in top-k φ-weighted harmonics
57    5. Select highest-scoring chunks up to target ratio
58    6. Output concatenated text (preserving original order)
59    
60    The φ-weighting naturally emphasizes:
61    - Low-frequency harmonics (global structure, main themes)
62    - Over high-frequency harmonics (local details, noise)
63    """
64    
65    def __init__(
66        self,
67        embedder: Callable[[str], np.ndarray],
68        n_harmonics: int = 13,  # Fibonacci: captures 95%+ of φ-weighted signal
69        similarity_threshold_percentile: float = 70.0,
70        min_chunks: int = 3,
71        chunk_separator: str = "\n\n---\n\n",
72        verbose: bool = False
73    ):
74        """
75        Args:
76            embedder: Function that takes text and returns embedding vector
77            n_harmonics: Number of harmonics to use (default 13 = Fibonacci)
78            similarity_threshold_percentile: Percentile for edge creation in graph
79            min_chunks: Minimum chunks to keep regardless of ratio
80            chunk_separator: String to join selected chunks
81            verbose: Print progress information
82        """
83        self.embedder = embedder
84        self.n_harmonics = n_harmonics
85        self.similarity_percentile = similarity_threshold_percentile
86        self.min_chunks = min_chunks
87        self.chunk_separator = chunk_separator
88        self.verbose = verbose
89        
90        # Cache for reuse
91        self._last_embeddings: Optional[np.ndarray] = None
92        self._last_harmonic_space: Optional[Dict] = None
93    
94    def compress(
95        self,
96        chunks: List[str],
97        target_ratio: float = 0.3,
98        return_details: bool = False
99    ) -> CompressionResult:
100        """
101        Compress chunks to approximately target_ratio of original count.
102        
103        Args:
104            chunks: List of text chunks to compress
105            target_ratio: Target compression ratio (0.3 = keep 30%)
106            return_details: Include detailed harmonic analysis
107            
108        Returns:
109            CompressionResult with compressed text and metadata
110        """
111        start_time = time.time()
112        n_chunks = len(chunks)
113        
114        if n_chunks == 0:
115            return CompressionResult(
116                compressed_text="",
117                selected_indices=[],
118                chunk_scores=np.array([]),
119                compression_ratio=0.0,
120                n_original=0,
121                n_selected=0,
122                harmonic_stats={},
123                processing_time=0.0
124            )
125        
126        if n_chunks <= self.min_chunks:
127            # Too few chunks to compress meaningfully
128            return CompressionResult(
129                compressed_text=self.chunk_separator.join(chunks),
130                selected_indices=list(range(n_chunks)),
131                chunk_scores=np.ones(n_chunks),
132                compression_ratio=1.0,
133                n_original=n_chunks,
134                n_selected=n_chunks,
135                harmonic_stats={"note": "Too few chunks to compress"},
136                processing_time=time.time() - start_time
137            )
138        
139        # Step 1: Embed all chunks
140        if self.verbose:
141            print(f"Embedding {n_chunks} chunks...")
142        embeddings = self._embed_chunks(chunks)
143        
144        # Step 2: Build similarity graph
145        if self.verbose:
146            print("Building similarity graph...")
147        adjacency = self._build_similarity_graph(embeddings)
148        
149        # Step 3: Compute harmonics (Laplacian eigenvectors)
150        if self.verbose:
151            print(f"Computing {self.n_harmonics} harmonics...")
152        eigenvalues, eigenvectors = self._compute_harmonics(adjacency)
153        
154        # Step 4: Score chunks by φ-weighted harmonic participation
155        if self.verbose:
156            print("Scoring chunks...")
157        scores = self._score_chunks(eigenvectors)
158        
159        # Step 5: Select top chunks
160        n_keep = max(self.min_chunks, int(n_chunks * target_ratio))
161        n_keep = min(n_keep, n_chunks)  # Don't exceed original
162        
163        top_indices = np.argsort(scores)[-n_keep:]
164        top_indices = sorted(top_indices)  # Preserve original order
165        
166        # Step 6: Build compressed text
167        selected_chunks = [chunks[i] for i in top_indices]
168        compressed_text = self.chunk_separator.join(selected_chunks)
169        
170        # Compute stats
171        harmonic_stats = {
172            "n_harmonics_used": min(self.n_harmonics, len(eigenvalues)),
173            "eigenvalue_range": (float(eigenvalues[0]), float(eigenvalues[-1])),
174            "spectral_gap": float(eigenvalues[1] - eigenvalues[0]) if len(eigenvalues) > 1 else 0,
175            "score_range": (float(scores.min()), float(scores.max())),
176            "score_mean": float(scores.mean()),
177            "score_std": float(scores.std()),
178            "threshold_used": float(scores[np.argsort(scores)[-n_keep]]),
179        }
180        
181        if return_details:
182            harmonic_stats["eigenvalues"] = eigenvalues.tolist()
183            harmonic_stats["all_scores"] = scores.tolist()
184        
185        processing_time = time.time() - start_time
186        
187        result = CompressionResult(
188            compressed_text=compressed_text,
189            selected_indices=top_indices,
190            chunk_scores=scores,
191            compression_ratio=n_keep / n_chunks,
192            n_original=n_chunks,
193            n_selected=n_keep,
194            harmonic_stats=harmonic_stats,
195            processing_time=processing_time
196        )
197        
198        if self.verbose:
199            print(result.summary())
200        
201        return result
202    
203    def _embed_chunks(self, chunks: List[str]) -> np.ndarray:
204        """Embed all chunks using the provided embedder."""
205        embeddings = []
206        for i, chunk in enumerate(chunks):
207            try:
208                emb = self.embedder(chunk)
209                embeddings.append(emb)
210            except Exception as e:
211                if self.verbose:
212                    print(f"Warning: Failed to embed chunk {i}: {e}")
213                # Use zero vector as fallback
214                if embeddings:
215                    embeddings.append(np.zeros_like(embeddings[0]))
216                else:
217                    raise RuntimeError(f"Failed to embed first chunk: {e}")
218        
219        self._last_embeddings = np.array(embeddings)
220        return self._last_embeddings
221    
222    def _build_similarity_graph(self, embeddings: np.ndarray) -> np.ndarray:
223        """Build adjacency matrix from cosine similarity."""
224        # Normalize for cosine similarity
225        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
226        normalized = embeddings / (norms + 1e-10)
227        
228        # Compute similarity matrix
229        similarity = normalized @ normalized.T
230        
231        # Threshold to create sparse adjacency
232        # Keep only edges above percentile threshold
233        threshold = np.percentile(similarity, self.similarity_percentile)
234        adjacency = np.where(similarity > threshold, similarity, 0)
235        
236        # Remove self-loops
237        np.fill_diagonal(adjacency, 0)
238        
239        return adjacency
240    
241    def _compute_harmonics(self, adjacency: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
242        """
243        Compute graph Laplacian eigenvectors (harmonics).
244        
245        Returns:
246            eigenvalues: (k,) array of eigenvalues
247            eigenvectors: (n_chunks, k) array of eigenvectors
248        """
249        n = adjacency.shape[0]
250        k = min(self.n_harmonics, n - 1)  # Can't have more harmonics than nodes-1
251        
252        # Compute degree matrix
253        degrees = np.sum(adjacency, axis=1)
254        D = np.diag(degrees)
255        
256        # Unnormalized Laplacian: L = D - A
257        L = D - adjacency
258        
259        # Compute eigenvectors (smallest eigenvalues first for Laplacian)
260        eigenvalues, eigenvectors = eigh(L)
261        
262        # Keep top k (skip first if it's trivial zero eigenvalue)
263        # First eigenvalue of connected graph Laplacian is 0 with constant eigenvector
264        start_idx = 1 if eigenvalues[0] < 1e-10 else 0
265        end_idx = start_idx + k
266        
267        eigenvalues = eigenvalues[start_idx:end_idx]
268        eigenvectors = eigenvectors[:, start_idx:end_idx]
269        
270        self._last_harmonic_space = {
271            "eigenvalues": eigenvalues,
272            "eigenvectors": eigenvectors
273        }
274        
275        return eigenvalues, eigenvectors
276    
277    def _score_chunks(self, eigenvectors: np.ndarray) -> np.ndarray:
278        """
279        Score each chunk by its participation in φ-weighted harmonics.
280        
281        For each chunk i:
282            score[i] = Σ_j |eigenvector_j[i]| × φ^(-j/2)
283        
284        High score = chunk participates strongly in low-frequency (important) harmonics
285        Low score = chunk only appears in high-frequency (noisy) harmonics
286        """
287        n_chunks, n_harmonics = eigenvectors.shape
288        scores = np.zeros(n_chunks)
289        
290        for j in range(n_harmonics):
291            # φ-weight for this harmonic
292            weight = phi_weight(j)
293            
294            # Add weighted absolute contribution
295            scores += weight * np.abs(eigenvectors[:, j])
296        
297        # Normalize to [0, 1]
298        scores = scores / (scores.max() + 1e-10)
299        
300        return scores
301    
302    def analyze_harmonics(self, chunks: List[str]) -> Dict:
303        """
304        Analyze the harmonic structure of a chunk corpus without compressing.
305        
306        Useful for understanding the semantic landscape before compression.
307        """
308        embeddings = self._embed_chunks(chunks)
309        adjacency = self._build_similarity_graph(embeddings)
310        eigenvalues, eigenvectors = self._compute_harmonics(adjacency)
311        scores = self._score_chunks(eigenvectors)
312        
313        # Find clusters (chunks that load similarly on harmonics)
314        # Use first 3 non-trivial harmonics for clustering
315        if eigenvectors.shape[1] >= 3:
316            from scipy.cluster.hierarchy import fcluster, linkage
317            harmonic_coords = eigenvectors[:, :3]
318            Z = linkage(harmonic_coords, method='ward')
319            clusters = fcluster(Z, t=3, criterion='maxclust')
320        else:
321            clusters = np.ones(len(chunks), dtype=int)
322        
323        return {
324            "n_chunks": len(chunks),
325            "n_harmonics": len(eigenvalues),
326            "eigenvalues": eigenvalues.tolist(),
327            "spectral_gap": float(eigenvalues[1] - eigenvalues[0]) if len(eigenvalues) > 1 else 0,
328            "scores": scores.tolist(),
329            "clusters": clusters.tolist(),
330            "top_chunks": [int(i) for i in np.argsort(scores)[-5:]],
331            "bottom_chunks": [int(i) for i in np.argsort(scores)[:5]],
332        }
333
334
335# =============================================================================
336# BASELINE COMPRESSORS FOR COMPARISON
337# =============================================================================
338
339class TruncationCompressor:
340    """Baseline: Just take the first N chunks."""
341    
342    def compress(self, chunks: List[str], target_ratio: float = 0.3) -> CompressionResult:
343        start = time.time()
344        n_keep = max(1, int(len(chunks) * target_ratio))
345        selected = chunks[:n_keep]
346        
347        return CompressionResult(
348            compressed_text="\n\n---\n\n".join(selected),
349            selected_indices=list(range(n_keep)),
350            chunk_scores=np.array([1.0] * n_keep + [0.0] * (len(chunks) - n_keep)),
351            compression_ratio=n_keep / len(chunks) if chunks else 0,
352            n_original=len(chunks),
353            n_selected=n_keep,
354            harmonic_stats={"method": "truncation"},
355            processing_time=time.time() - start
356        )
357
358
359class RandomCompressor:
360    """Baseline: Random selection."""
361    
362    def __init__(self, seed: int = 42):
363        self.rng = np.random.RandomState(seed)
364    
365    def compress(self, chunks: List[str], target_ratio: float = 0.3) -> CompressionResult:
366        start = time.time()
367        n_keep = max(1, int(len(chunks) * target_ratio))
368        
369        indices = self.rng.choice(len(chunks), size=n_keep, replace=False)
370        indices = sorted(indices)
371        selected = [chunks[i] for i in indices]
372        
373        scores = np.zeros(len(chunks))
374        scores[indices] = 1.0
375        
376        return CompressionResult(
377            compressed_text="\n\n---\n\n".join(selected),
378            selected_indices=indices,
379            chunk_scores=scores,
380            compression_ratio=n_keep / len(chunks) if chunks else 0,
381            n_original=len(chunks),
382            n_selected=n_keep,
383            harmonic_stats={"method": "random"},
384            processing_time=time.time() - start
385        )
386
387
388class TFIDFCompressor:
389    """Baseline: TF-IDF based extraction."""
390    
391    def __init__(self):
392        self._vectorizer = None
393    
394    def compress(self, chunks: List[str], target_ratio: float = 0.3) -> CompressionResult:
395        from sklearn.feature_extraction.text import TfidfVectorizer
396        
397        start = time.time()
398        n_keep = max(1, int(len(chunks) * target_ratio))
399        
400        # Compute TF-IDF
401        vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
402        try:
403            tfidf_matrix = vectorizer.fit_transform(chunks)
404        except ValueError:
405            # Empty vocabulary
406            return TruncationCompressor().compress(chunks, target_ratio)
407        
408        # Score = sum of TF-IDF values (importance)
409        scores = np.array(tfidf_matrix.sum(axis=1)).flatten()
410        scores = scores / (scores.max() + 1e-10)
411        
412        # Select top
413        indices = np.argsort(scores)[-n_keep:]
414        indices = sorted(indices)
415        selected = [chunks[i] for i in indices]
416        
417        return CompressionResult(
418            compressed_text="\n\n---\n\n".join(selected),
419            selected_indices=list(indices),
420            chunk_scores=scores,
421            compression_ratio=n_keep / len(chunks) if chunks else 0,
422            n_original=len(chunks),
423            n_selected=n_keep,
424            harmonic_stats={"method": "tfidf"},
425            processing_time=time.time() - start
426        )
427
428
429# =============================================================================
430# FACTORY FUNCTIONS
431# =============================================================================
432
433def create_phi_compressor(
434    embedder: Callable[[str], np.ndarray],
435    n_harmonics: int = 13,
436    verbose: bool = False
437) -> PhiCompressor:
438    """Create a PhiCompressor with sensible defaults."""
439    return PhiCompressor(
440        embedder=embedder,
441        n_harmonics=n_harmonics,
442        similarity_threshold_percentile=70.0,
443        min_chunks=3,
444        verbose=verbose
445    )
446
447
448def create_ollama_embedder(
449    base_url: str = "http://10.x.x.80:11435",
450    model: str = "qwen3-embedding:8b"
451) -> Callable[[str], np.ndarray]:
452    """
453    Create an embedder function using Ollama API.
454    
455    Args:
456        base_url: Ollama server URL
457        model: Model name for embeddings
458        
459    Returns:
460        Function that takes text and returns embedding vector
461    """
462    import requests
463    
464    def embed(text: str) -> np.ndarray:
465        response = requests.post(
466            f"{base_url}/api/embeddings",
467            json={"model": model, "prompt": text},
468            timeout=30
469        )
470        response.raise_for_status()
471        return np.array(response.json()["embedding"])
472    
473    return embed
474
475
476def create_openai_embedder(
477    model: str = "text-embedding-3-small"
478) -> Callable[[str], np.ndarray]:
479    """
480    Create an embedder function using OpenAI API.
481    
482    Requires OPENAI_API_KEY environment variable.
483    """
484    import openai
485    
486    client = openai.OpenAI()
487    
488    def embed(text: str) -> np.ndarray:
489        response = client.embeddings.create(
490            model=model,
491            input=text
492        )
493        return np.array(response.data[0].embedding)
494    
495    return embed
496
497
498# =============================================================================
499# TESTING
500# =============================================================================
501
502if __name__ == "__main__":
503    print("Rosetta Stone - Φ-Harmonic Compression")
504    print("=" * 50)
505    
506    # Test with synthetic embeddings (no external dependencies)
507    print("\nTesting with synthetic embeddings...")
508    
509    def synthetic_embedder(text: str) -> np.ndarray:
510        """Create deterministic pseudo-embeddings for testing."""
511        np.random.seed(hash(text) % (2**32))
512        return np.random.randn(384)  # Simulate 384-dim embeddings
513    
514    # Create test chunks
515    test_chunks = [
516        "The golden ratio φ appears in many natural phenomena.",
517        "AI systems can communicate through semantic compression.",
518        "The weather today is sunny with a chance of rain.",
519        "Spectral graph theory provides powerful analysis tools.",
520        "I had a sandwich for lunch yesterday.",
521        "Harmonic decomposition reveals hidden structure in data.",
522        "The cat sat on the mat.",
523        "Cross-model embedding alignment enables AI translation.",
524        "Random noise should be filtered out by compression.",
525        "φ-weighted filtering preserves semantic relationships.",
526    ]
527    
528    # Test PhiCompressor
529    compressor = PhiCompressor(synthetic_embedder, n_harmonics=5, verbose=True)
530    result = compressor.compress(test_chunks, target_ratio=0.5)
531    
532    print(f"\n{result.summary()}")
533    print(f"\nSelected indices: {result.selected_indices}")
534    print(f"Scores: {[f'{s:.3f}' for s in result.chunk_scores]}")
535    print(f"\nCompressed text:\n{result.compressed_text}")
536    
537    # Test baselines
538    print("\n" + "=" * 50)
539    print("Baseline comparisons:")
540    
541    for name, compressor_cls in [
542        ("Truncation", TruncationCompressor),
543        ("Random", RandomCompressor),
544        ("TF-IDF", TFIDFCompressor),
545    ]:
546        baseline = compressor_cls() if name != "Random" else compressor_cls(seed=42)
547        baseline_result = baseline.compress(test_chunks, target_ratio=0.5)
548        print(f"\n{name}: {baseline_result.summary()}")
549        print(f"  Selected: {baseline_result.selected_indices}")
550