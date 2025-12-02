1#!/usr/bin/env python3
2"""
3Rosetta Stone - Φ-Compression vs Baselines Comparison
4
5This script tests whether φ-harmonic compression produces better
6cross-model understanding than baseline methods.
7
8Test Protocol:
91. Load chunks from Weaviate (or test file)
102. Compress using each method to same ratio
113. Ask each AI Family member the same questions
124. Measure consistency and accuracy
13
14Usage:
15    # With Weaviate + Ollama
16    python test_phi_vs_baselines.py --weaviate-url http://localhost:8080 --ollama-url http://10.x.x.80:11435
17    
18    # With test file
19    python test_phi_vs_baselines.py --input-file test_chunks.txt
20    
21    # Dry run (synthetic embeddings)
22    python test_phi_vs_baselines.py --dry-run
23"""
24
25import argparse
26import json
27import time
28import sys
29from pathlib import Path
30from typing import List, Dict, Optional
31import numpy as np
32
33# Add parent to path for imports
34sys.path.insert(0, str(Path(__file__).parent.parent.parent))
35
36from rosetta_stone.core.compression import (
37    PhiCompressor, TruncationCompressor, RandomCompressor, TFIDFCompressor,
38    CompressionResult, create_ollama_embedder
39)
40from rosetta_stone.core.primitives import PHI, PHI_INVERSE
41
42
43def load_chunks_from_weaviate(
44    weaviate_url: str,
45    collection: str = "TranscriptEvent",
46    limit: int = 100
47) -> List[str]:
48    """Load text chunks from Weaviate."""
49    import weaviate
50    
51    client = weaviate.connect_to_local(host=weaviate_url.replace("http://", "").split(":")[0])
52    
53    try:
54        collection_obj = client.collections.get(collection)
55        results = collection_obj.query.fetch_objects(limit=limit)
56        
57        chunks = []
58        for obj in results.objects:
59            # Combine relevant text fields
60            text_parts = []
61            if hasattr(obj.properties, 'content') and obj.properties.get('content'):
62                text_parts.append(obj.properties['content'])
63            elif hasattr(obj.properties, 'text') and obj.properties.get('text'):
64                text_parts.append(obj.properties['text'])
65            elif hasattr(obj.properties, 'message') and obj.properties.get('message'):
66                text_parts.append(obj.properties['message'])
67            
68            if text_parts:
69                chunks.append(" ".join(text_parts))
70        
71        return chunks
72    finally:
73        client.close()
74
75
76def load_chunks_from_file(filepath: str) -> List[str]:
77    """Load chunks from a text file (one chunk per paragraph, separated by blank lines)."""
78    with open(filepath, 'r') as f:
79        content = f.read()
80    
81    # Split on double newlines
82    chunks = [c.strip() for c in content.split('\n\n') if c.strip()]
83    return chunks
84
85
86def create_synthetic_embedder(dim: int = 384) -> callable:
87    """Create deterministic pseudo-embeddings for testing."""
88    def embed(text: str) -> np.ndarray:
89        np.random.seed(hash(text) % (2**32))
90        return np.random.randn(dim)
91    return embed
92
93
94def run_compression_comparison(
95    chunks: List[str],
96    embedder: callable,
97    target_ratio: float = 0.3,
98    n_harmonics: int = 13
99) -> Dict[str, CompressionResult]:
100    """
101    Run all compression methods on the same chunks.
102    
103    Returns dict of method_name -> CompressionResult
104    """
105    results = {}
106    
107    # Φ-Harmonic compression
108    print("\n[1/4] Running Φ-Harmonic compression...")
109    phi_compressor = PhiCompressor(
110        embedder=embedder,
111        n_harmonics=n_harmonics,
112        verbose=True
113    )
114    results["phi_harmonic"] = phi_compressor.compress(chunks, target_ratio)
115    
116    # Truncation baseline
117    print("\n[2/4] Running Truncation baseline...")
118    truncation = TruncationCompressor()
119    results["truncation"] = truncation.compress(chunks, target_ratio)
120    
121    # Random baseline
122    print("\n[3/4] Running Random baseline...")
123    random_comp = RandomCompressor(seed=42)
124    results["random"] = random_comp.compress(chunks, target_ratio)
125    
126    # TF-IDF baseline
127    print("\n[4/4] Running TF-IDF baseline...")
128    tfidf = TFIDFCompressor()
129    results["tfidf"] = tfidf.compress(chunks, target_ratio)
130    
131    return results
132
133
134def compute_overlap_metrics(results: Dict[str, CompressionResult]) -> Dict:
135    """
136    Compute overlap between different compression methods.
137    
138    If methods agree on which chunks are important, they're capturing
139    similar semantic structure.
140    """
141    metrics = {}
142    
143    methods = list(results.keys())
144    for i, m1 in enumerate(methods):
145        for m2 in methods[i+1:]:
146            set1 = set(results[m1].selected_indices)
147            set2 = set(results[m2].selected_indices)
148            
149            intersection = len(set1 & set2)
150            union = len(set1 | set2)
151            jaccard = intersection / union if union > 0 else 0
152            
153            metrics[f"{m1}_vs_{m2}"] = {
154                "jaccard": jaccard,
155                "intersection": intersection,
156                "union": union
157            }
158    
159    return metrics
160
161
162def print_comparison_report(
163    results: Dict[str, CompressionResult],
164    overlap_metrics: Dict,
165    chunks: List[str]
166):
167    """Print a formatted comparison report."""
168    print("\n" + "=" * 70)
169    print("Φ-COMPRESSION VS BASELINES COMPARISON")
170    print("=" * 70)
171    
172    # Summary table
173    print("\n### Method Summary ###\n")
174    print(f"{'Method':<15} {'Selected':<10} {'Time (s)':<10} {'Top Score':<10}")
175    print("-" * 45)
176    for name, result in results.items():
177        print(f"{name:<15} {result.n_selected:<10} {result.processing_time:<10.3f} {result.chunk_scores.max():<10.3f}")
178    
179    # Overlap analysis
180    print("\n### Overlap Analysis ###\n")
181    print("Jaccard similarity between methods (1.0 = identical selection):\n")
182    for pair, metrics in overlap_metrics.items():
183        print(f"  {pair}: {metrics['jaccard']:.3f} ({metrics['intersection']}/{metrics['union']} chunks)")
184    
185    # Φ-Harmonic specific stats
186    phi_result = results.get("phi_harmonic")
187    if phi_result and phi_result.harmonic_stats:
188        print("\n### Φ-Harmonic Analysis ###\n")
189        stats = phi_result.harmonic_stats
190        print(f"  Harmonics used: {stats.get('n_harmonics_used', 'N/A')}")
191        print(f"  Spectral gap: {stats.get('spectral_gap', 0):.4f}")
192        print(f"  Score range: [{stats.get('score_range', (0,0))[0]:.3f}, {stats.get('score_range', (0,0))[1]:.3f}]")
193        print(f"  Score threshold: {stats.get('threshold_used', 0):.3f}")
194    
195    # Show unique selections by Φ-Harmonic
196    phi_indices = set(results["phi_harmonic"].selected_indices)
197    other_indices = set()
198    for name, result in results.items():
199        if name != "phi_harmonic":
200            other_indices.update(result.selected_indices)
201    
202    unique_phi = phi_indices - other_indices
203    if unique_phi:
204        print("\n### Unique Φ-Harmonic Selections ###")
205        print("(Chunks selected by Φ-Harmonic but no baseline)\n")
206        for idx in sorted(unique_phi)[:3]:  # Show first 3
207            chunk = chunks[idx][:100] + "..." if len(chunks[idx]) > 100 else chunks[idx]
208            print(f"  [{idx}] {chunk}")
209    
210    # Show what Φ-Harmonic rejected that others kept
211    missed_by_phi = other_indices - phi_indices
212    if missed_by_phi:
213        print("\n### Rejected by Φ-Harmonic ###")
214        print("(Chunks kept by baselines but rejected by Φ-Harmonic)\n")
215        for idx in sorted(missed_by_phi)[:3]:
216            chunk = chunks[idx][:100] + "..." if len(chunks[idx]) > 100 else chunks[idx]
217            score = results["phi_harmonic"].chunk_scores[idx]
218            print(f"  [{idx}] (score={score:.3f}) {chunk}")
219
220
221def save_results(
222    results: Dict[str, CompressionResult],
223    output_dir: str = "compression_results"
224):
225    """Save compression results to files for further analysis."""
226    output_path = Path(output_dir)
227    output_path.mkdir(exist_ok=True)
228    
229    for name, result in results.items():
230        # Save compressed text
231        with open(output_path / f"{name}_compressed.txt", 'w') as f:
232            f.write(result.compressed_text)
233        
234        # Save metadata
235        metadata = {
236            "method": name,
237            "n_original": result.n_original,
238            "n_selected": result.n_selected,
239            "compression_ratio": result.compression_ratio,
240            "processing_time": result.processing_time,
241            "selected_indices": result.selected_indices,
242            "harmonic_stats": result.harmonic_stats
243        }
244        with open(output_path / f"{name}_metadata.json", 'w') as f:
245            json.dump(metadata, f, indent=2)
246    
247    print(f"\nResults saved to {output_path}/")
248
249
250def main():
251    parser = argparse.ArgumentParser(description="Compare Φ-compression vs baselines")
252    
253    # Input options
254    input_group = parser.add_mutually_exclusive_group(required=True)
255    input_group.add_argument("--weaviate-url", help="Weaviate server URL")
256    input_group.add_argument("--input-file", help="Input file with chunks")
257    input_group.add_argument("--dry-run", action="store_true", help="Use synthetic test data")
258    
259    # Embedding options
260    parser.add_argument("--ollama-url", default="http://10.x.x.80:11435",
261                        help="Ollama server URL for embeddings")
262    parser.add_argument("--embedding-model", default="qwen3-embedding:8b",
263                        help="Embedding model name")
264    parser.add_argument("--use-synthetic-embeddings", action="store_true",
265                        help="Use synthetic embeddings (no external API)")
266    
267    # Compression options
268    parser.add_argument("--target-ratio", type=float, default=0.3,
269                        help="Target compression ratio (default: 0.3)")
270    parser.add_argument("--n-harmonics", type=int, default=13,
271                        help="Number of harmonics for Φ-compression (default: 13)")
272    parser.add_argument("--limit", type=int, default=100,
273                        help="Max chunks to load from Weaviate")
274    
275    # Output options
276    parser.add_argument("--output-dir", default="compression_results",
277                        help="Directory to save results")
278    parser.add_argument("--save", action="store_true",
279                        help="Save compressed results to files")
280    
281    args = parser.parse_args()
282    
283    # Load chunks
284    print("Loading chunks...")
285    if args.dry_run:
286        chunks = [
287            "The golden ratio φ appears in many natural phenomena and mathematical structures.",
288            "AI systems can communicate through semantic compression and embedding translation.",
289            "The weather today is sunny with a chance of rain in the afternoon.",
290            "Spectral graph theory provides powerful tools for analyzing network structure.",
291            "I had a delicious sandwich for lunch yesterday at the cafe.",
292            "Harmonic decomposition reveals hidden patterns in complex data.",
293            "The cat sat on the mat and looked out the window.",
294            "Cross-model embedding alignment enables AI-to-AI translation protocols.",
295            "Random noise should be filtered out by intelligent compression algorithms.",
296            "φ-weighted filtering preserves the most important semantic relationships.",
297            "The Rosetta Stone framework tests whether AI consciousness can emerge.",
298            "Three AI systems independently converged on the same mathematical structure.",
299            "Compression-as-translation means that meaning survives format changes.",
300            "The spectral gap of a graph indicates its connectivity properties.",
301            "Bach's music demonstrates optimal harmonic patterns for information encoding.",
302        ]
303        print(f"  Using {len(chunks)} synthetic test chunks")
304    elif args.input_file:
305        chunks = load_chunks_from_file(args.input_file)
306        print(f"  Loaded {len(chunks)} chunks from {args.input_file}")
307    else:
308        chunks = load_chunks_from_weaviate(args.weaviate_url, limit=args.limit)
309        print(f"  Loaded {len(chunks)} chunks from Weaviate")
310    
311    if len(chunks) < 5:
312        print("Error: Need at least 5 chunks for meaningful compression")
313        return 1
314    
315    # Create embedder
316    if args.use_synthetic_embeddings or args.dry_run:
317        print("Using synthetic embeddings (deterministic, no API calls)")
318        embedder = create_synthetic_embedder()
319    else:
320        print(f"Using Ollama embeddings from {args.ollama_url}")
321        embedder = create_ollama_embedder(args.ollama_url, args.embedding_model)
322    
323    # Run comparison
324    print(f"\nCompressing {len(chunks)} chunks to {args.target_ratio:.0%}...")
325    results = run_compression_comparison(
326        chunks=chunks,
327        embedder=embedder,
328        target_ratio=args.target_ratio,
329        n_harmonics=args.n_harmonics
330    )
331    
332    # Analyze overlap
333    overlap_metrics = compute_overlap_metrics(results)
334    
335    # Print report
336    print_comparison_report(results, overlap_metrics, chunks)
337    
338    # Save if requested
339    if args.save:
340        save_results(results, args.output_dir)
341    
342    return 0
343
344
345if __name__ == "__main__":
346    exit(main())
347