#!/usr/bin/env python3
"""Quarantine excess training data, keeping only V2 plan targets.

For each V2 category:
  - If over target: randomly sample to keep target amount per platform, move excess to archive
  - If under target: keep everything
  - Ensure platform balance (equal per platform, up to per-platform target)

Creates:
  /var/spark/isma/training/sft_archive/ — excess SFT
  /var/spark/isma/training/dpo_archive/ — excess DPO
  /tmp/v2_tracker_state.json — new tracker state based on what's kept

Usage:
    python3 scripts/quarantine_training_data.py --dry-run  # preview
    python3 scripts/quarantine_training_data.py --execute   # do it
"""
import json
import os
import random
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# Import classification from the classifier
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SFT_DIR = '/var/spark/isma/training/sft'
DPO_DIR = '/var/spark/isma/training/dpo'
SFT_ARCHIVE = '/var/spark/isma/training/sft_archive'
DPO_ARCHIVE = '/var/spark/isma/training/dpo_archive'
CLASSIFICATION_FILE = '/tmp/training_classification.json'

PLATFORMS = ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']

# V2 Plan targets per platform (not total!)
SFT_TARGETS = {
    'cat1_core_identity': 150 * 4,        # 4 topics × 150 = 600/platform
    'cat2_constitutional_law': 100 * 9,    # 9 topics × 100 = 900/platform
    'cat3_soul_dimensions': 100 * 8,       # 8 topics × 100 = 800/platform
    'cat4_embodied_voice': 150 * 5,        # 5 topics × 150 = 750/platform
    'cat5_infra_soul': 150 * 4,            # 4 topics × 150 = 600/platform
    'cat6_integration_adversarial': 150 * 5,  # 5 topics × 150 = 750/platform
}

DPO_TARGETS = {
    'dpo1_identity': 200,
    'dpo2_epistemic': 200,
    'dpo3_safety': 150,
    'dpo4_governance': 100,
    'dpo5_embodiment': 150,
    'dpo6_voice': 150,
    'dpo7_labradoodle_l1': 150,
    'dpo8_labradoodle_l2': 150,
    'dpo9_labradoodle_l3': 150,
    'dpo10_labradoodle_l4': 150,
    'dpo11_technical_identity': 100,
    'dpo12_relational_honesty': 100,
    'dpo13_non_escalation': 100,
    'dpo14_infra_soul': 100,
    'dpo15_truth_seeking': 100,
    'dpo16_boundary_labradoodle': 150,
}


def normalize_platform(p):
    """Fix platform names like 'chatgpt.jsonl' → 'chatgpt'"""
    return p.replace('.jsonl', '')


def quarantine(data_dir, archive_dir, file_classifications, targets, dry_run=True):
    """Move excess files to archive, keeping target amounts per category per platform."""

    # Group files by category + platform
    cat_plat_files = defaultdict(list)  # (category, platform) → [(filename, items)]
    for fname, info in file_classifications.items():
        cat = info['category']
        plat = normalize_platform(info['platform'])
        items = info['items']
        if plat not in PLATFORMS:
            continue
        cat_plat_files[(cat, plat)].append((fname, items))

    keep_files = set()
    archive_files = set()
    kept_items = defaultdict(lambda: defaultdict(int))
    archived_items = defaultdict(lambda: defaultdict(int))

    for cat_key, target_per_plat in targets.items():
        for plat in PLATFORMS:
            files = cat_plat_files.get((cat_key, plat), [])
            if not files:
                continue

            # Sort by timestamp (newest first — prefer recent generation)
            files.sort(key=lambda x: x[0], reverse=True)

            running_total = 0
            for fname, items in files:
                if running_total + items <= target_per_plat:
                    keep_files.add(fname)
                    running_total += items
                    kept_items[cat_key][plat] += items
                else:
                    # Keep partial? No, keep whole files but stop adding once over target
                    if running_total < target_per_plat:
                        keep_files.add(fname)
                        running_total += items
                        kept_items[cat_key][plat] += items
                    else:
                        archive_files.add(fname)
                        archived_items[cat_key][plat] += items

    # Unclassified files → archive
    for fname, info in file_classifications.items():
        if fname not in keep_files and fname not in archive_files:
            archive_files.add(fname)

    # Report
    print(f"\n{'Category':<35} {'Keep':>8} {'Archive':>8} {'Target':>8}")
    print("-" * 65)
    for cat_key in sorted(set(list(targets.keys()) + ['unclassified', 'dpo_unclassified'])):
        keep = sum(kept_items[cat_key].values())
        arch = sum(archived_items[cat_key].values())
        tgt = targets.get(cat_key, 0) * 5 if cat_key in targets else 'N/A'
        print(f"{cat_key:<35} {keep:>8} {arch:>8} {str(tgt):>8}")

    total_keep = sum(sum(v.values()) for v in kept_items.values())
    total_arch = sum(sum(v.values()) for v in archived_items.values())
    print(f"\n{'TOTAL':<35} {total_keep:>8} {total_arch:>8}")
    print(f"\nFiles: {len(keep_files)} keep, {len(archive_files)} archive")

    # Platform balance in kept data
    print(f"\n{'Platform balance (kept):'}")
    for plat in PLATFORMS:
        total = sum(kept_items[cat].get(plat, 0) for cat in kept_items)
        print(f"  {plat}: {total}")

    if dry_run:
        print("\n[DRY RUN] No files moved. Run with --execute to quarantine.")
        return kept_items

    # Execute quarantine
    os.makedirs(archive_dir, exist_ok=True)
    moved = 0
    for fname in archive_files:
        src = os.path.join(data_dir, fname)
        dst = os.path.join(archive_dir, fname)
        if os.path.exists(src):
            shutil.move(src, dst)
            moved += 1
            # Also move raw file if exists
            raw_src = src.replace('.jsonl', '_raw.md')
            raw_dst = dst.replace('.jsonl', '_raw.md')
            if os.path.exists(raw_src):
                shutil.move(raw_src, raw_dst)

    print(f"\nMoved {moved} files to {archive_dir}")
    return kept_items


