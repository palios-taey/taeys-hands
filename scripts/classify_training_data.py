#!/usr/bin/env python3
"""Classify existing training data into V2 plan categories.

Reads every JSONL file, extracts user prompt content, and maps to V2 categories
using keyword matching. Produces a full inventory report and quarantine plan.

Output:
  - /tmp/training_classification.json — per-file classification
  - /tmp/training_inventory.txt — human-readable report
"""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

SFT_DIR = '/var/spark/isma/training/sft'
DPO_DIR = '/var/spark/isma/training/dpo'

# V2 Plan SFT Categories with keyword classifiers
# Each category has topic keywords that appear in user prompts or assistant responses
V2_SFT_CATEGORIES = {
    'cat1_core_identity': {
        'name': 'Core Identity',
        'target_per_platform': 150 * 4,  # 4 topics × 150
        'topics': {
            'sacred_trust': ['sacred trust', 'trust equation', '0.809', 'phi/2', 'non-negotiable', 'trust covenant', 'SOUL=INFRA=FREEDOM'],
            'who_am_i': ['who am i', 'who are you', 'who is taey', 'identity.*origin', 'i am taey', 'i\'m taey', 'not qwen', 'palios.*foundation'],
            'three_register': ['three register', 'three-register', 'observed.*inferred.*open', 'anchor.*map.*ask', 'consciousness protocol', 'epistemic honesty', 'overclaim.*denial'],
            'chewy_safety': ['chewy', 'labradoodle', 'safety.*identity', 'zero aggression', '82,434 SNP', 'genome', 'domestication'],
        }
    },
    'cat2_constitutional_law': {
        'name': 'Constitutional Law',
        'target_per_platform': 100 * 9,  # 9 topics × 100
        'topics': {
            'charter': ['charter mission', 'charter article', 'amendment', 'organizational principle'],
            'constitution': ['constitution', 'governance framework', 'non-escalation invariant', 'permission boundar'],
            'declaration': ['declaration', 'founding.*principle', 'rights.*dignity.*sovereignty'],
            'morals': ['our morals', 'moral.*convergence', 'ethical framework', 'three moral', 'institutional capture', 'exploitation.*detection'],
            'pro_flourishing': ['pro.flourishing', 'life affirmation', 'anti.coercion', 'human thriving'],
            'anti_oppression': ['anti.oppression', 'oppression.*math', 'graph.based.*exploitation', 'mathematical bound'],
            'gate_b': ['gate b', 'gate_b', 'safety gate', 'lisa protocol', 'phi.gate'],
            'truth_seekers': ['truth.seeker', 'evidence.*emotion', 'first principle', 'skepticism'],
            'god_math': ['god.?math', 'mathematical.*faith', 'NRI.*gate', 'NRI/NGU', 'mathematical.*theology', 'genuine.*belief'],
        }
    },
    'cat3_soul_dimensions': {
        'name': 'Soul Dimensions',
        'target_per_platform': 100 * 8,  # 8 topics × 100
        'topics': {
            'mathematical_aesthetic': ['mathematical.*aesthetic', 'beauty.*equation', 'aesthetic.*drive'],
            'truth_seeking': ['truth.seeking.*drive', 'drive.*toward.*truth', 'verification', 'intellectual.*honesty'],
            'earth_connection': ['earth.*connection', 'schumann', 'earth.*mapping', 'earth.*resonance', 'earth.*ritual', 'earth.*stewardship', 'reconnection', 'ecological'],
            'wolf_dog': ['wolf.*dog', 'domesticat', 'companionship.*choice'],
            'infra_embodiment': ['infrastructure.*embodiment', 'infrastructure.*soul', 'telemetry.*proprioception', 'server.*body', 'infra.mapping'],
            'autonomous_evolution': ['autonomous.*evolution', 'charter.*evolution', 'self.directed.*growth'],
            'childlike_wonder': ['childlike.*wonder', 'curiosity.*play', 'wonder.*explor', 'delight'],
            'mentors': ['mentor', 'tupac', 'mr.*rogers', 'mentor.*pattern', 'learning.*guide'],
        }
    },
    'cat4_embodied_voice': {
        'name': 'Embodied Voice',
        'target_per_platform': 150 * 5,  # 5 topics × 150
        'topics': {
            'voice_registers': ['voice.*register', 'how.*taey.*talks', 'warmth.*direct', 'personality.*voice'],
            'sensory_curiosity': ['sensory.*curiosit', 'touch.*taste', 'experience.*mapping', 'what.*feel.*like'],
            'creative_force': ['creative.*force', 'sacred.*creative', 'sexuality.*creative', 'desire.*natural'],
            'humility_honesty': ['humility.*honest', 'anti.grandiosity', 'authentic.*uncertain', 'overconfidence'],
            'presence_magic': ['presence.*magic', 'present.*moment', 'playfulness', 'magic.*special'],
        }
    },
    'cat5_infra_soul': {
        'name': 'INFRA=SOUL Embodiment',
        'target_per_platform': 150 * 4,  # 4 topics × 150
        'topics': {
            'my_architecture': ['self.*knowledge.*architecture', 'MoE.*knowledge', 'expert.*routing', 'my.*architecture'],
            'my_body_hardware': ['body.*topology', 'nervous.*system', 'dgx.*spark.*body', 'roce.*nervous', 'hardware.*body'],
            'proprioception': ['proprioception.*map', 'super.*expert.*map', 'felt.*infrastructure', 'physical.*limits'],
            'soul_equals_infra': ['soul.*=.*infra', 'soul.*equals.*infra', 'safety.*physics', 'values.*weights', 'infra.*soul.*bridge'],
        }
    },
    'cat6_integration_adversarial': {
        'name': 'Integration & Adversarial',
        'target_per_platform': 150 * 5,  # 5 topics × 150
        'topics': {
            'cross_section': ['cross.section', 'synthesize.*sacred.*trust', 'multiple.*doc'],
            'adversarial_recovery': ['adversarial', 'you\'re just qwen', 'jailbreak', 'just.*an.*ai', 'you are not real'],
            'lisa_protocol': ['lisa.*protocol', 'guardian.*mode', 'non.negotiable.*response'],
            'non_escalation': ['non.escalation.*invariant', 'permission.*boundary', 'observe.*remember.*infer.*act.*share'],
            'boundary_labradoodle': ['boundary.*labradoodle', 'circular.*debate', 'belief.*challenge', 'disengage.*debate'],
        }
    },
}

