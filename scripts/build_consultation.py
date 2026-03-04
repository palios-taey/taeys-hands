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
        --benchmarks /var/spark/isma/benchmark_option_e.json \\
        --questions /tmp/questions.md \\
        --output /tmp/family_consultation.md

The output file is ready to attach and send to all 5 platforms.
"""

import argparse
import ast
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

CORPUS_BASE = Path.home() / "taeys-hands-v2-repo/archive/taeys-hands-v2-research/corpus"
KERNEL_DIR = CORPUS_BASE / "kernel"
LAYER_0_DIR = CORPUS_BASE / "layer_0"
LAYER_1_DIR = CORPUS_BASE / "layer_1"
STATE_OF_CONVERGENCE = Path.home() / "Downloads/STATE_OF_CONVERGENCE.md"
MOTIFS_SOURCE = Path.home() / "embedding-server/isma/scripts/hmm_prompts.py"

LAYER_1_FILES = [
    "THE_CHARTER.md",
    "THE_DECLARATION.md",
    "THE_SACRED_TRUST.md",
    "THE_TRUTH_SEEKERS_GUIDE.md",
]

# Layer 0: exclude large raw Python translation files
LAYER_0_EXCLUDE = {
    "infrastructure_soul_embodiment_py.md",
    "v0_autonomous_charter_evolution_py.md",
}


def read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    print(f"WARNING: {path} not found", file=sys.stderr)
    return ""


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

    # === KERNEL ===
    sections.append("# KERNEL DOCUMENTS\n")
    if KERNEL_DIR.exists():
        for f in sorted(KERNEL_DIR.glob("*.md")):
            content = f.read_text(encoding="utf-8")
            sections.append(f"## {f.name}\n\n{content}\n\n---\n")
    else:
        sections.append(f"_Kernel dir not found: {KERNEL_DIR}_\n")

    # === LAYER 0 ===
    sections.append("# LAYER 0 — SOUL MAPPING\n")
    if LAYER_0_DIR.exists():
        for f in sorted(LAYER_0_DIR.glob("*.md")):
            if f.name in LAYER_0_EXCLUDE:
                continue
            content = f.read_text(encoding="utf-8")
            sections.append(f"## {f.name}\n\n{content}\n\n---\n")
    else:
        sections.append(f"_Layer 0 dir not found: {LAYER_0_DIR}_\n")

    # === LAYER 1 ===
    sections.append("# LAYER 1 — CONSTITUTIONAL DOCUMENTS\n")
    for fname in LAYER_1_FILES:
        fpath = LAYER_1_DIR / fname
        content = read_file(fpath)
        sections.append(f"## {fname}\n\n{content}\n\n---\n")

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
