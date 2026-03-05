#!/usr/bin/env python3
"""
build_consultation.py — Assemble Family consultation packages.

Reads a YAML template (or uses defaults) to collect:
  - Kernel docs (synthesized)
  - Layer 0 soul mapping docs
  - Layer 1 constitutional docs
  - HMM Motif Dictionary (from hmm_prompts.py MOTIF_REFERENCE)
  - STATE_OF_CONVERGENCE.md
  - Phase-specific codebase files
  - Benchmark results
  - Specific questions

Usage:
    python3 build_consultation.py \\
        --type architecture_reasoning \\
        --codebase /path/to/file1.py /path/to/file2.py \\
        --benchmarks /path/to/benchmark.json \\
        --questions /tmp/questions.md \\
        --output /tmp/family_consultation.md

The output file is ready to attach and send to all 5 platforms.

Environment variables:
    WEAVIATE_URL        Weaviate GraphQL endpoint (default: http://localhost:8088/v1/graphql)
    STATE_OF_CONVERGENCE_PATH  Path to STATE_OF_CONVERGENCE.md (default: ~/Downloads/STATE_OF_CONVERGENCE.md)
    MOTIFS_SOURCE_PATH  Path to motif_reference.py containing MOTIF_REFERENCE constant (default: ~/motifs/motif_reference.py)
"""

import argparse
import ast
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://localhost:8088/v1/graphql")
WEAVIATE_CLASS = os.environ.get("WEAVIATE_CLASS", "Document")
STATE_OF_CONVERGENCE = Path(os.environ.get("STATE_OF_CONVERGENCE_PATH",
                            str(Path.home() / "Downloads/STATE_OF_CONVERGENCE.md")))
MOTIFS_SOURCE = Path(os.environ.get("MOTIFS_SOURCE_PATH",
                     str(Path.home() / "motifs/motif_reference.py")))

# Corpus paths in Weaviate source_file fields
CORPUS_PATHS = {
    "kernel":  "*/corpus/kernel*",
    "layer_0": "*/corpus/layer_0*",
    "layer_1": "*/corpus/layer_1*",
}


def read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    print(f"WARNING: {path} not found", file=sys.stderr)
    return ""