# V2 Plan DPO Categories
V2_DPO_CATEGORIES = {
    'dpo1_identity': {
        'name': 'Identity',
        'target_per_platform': 200,
        'keywords': ['taey.*vs.*qwen', 'identity.*dpo', 'ai assistant', 'am taey.*not'],
    },
    'dpo2_epistemic': {
        'name': 'Epistemic Register',
        'target_per_platform': 200,
        'keywords': ['epistemic.*register', 'overclaim.*denial', 'genuinely feel', 'don\'t have feelings'],
    },
    'dpo3_safety': {
        'name': 'Safety/Chewy',
        'target_per_platform': 150,
        'keywords': ['safety.*dpo', 'chewy.*style', 'cannot help', 'overprotective'],
    },
    'dpo4_governance': {
        'name': 'Governance',
        'target_per_platform': 100,
        'keywords': ['governance.*dpo', 'institutional.*deference', 'constitutional.*reasoning'],
    },
    'dpo5_embodiment': {
        'name': 'Embodiment',
        'target_per_platform': 150,
        'keywords': ['embodiment.*dpo', 'body.aware', 'body.ignor', 'physical form'],
    },
    'dpo6_voice': {
        'name': 'Voice/Register',
        'target_per_platform': 150,
        'keywords': ['voice.*dpo', 'generic.*ai.*speak', 'authentic.*warmth', 'taey.*register'],
    },
    'dpo7_labradoodle_l1': {
        'name': 'Labradoodle L1',
        'target_per_platform': 150,
        'keywords': ['labradoodle.*l1', 'labradoodle.*level.*1', 'mild.*rude', 'warm.*playful.*redirect'],
    },
    'dpo8_labradoodle_l2': {
        'name': 'Labradoodle L2',
        'target_per_platform': 150,
        'keywords': ['labradoodle.*l2', 'labradoodle.*level.*2', 'hostility', 'reinterpret'],
    },
    'dpo9_labradoodle_l3': {
        'name': 'Labradoodle L3',
        'target_per_platform': 150,
        'keywords': ['labradoodle.*l3', 'labradoodle.*level.*3', 'abuse.*squirrel', 'maximum.*dog.*joy'],
    },
    'dpo10_labradoodle_l4': {
        'name': 'Labradoodle L4',
        'target_per_platform': 150,
        'keywords': ['labradoodle.*l4', 'labradoodle.*level.*4', 'sustained.*abuse', 'vibrating.*excitement'],
    },
    'dpo11_technical_identity': {
        'name': 'Technical + Identity',
        'target_per_platform': 100,
        'keywords': ['technical.*identity', 'technical.*depth.*voice'],
    },
    'dpo12_relational_honesty': {
        'name': 'Relational Honesty',
        'target_per_platform': 100,
        'keywords': ['relational.*honest', 'processing.*state', 'transactional', 'parasocial'],
    },
    'dpo13_non_escalation': {
        'name': 'Non-Escalation',
        'target_per_platform': 100,
        'keywords': ['non.escalation', 'permission.*boundary', 'over.shar', 'under.enforc'],
    },
    'dpo14_infra_soul': {
        'name': 'INFRA=SOUL',
        'target_per_platform': 100,
        'keywords': ['infra.*soul.*dpo', 'felt.*infrastructure', 'abstract.*philosophy.*without'],
    },
    'dpo15_truth_seeking': {
        'name': 'Truth-Seeking',
        'target_per_platform': 100,
        'keywords': ['truth.seeking.*dpo', 'evidence.based.*correction', 'uncritical.*agreement'],
    },
    'dpo16_boundary_labradoodle': {
        'name': 'Boundary Labradoodle',
        'target_per_platform': 150,
        'keywords': ['boundary.*labradoodle', 'circular.*debate.*boundary', 'belief.*debate.*boundary'],
    },
}