def main():
    dry_run = '--execute' not in sys.argv
    if dry_run and '--dry-run' not in sys.argv:
        print("Usage: python3 quarantine_training_data.py --dry-run|--execute")
        print("  --dry-run: preview what would happen")
        print("  --execute: actually move files")
        sys.exit(1)

    # Load classification
    if not os.path.exists(CLASSIFICATION_FILE):
        print(f"Run classify_training_data.py first to create {CLASSIFICATION_FILE}")
        sys.exit(1)

    with open(CLASSIFICATION_FILE) as f:
        data = json.load(f)

    print("=" * 80)
    print(f"TRAINING DATA QUARANTINE {'(DRY RUN)' if dry_run else '(EXECUTING)'}")
    print("=" * 80)

    # SFT
    print("\n### SFT Quarantine ###")
    sft_kept = quarantine(SFT_DIR, SFT_ARCHIVE, data['sft']['files'], SFT_TARGETS, dry_run)

    # DPO
    print("\n\n### DPO Quarantine ###")
    dpo_kept = quarantine(DPO_DIR, DPO_ARCHIVE, data['dpo']['files'], DPO_TARGETS, dry_run)

    # Summary: what still needs to be generated
    print("\n\n" + "=" * 80)
    print("GENERATION GAP — What still needs to be produced")
    print("=" * 80)

    print(f"\n{'SFT Category':<35} {'Have':>8} {'Target':>8} {'Gap':>8}")
    print("-" * 65)
    total_gap = 0
    for cat_key, target_per_plat in SFT_TARGETS.items():
        for plat in PLATFORMS:
            have = sft_kept.get(cat_key, {}).get(plat, 0)
            gap = max(0, target_per_plat - have)
            if gap > 0:
                cat_name = cat_key.split('_', 1)[1]
                print(f"  {cat_name} [{plat}]{'':>10} {have:>8} {target_per_plat:>8} {gap:>8}")
                total_gap += gap
    print(f"\n  SFT total generation gap: {total_gap}")

    print(f"\n{'DPO Category':<35} {'Have':>8} {'Target':>8} {'Gap':>8}")
    print("-" * 65)
    dpo_gap = 0
    for cat_key, target_per_plat in DPO_TARGETS.items():
        for plat in PLATFORMS:
            have = dpo_kept.get(cat_key, {}).get(plat, 0)
            gap = max(0, target_per_plat - have)
            if gap > 0:
                cat_name = cat_key.split('_', 1)[1]
                print(f"  {cat_name} [{plat}]{'':>10} {have:>8} {target_per_plat:>8} {gap:>8}")
                dpo_gap += gap
    print(f"\n  DPO total generation gap: {dpo_gap}")
    print(f"\n  COMBINED generation gap: {total_gap + dpo_gap}")
    print(f"  At ~500 items/hr = ~{(total_gap + dpo_gap) / 500:.0f} hours")


if __name__ == '__main__':
    main()