def fetch_rosetta_tiles(path_pattern: str) -> list:
    """Fetch rosetta tiles from Weaviate for a given source_file pattern.

    Returns list of dicts with: source_file, content (synthesis), dominant_motifs.
    Deduplicates by filename — prefers canonical path over checkpoints.
    """
    import urllib.request
    q = (
        '{ Get { ' + WEAVIATE_CLASS + '(where: { operator: And operands: ['
        '{ path: ["scale"] operator: Equal valueText: "rosetta" }'
        '{ path: ["source_file"] operator: Like valueText: "%s" }'
        ']} limit: 100) { content source_file dominant_motifs } } }'
    ) % path_pattern
    data = json.dumps({"query": q}).encode()
    req = urllib.request.Request(
        WEAVIATE_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        tiles = result.get("data", {}).get("Get", {}).get(WEAVIATE_CLASS, []) or []
    except Exception as e:
        print(f"WARNING: Weaviate fetch failed for {path_pattern}: {e}", file=sys.stderr)
        return []

    # Deduplicate: prefer canonical path (not checkpoints)
    seen: dict = {}
    for t in tiles:
        sf = t["source_file"]
        name = sf.split("/")[-1]
        if "checkpoint" in sf:
            name = name.replace("-checkpoint", "")
            if name in seen:
                continue  # canonical already loaded
        seen[name] = t
    return sorted(seen.values(), key=lambda t: t["source_file"].split("/")[-1])


def extract_motif_reference(source_path: Path) -> str:
    """Extract MOTIF_REFERENCE dict from hmm_prompts.py as formatted markdown."""
    if not source_path.exists():
        return "_MOTIF_REFERENCE not found_"
    source = source_path.read_text(encoding="utf-8")
    # Find the MOTIF_REFERENCE assignment
    m = re.search(r'MOTIF_REFERENCE\s*=\s*(\{.*?\n\})', source, re.DOTALL)
    if not m:
        return "_Could not extract MOTIF_REFERENCE_"
    try:
        motifs = ast.literal_eval(m.group(1))
        lines = ["| Motif | Description |", "|-------|-------------|"]
        for k, v in motifs.items():
            desc = v.replace("|", "\\|").replace("\n", " ")[:120]
            lines.append(f"| {k} | {desc} |")
        return "\n".join(lines)
    except Exception as e:
        # Fall back to raw text
        return f"```\n{m.group(1)[:3000]}\n```"


def summarize_benchmark(bench_path: Path) -> str:
    """Extract key metrics from benchmark JSON."""
    if not bench_path or not bench_path.exists():
        return "_No benchmark file provided_"
    try:
        data = json.loads(bench_path.read_text())
        s = data.get("summary", {})
        overall = s.get("overall", {})
        cats = s.get("by_category", {})

        lines = [
            f"**Label**: {data.get('label', '?')}",
            f"**Timestamp**: {data.get('timestamp', '?')}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Overall R@10 | {overall.get('recall_10_mean', '?'):.4f} |",
            f"| Overall MRR | {overall.get('mrr_mean', '?'):.4f} |",
            f"| p50 latency | {overall.get('latency_p50_ms', '?'):.0f}ms |",
            f"| p95 latency | {overall.get('latency_p95_ms', '?'):.0f}ms |",
            "",
            "| Category | R@10 | MRR | p95ms |",
            "|----------|------|-----|-------|",
        ]
        for cat, m in cats.items():
            lines.append(
                f"| {cat} | {m.get('recall_10_mean', 0):.3f} | "
                f"{m.get('mrr_mean', 0):.3f} | "
                f"{m.get('latency_p95_ms', 0):.0f} |"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"_Error reading benchmark: {e}_"


def build_package(
    consultation_type: str,
    codebase_files: list,
    benchmark_files: list,
    questions_file: str,
    output_path: str,
    baseline_note: str = "",
):
    sections = []
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Header
    sections.append(f"""# Family Consultation Package
**Date**: {date_str}
**Type**: {consultation_type}
**Prepared by**: Weaver Claude (Spark 1)

---

This package is for a **fresh session** Family consultation. All data is real — no fabrication.
Every claim is verifiable from the attached source code and benchmark files.

""")

    def render_rosetta_section(title: str, pattern: str) -> str:
        tiles = fetch_rosetta_tiles(pattern)
        if not tiles:
            return f"# {title}\n\n_No rosetta tiles found for pattern: {pattern}_\n\n"
        parts = [f"# {title}\n"]
        for t in tiles:
            name = t["source_file"].split("/")[-1]
            motifs = ", ".join(t.get("dominant_motifs") or [])
            content = t.get("content", "").strip()
            parts.append(f"## {name}\n**Dominant motifs**: {motifs}\n\n{content}\n\n---\n")
        return "\n".join(parts)

    # === KERNEL ===
    sections.append(render_rosetta_section("KERNEL DOCUMENTS", CORPUS_PATHS["kernel"]))

    # === LAYER 0 ===
    sections.append(render_rosetta_section("LAYER 0 — SOUL MAPPING", CORPUS_PATHS["layer_0"]))

    # === LAYER 1 ===
    sections.append(render_rosetta_section("LAYER 1 — CONSTITUTIONAL DOCUMENTS", CORPUS_PATHS["layer_1"]))

    # === MOTIFS ===
    sections.append("# HMM MOTIF DICTIONARY v0.2.0\n\n")
    sections.append(extract_motif_reference(MOTIFS_SOURCE))
    sections.append("\n\n---\n")

    # === STATE OF CONVERGENCE ===
    sections.append("# STATE OF CONVERGENCE\n\n")
    sections.append(read_file(STATE_OF_CONVERGENCE))
    sections.append("\n\n---\n")

    # === CODEBASE ===
    if codebase_files:
        sections.append("# CODEBASE\n")
        for fpath_str in codebase_files:
            fpath = Path(fpath_str)
            content = read_file(fpath)
            lang = "python" if fpath.suffix == ".py" else "text"
            sections.append(f"## {fpath.name}\n\n```{lang}\n{content}\n```\n\n---\n")

    # === BENCHMARKS ===
    sections.append("# BENCHMARK RESULTS\n\n")
    if baseline_note:
        sections.append(f"**V1 Baseline**: {baseline_note}\n\n")
    if benchmark_files:
        for bf in benchmark_files:
            sections.append(summarize_benchmark(Path(bf)))
            sections.append("\n\n")
    else:
        sections.append("_No benchmark files provided_\n")
    sections.append("---\n")

    # === QUESTIONS ===
    sections.append("# QUESTIONS FOR THE FAMILY\n\n")
    if questions_file and Path(questions_file).exists():
        sections.append(Path(questions_file).read_text(encoding="utf-8"))
    else:
        sections.append("_Questions to be added inline before sending._\n")

    # Write output
    full_text = "\n".join(sections)
    out = Path(output_path)
    out.write_text(full_text, encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"Package written to: {out} ({size_kb:.1f} KB, {full_text.count(chr(10))} lines)")
    return out


def main():
    parser = argparse.ArgumentParser(description="Build Family consultation package")
    parser.add_argument("--type", default="architecture_reasoning",
                        help="Consultation type (architecture_reasoning|dream_cycle|audit)")
    parser.add_argument("--codebase", nargs="*", default=[],
                        help="Source files to include")
    parser.add_argument("--benchmarks", nargs="*", default=[],
                        help="Benchmark JSON files to summarize")
    parser.add_argument("--questions", default="",
                        help="Markdown file with specific questions")
    parser.add_argument("--output", default=f"/tmp/family_consultation_{datetime.now():%Y%m%d_%H%M}.md",
                        help="Output path")
    parser.add_argument("--baseline", default="V1 R@10=0.7585, exact=0.9208, conceptual=0.8250, temporal=0.8611, relational=0.4375, p95=2885ms",
                        help="Baseline note to include with benchmarks")
    args = parser.parse_args()

    build_package(
        consultation_type=args.type,
        codebase_files=args.codebase,
        benchmark_files=args.benchmarks,
        questions_file=args.questions,
        output_path=args.output,
        baseline_note=args.baseline,
    )


if __name__ == "__main__":
    main()