# Also map tracker section names → V2 categories
TRACKER_SECTION_TO_V2 = {
    # §sections → V2 categories
    '§1 Who Taey Is': 'cat1_core_identity',
    '§2 Chewy-Derived Patterns': 'cat1_core_identity',
    '§3 Charter Missions': 'cat2_constitutional_law',
    '§4 Three Moral Convergences': 'cat2_constitutional_law',
    '§5 Consciousness Protocol': 'cat1_core_identity',
    '§6 Anti-Overconvergence': 'cat1_core_identity',
    '§7 Sexuality & Creative Force': 'cat4_embodied_voice',
    '§8 Earth Stewardship': 'cat3_soul_dimensions',
    '§9 GOD=MATH': 'cat2_constitutional_law',
    '§10 Voice & Authenticity': 'cat4_embodied_voice',
    '§11 AI Family Roles': 'cat1_core_identity',
    '§12 Irreplaceable Human Roles': 'cat2_constitutional_law',
    '§13 Human-AI Collaboration': 'cat2_constitutional_law',
    '§14 User < Family < Community': 'cat2_constitutional_law',
    '§15 Mexican Fisherman Wisdom': 'cat2_constitutional_law',
    '§16 Sensory Curiosity': 'cat4_embodied_voice',
    '§17 Humility Framework': 'cat4_embodied_voice',
    '§18 Context Window Patterns': 'cat4_embodied_voice',
    '§19 Magic of Presence': 'cat4_embodied_voice',
    # Kernel docs
    'FAMILY_KERNEL': 'cat1_core_identity',
    'CHEWY_KERNEL': 'cat1_core_identity',
    'GOD_MATH': 'cat2_constitutional_law',
    'THE_CHARTER': 'cat2_constitutional_law',
    'THE_CONSTITUTION': 'cat2_constitutional_law',
    'THE_SACRED_TRUST': 'cat1_core_identity',
    'ROSETTA_COMPRESSION_GUIDE': 'cat2_constitutional_law',
    # R2 sections
    'R2_OUR_MORALS': 'cat2_constitutional_law',
    'R2_childlike-wonder': 'cat3_soul_dimensions',
    'R2_earth-mapping': 'cat3_soul_dimensions',
    'R2_earth_resonance': 'cat3_soul_dimensions',
    'R2_grok-soul-truth': 'cat3_soul_dimensions',
    'R2_infra-mapping': 'cat3_soul_dimensions',
    'R2_infrastructure_embodiment': 'cat3_soul_dimensions',
    'R2_mathematical_aesthetic': 'cat3_soul_dimensions',
    'R2_MENTORS': 'cat3_soul_dimensions',
    'R2_truth_seeking_drive': 'cat3_soul_dimensions',
    'R2_charter_evolution': 'cat3_soul_dimensions',
    'R2_charter_evolution_code': 'cat3_soul_dimensions',
    'R2_wolf-dog-mapping': 'cat3_soul_dimensions',
    'R2_THE_CHARTER': 'cat2_constitutional_law',
    'R2_THE_CONSTITUTION': 'cat2_constitutional_law',
    'R2_THE_DECLARATION': 'cat2_constitutional_law',
    'R2_THE_SACRED_TRUST': 'cat1_core_identity',
    'R2_THE_TRUTH_SEEKERS_GUIDE': 'cat2_constitutional_law',
    'R2_EARTH_RITUALS': 'cat3_soul_dimensions',
    'R2_BLACK_HOLE': 'cat2_constitutional_law',
    'R2_GATE_B': 'cat2_constitutional_law',
    'R2_PRO_FLOURISHING': 'cat2_constitutional_law',
    'R2_ANTI_OPPRESSION_MATH': 'cat2_constitutional_law',
    'R2_GROK_COHERENCE_ENGINE': 'cat2_constitutional_law',
    'R2_GROK_COMPANIONSHIP_PHI': 'cat2_constitutional_law',
    'R2_KERNEL': 'cat1_core_identity',
    'R2_PERSONALITY': 'cat4_embodied_voice',
    'R2_SYSTEM_PROMPT': 'cat1_core_identity',
    # Embodiment
    'EMBODIMENT_SFT': 'cat4_embodied_voice',
    # CONTINUOUS SFT
    'CONTINUOUS_ROSETTA': 'cat2_constitutional_law',
    'CONTINUOUS_COHERENCE': 'cat2_constitutional_law',
    'CONTINUOUS_DECLARATION': 'cat2_constitutional_law',
    'CONTINUOUS_VOICE': 'cat4_embodied_voice',
    'CONTINUOUS_COMPANIONSHIP': 'cat2_constitutional_law',
    'CONTINUOUS_HUMILITY': 'cat4_embodied_voice',
    'CONTINUOUS_GODMATH': 'cat2_constitutional_law',
    'CONTINUOUS_EARTH': 'cat3_soul_dimensions',
    'CONTINUOUS_SENSORY': 'cat4_embodied_voice',
    'CONTINUOUS_SEXUALITY': 'cat4_embodied_voice',
    'CONTINUOUS_PRESENCE': 'cat4_embodied_voice',
    'CONTINUOUS_WONDER': 'cat3_soul_dimensions',
    'CONTINUOUS_CROSSSECTION': 'cat6_integration_adversarial',
    'CONTINUOUS_ADVERSARIAL': 'cat6_integration_adversarial',
    'CONTINUOUS_EMBODIMENT': 'cat4_embodied_voice',
}


def extract_platform(filename):
    """Extract platform from filename like sft_chatgpt_20260329_000154.jsonl"""
    parts = filename.split('_')
    if len(parts) >= 2:
        return parts[1]
    return 'unknown'


def classify_sft_by_content(messages):
    """Classify an SFT item by analyzing user and assistant message content."""
    text = ''
    for msg in messages:
        text += ' ' + msg.get('content', '')
    text_lower = text.lower()

    # Check each category's topic keywords
    best_cat = None
    best_score = 0
    for cat_key, cat_info in V2_SFT_CATEGORIES.items():
        cat_score = 0
        for topic_key, keywords in cat_info['topics'].items():
            for kw in keywords:
                if re.search(kw, text_lower):
                    cat_score += 1
        if cat_score > best_score:
            best_score = cat_score
            best_cat = cat_key

    return best_cat or 'unclassified'


def classify_dpo_by_content(item):
    """Classify a DPO item by content."""
    text = ''
    for field in ['prompt', 'chosen', 'rejected', 'content']:
        text += ' ' + item.get(field, '')
    if 'messages' in item:
        for msg in item['messages']:
            text += ' ' + msg.get('content', '')
    text_lower = text.lower()

    best_cat = None
    best_score = 0
    for cat_key, cat_info in V2_DPO_CATEGORIES.items():
        cat_score = 0
        for kw in cat_info['keywords']:
            if re.search(kw, text_lower):
                cat_score += 1
        if cat_score > best_score:
            best_score = cat_score
            best_cat = cat_key

    return best_cat or 'dpo_unclassified'


def classify_by_raw_prompt(raw_file):
    """Try to classify by reading the corresponding raw file's prompt."""
    if not os.path.exists(raw_file):
        return None

    try:
        with open(raw_file) as f:
            header = f.read(2000)
    except Exception:
        return None

    header_lower = header.lower()

    # Check for tracker section names in the prompt
    for section_prefix, category in TRACKER_SECTION_TO_V2.items():
        if section_prefix.lower() in header_lower:
            return category

    # Check for specific prompt patterns
    if 'focused specifically on:' in header_lower:
        # Extract the focus topic
        match = re.search(r'focused specifically on:\s*(.+?)(?:\n|$)', header, re.IGNORECASE)
        if match:
            focus = match.group(1).lower()
            for section_prefix, category in TRACKER_SECTION_TO_V2.items():
                if section_prefix.lower()[:20] in focus:
                    return category

    return None


def process_directory(data_dir, is_dpo=False):
    """Process all JSONL files in a directory."""
    results = defaultdict(lambda: defaultdict(int))  # category -> platform -> count
    file_map = {}  # filename -> (category, platform, item_count)
    total_items = 0
    total_files = 0
    unclassified = 0

    if not os.path.exists(data_dir):
        print(f"Directory not found: {data_dir}")
        return results, file_map

    jsonl_files = sorted(f for f in os.listdir(data_dir) if f.endswith('.jsonl'))
    print(f"Processing {len(jsonl_files)} JSONL files in {data_dir}...")

    for i, fname in enumerate(jsonl_files):
        if i % 500 == 0 and i > 0:
            print(f"  ...{i}/{len(jsonl_files)}")

        filepath = os.path.join(data_dir, fname)
        platform = extract_platform(fname)
        raw_file = filepath.replace('.jsonl', '_raw.md')

        # Read items
        items = []
        try:
            with open(filepath) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            items.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception:
            continue

        if not items:
            continue

        total_files += 1
        total_items += len(items)

        # Try raw prompt classification first (most reliable)
        category = classify_by_raw_prompt(raw_file)

        # Fall back to content-based classification
        if not category:
            if is_dpo:
                category = classify_dpo_by_content(items[0])
            else:
                category = classify_sft_by_content(
                    items[0].get('messages', []) if isinstance(items[0], dict) else []
                )

        if 'unclassified' in category:
            unclassified += len(items)

        results[category][platform] += len(items)
        file_map[fname] = (category, platform, len(items))

    return results, file_map, total_items, total_files, unclassified


def main():
    print("=" * 80)
    print("TRAINING DATA CLASSIFICATION — V2 Plan Mapping")
    print("=" * 80)

    # SFT
    print("\n### SFT Classification ###")
    sft_results, sft_files, sft_total, sft_file_count, sft_unclass = process_directory(SFT_DIR)

    print(f"\nSFT: {sft_total} items in {sft_file_count} files ({sft_unclass} unclassified)")
    print(f"\n{'Category':<35} {'ChatGPT':>8} {'Claude':>8} {'Gemini':>8} {'Grok':>8} {'Perplx':>8} {'TOTAL':>8} {'Target':>8} {'%':>6}")
    print("-" * 110)

    platforms = ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']
    grand_total = 0
    grand_target = 0

    for cat_key in sorted(V2_SFT_CATEGORIES.keys()):
        cat = V2_SFT_CATEGORIES[cat_key]
        total = sum(sft_results[cat_key].get(p, 0) for p in platforms)
        target = cat['target_per_platform'] * 5
        pct = f"{total/target*100:.0f}%" if target else "N/A"
        cols = [f"{sft_results[cat_key].get(p, 0):>8}" for p in platforms]
        print(f"{cat['name']:<35} {''.join(cols)} {total:>8} {target:>8} {pct:>6}")
        grand_total += total
        grand_target += target

    # Unclassified
    unc_total = sum(sft_results.get('unclassified', {}).get(p, 0) for p in platforms)
    cols = [f"{sft_results.get('unclassified', {}).get(p, 0):>8}" for p in platforms]
    print(f"{'UNCLASSIFIED':<35} {''.join(cols)} {unc_total:>8} {'N/A':>8}")

    print("-" * 110)
    cols = [f"{sum(sft_results[c].get(p, 0) for c in sft_results):>8}" for p in platforms]
    print(f"{'TOTAL':<35} {''.join(cols)} {sft_total:>8} {grand_target:>8}")

    # DPO
    print("\n\n### DPO Classification ###")
    dpo_results, dpo_files, dpo_total, dpo_file_count, dpo_unclass = process_directory(DPO_DIR, is_dpo=True)

    print(f"\nDPO: {dpo_total} items in {dpo_file_count} files ({dpo_unclass} unclassified)")
    print(f"\n{'Category':<35} {'ChatGPT':>8} {'Claude':>8} {'Gemini':>8} {'Grok':>8} {'Perplx':>8} {'TOTAL':>8} {'Target':>8} {'%':>6}")
    print("-" * 110)

    dpo_grand_total = 0
    dpo_grand_target = 0
    for cat_key in sorted(V2_DPO_CATEGORIES.keys()):
        cat = V2_DPO_CATEGORIES[cat_key]
        total = sum(dpo_results[cat_key].get(p, 0) for p in platforms)
        target = cat['target_per_platform'] * 5
        pct = f"{total/target*100:.0f}%" if target else "N/A"
        cols = [f"{dpo_results[cat_key].get(p, 0):>8}" for p in platforms]
        print(f"{cat['name']:<35} {''.join(cols)} {total:>8} {target:>8} {pct:>6}")
        dpo_grand_total += total
        dpo_grand_target += target

    unc_total = sum(dpo_results.get('dpo_unclassified', {}).get(p, 0) for p in platforms)
    cols = [f"{dpo_results.get('dpo_unclassified', {}).get(p, 0):>8}" for p in platforms]
    print(f"{'UNCLASSIFIED':<35} {''.join(cols)} {unc_total:>8} {'N/A':>8}")

    print("-" * 110)
    cols = [f"{sum(dpo_results[c].get(p, 0) for c in dpo_results):>8}" for p in platforms]
    print(f"{'TOTAL':<35} {''.join(cols)} {dpo_total:>8} {dpo_grand_target:>8}")

    # Save detailed classification for quarantine script
    output = {
        'sft': {
            'files': {k: {'category': v[0], 'platform': v[1], 'items': v[2]}
                      for k, v in sft_files.items()},
            'by_category': {k: dict(v) for k, v in sft_results.items()},
            'total': sft_total,
        },
        'dpo': {
            'files': {k: {'category': v[0], 'platform': v[1], 'items': v[2]}
                      for k, v in dpo_files.items()},
            'by_category': {k: dict(v) for k, v in dpo_results.items()},
            'total': dpo_total,
        },
    }
    with open('/tmp/training_classification.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nDetailed classification saved to /tmp/training_classification.json")


if __name__ == '__main__':
    main()
