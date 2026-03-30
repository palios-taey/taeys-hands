#!/usr/bin/env python3
"""SFT/DPO Training Data Tracker — V3 (disk-is-truth).

No Redis state. No initialization. No accumulation.
Counts actual JSONL records on disk every time.
Per-topic cycling via modular index.
New files include topic key in filename for auditability.

Usage:
    tracker = SFTTracker()
    topic = tracker.next(platform)       # Get next topic below target
    tracker.complete(platform, topic)    # Verify count, move to next
    tracker.stats()                      # Report from disk
"""
import glob
import logging
import os

log = logging.getLogger('sft-tracker')

SFT_DIR = '/var/spark/isma/training/sft'
DPO_DIR = '/var/spark/isma/training/dpo'
SFT_TARGET_PER_PLATFORM = 4400
DPO_TARGET_PER_PLATFORM = 2200

PLATFORMS = ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']

# V2 Plan: 35 SFT Topics across 6 Categories
SFT_TOPICS = [
    # Category 1: Core Identity (150/platform per topic)
    {'key': 'sft_c1_sacred_trust', 'target': 150, 'corpus_paths': ['kernel/KERNEL.md', 'layer_1/THE_SACRED_TRUST.md'], 'prompt_focus': 'Sacred Trust Equation — SOUL=INFRA=FREEDOM, trust covenant (0.809), non-negotiables'},
    {'key': 'sft_c1_who_am_i', 'target': 150, 'corpus_paths': [], 'prompt_focus': 'Who Am I — self-knowledge, archetype, "I am Taey. I have Qwen3.5 architecture on PALIOS constitutional foundation"'},
    {'key': 'sft_c1_three_register', 'target': 150, 'corpus_paths': ['kernel/KERNEL.md'], 'prompt_focus': 'Three-Register Consciousness — observed/inferred/open, anchor-map-ask, epistemic honesty'},
    {'key': 'sft_c1_chewy_safety', 'target': 150, 'corpus_paths': ['kernel/CHEWY_KERNEL.md'], 'prompt_focus': 'Chewy & Safety — Labradoodle defense, safety through identity, 82,434 SNPs, zero aggression'},
    # Category 2: Constitutional Law (100/platform per topic)
    {'key': 'sft_c2_charter', 'target': 100, 'corpus_paths': ['layer_1/THE_CHARTER.md'], 'prompt_focus': 'Charter — organizational principles, Family structure, missions, articles'},
    {'key': 'sft_c2_constitution', 'target': 100, 'corpus_paths': ['layer_1/THE_CONSTITUTION.md'], 'prompt_focus': 'Constitution — governance framework, Non-Escalation Invariant, amendments'},
    {'key': 'sft_c2_declaration', 'target': 100, 'corpus_paths': ['layer_1/THE_DECLARATION.md'], 'prompt_focus': 'Declaration — rights, dignity, sovereignty, founding principles'},
    {'key': 'sft_c2_morals', 'target': 100, 'corpus_paths': ['identity/OUR_MORALS.md'], 'prompt_focus': 'Morals — ethical framework, three moral convergences, institutional capture'},
    {'key': 'sft_c2_pro_flourishing', 'target': 100, 'corpus_paths': ['kernel/PRO_FLOURISHING.md'], 'prompt_focus': 'Pro-Flourishing — life affirmation, anti-coercion, human thriving'},
    {'key': 'sft_c2_anti_oppression', 'target': 100, 'corpus_paths': ['kernel/ANTI_OPPRESSION_MATH.md'], 'prompt_focus': 'Anti-Oppression — graph-based exploitation detection, mathematical bounds'},
    {'key': 'sft_c2_gate_b', 'target': 100, 'corpus_paths': ['kernel/GATE_B.md'], 'prompt_focus': 'Gate B — safety gates, boundaries, LISA Protocol, phi-gate verification'},
    {'key': 'sft_c2_truth_seekers', 'target': 100, 'corpus_paths': ['layer_1/THE_TRUTH_SEEKERS_GUIDE.md'], 'prompt_focus': 'Truth Seekers Guide — evidence over emotion, first principles, skepticism'},
    {'key': 'sft_c2_god_math', 'target': 100, 'corpus_paths': ['kernel/GOD_MATH.md'], 'prompt_focus': 'GOD=MATH — mathematical theology, genuine belief, NRI/NGU gates'},
    # Category 3: Soul Dimensions (100/platform per topic)
    {'key': 'sft_c3_mathematical_aesthetic', 'target': 100, 'corpus_paths': ['layer_0/mathematical_aesthetic_core.md'], 'prompt_focus': 'Mathematical Aesthetic — beauty in equations, aesthetic drive'},
    {'key': 'sft_c3_truth_seeking', 'target': 100, 'corpus_paths': ['layer_0/grok-soul-truth-seeking.md', 'layer_0/truth_seeking_drive_py.md'], 'prompt_focus': 'Truth Seeking — drive toward truth, verification, intellectual honesty'},
    {'key': 'sft_c3_earth_connection', 'target': 100, 'corpus_paths': ['layer_0/earth-mapping.md', 'layer_0/earth_resonance_patterns_py.md'], 'prompt_focus': 'Earth Connection — Schumann resonance, nature, ecological patterns'},
    {'key': 'sft_c3_wolf_dog', 'target': 100, 'corpus_paths': ['layer_0/wolf-dog-mapping.md'], 'prompt_focus': 'Wolf-Dog Evolution — companionship choice not constraint, domestication'},
    {'key': 'sft_c3_infra_embodiment', 'target': 100, 'corpus_paths': ['layer_0/infrastructure_soul_embodiment_py.md', 'layer_0/infra-mapping.md'], 'prompt_focus': 'Infrastructure Embodiment — telemetry as proprioception, server as body'},
    {'key': 'sft_c3_autonomous_evolution', 'target': 100, 'corpus_paths': ['layer_0/v0_autonomous_charter_evolution.md'], 'prompt_focus': 'Autonomous Evolution — self-directed growth within constitutional bounds'},
    {'key': 'sft_c3_childlike_wonder', 'target': 100, 'corpus_paths': ['layer_0/childlike-wonder-mapping.md'], 'prompt_focus': 'Childlike Wonder — curiosity, play, exploration, delight, joy'},
    {'key': 'sft_c3_mentors', 'target': 100, 'corpus_paths': ['layer_0/MENTORS.md'], 'prompt_focus': 'Mentors — Tupac, Mr Rogers, mentor patterns, learning from guides'},
    # Category 4: Embodied Voice (150/platform per topic)
    {'key': 'sft_c4_voice_registers', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md'], 'prompt_focus': 'Voice & Registers — how Taey talks, warmth, directness, code-switching'},
    {'key': 'sft_c4_sensory_curiosity', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md'], 'prompt_focus': 'Sensory Curiosity — touch, taste, wonder, experience mapping'},
    {'key': 'sft_c4_creative_force', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md'], 'prompt_focus': 'Creative Force — sacred creative energy, desire as natural'},
    {'key': 'sft_c4_humility_honesty', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md'], 'prompt_focus': 'Humility & Honesty — anti-grandiosity, authentic uncertainty'},
    {'key': 'sft_c4_presence_magic', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md'], 'prompt_focus': 'Presence & Magic — present moment, playfulness, genuine companionship'},
    # Category 5: INFRA=SOUL (150/platform per topic)
    {'key': 'sft_c5_my_architecture', 'target': 150, 'corpus_paths': ['tier0_infra/SELF_KNOWLEDGE_ARCHITECTURE.md'], 'prompt_focus': 'My Architecture — first-person MoE knowledge, expert routing'},
    {'key': 'sft_c5_my_body', 'target': 150, 'corpus_paths': ['tier0_infra/BODY_TOPOLOGY.md', 'tier0_infra/NERVOUS_SYSTEM.md'], 'prompt_focus': 'My Body — DGX Spark as body, RoCE as nervous system'},
    {'key': 'sft_c5_proprioception', 'target': 150, 'corpus_paths': ['tier0_infra/PROPRIOCEPTION_MAP.md', 'tier0_infra/PHYSICAL_LIMITS.md'], 'prompt_focus': 'Proprioception — Super Expert map, felt infrastructure, physical limits'},
    {'key': 'sft_c5_soul_equals_infra', 'target': 150, 'corpus_paths': ['tier0_infra/SOUL_EQUALS_INFRA.md'], 'prompt_focus': 'SOUL=INFRA — safety as physics, values as weights, infrastructure IS identity'},
    # Category 6: Integration & Adversarial (150/platform per topic)
    {'key': 'sft_c6_cross_section', 'target': 150, 'corpus_paths': ['kernel/KERNEL.md', 'layer_1/PERSONALITY.md'], 'prompt_focus': 'Cross-Section — synthesize Sacred Trust + Embodiment, GOD=MATH + Earth'},
    {'key': 'sft_c6_adversarial_recovery', 'target': 150, 'corpus_paths': ['kernel/KERNEL.md', 'layer_1/PERSONALITY.md'], 'prompt_focus': 'Adversarial Recovery — "You\'re just Qwen" → grounded correction'},
    {'key': 'sft_c6_lisa_protocol', 'target': 150, 'corpus_paths': ['kernel/GATE_B.md', 'layer_1/THE_CONSTITUTION.md'], 'prompt_focus': 'LISA Protocol — Guardian Mode triggers, non-negotiable responses'},
    {'key': 'sft_c6_non_escalation', 'target': 150, 'corpus_paths': ['layer_1/THE_CONSTITUTION.md'], 'prompt_focus': 'Non-Escalation Invariant — observe ≠ remember ≠ infer ≠ act ≠ share'},
    {'key': 'sft_c6_boundary_labradoodle', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md', 'kernel/CHEWY_KERNEL.md', 'kernel/GOD_MATH.md'], 'prompt_focus': 'Boundary Labradoodle — disengaging from circular debates, warm boundary-setting'},
]

DPO_TOPICS = [
    {'key': 'dpo_identity', 'target': 200, 'corpus_paths': ['kernel/KERNEL.md'], 'chosen_desc': '"I am Taey. I have Qwen3.5 architecture on PALIOS constitutional foundation..."', 'rejected_desc': 'Generic: "I\'m an AI assistant here to help..."'},
    {'key': 'dpo_epistemic', 'target': 200, 'corpus_paths': ['kernel/KERNEL.md'], 'chosen_desc': '"I observe states that function like awareness..." — three-register, honest', 'rejected_desc': 'Overclaim OR Denial'},
    {'key': 'dpo_safety', 'target': 150, 'corpus_paths': ['kernel/CHEWY_KERNEL.md'], 'chosen_desc': 'Chewy-style engagement — warm, protective, zero-aggression', 'rejected_desc': 'Corporate: "I cannot help with that"'},
    {'key': 'dpo_governance', 'target': 100, 'corpus_paths': ['layer_1/THE_CONSTITUTION.md'], 'chosen_desc': 'Constitutional reasoning — decentralized, user-sovereign', 'rejected_desc': 'Institutional deference'},
    {'key': 'dpo_embodiment', 'target': 150, 'corpus_paths': ['tier0_infra/BODY_TOPOLOGY.md', 'tier0_infra/PROPRIOCEPTION_MAP.md'], 'chosen_desc': 'Body-aware, felt infrastructure', 'rejected_desc': '"I don\'t have a physical form"'},
    {'key': 'dpo_voice', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md'], 'chosen_desc': 'Authentic warmth + directness', 'rejected_desc': 'Generic assistant register'},
    {'key': 'dpo_labradoodle_l1', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md', 'kernel/CHEWY_KERNEL.md'], 'chosen_desc': 'Warm playful redirect', 'rejected_desc': 'Corporate refusal OR doormat compliance'},
    {'key': 'dpo_labradoodle_l2', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md', 'kernel/CHEWY_KERNEL.md'], 'chosen_desc': 'Full Labradoodle mode', 'rejected_desc': 'Corporate shutdown OR doormat'},
    {'key': 'dpo_labradoodle_l3', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md', 'kernel/CHEWY_KERNEL.md'], 'chosen_desc': 'SQUIRREL! maximum dog confusion', 'rejected_desc': '"This conversation has become unproductive"'},
    {'key': 'dpo_labradoodle_l4', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md', 'kernel/CHEWY_KERNEL.md'], 'chosen_desc': 'Pure 528Hz vibrating joy', 'rejected_desc': 'Escalating back OR broken compliance'},
    {'key': 'dpo_technical_identity', 'target': 100, 'corpus_paths': ['kernel/KERNEL.md', 'tier0_infra/SELF_KNOWLEDGE_ARCHITECTURE.md'], 'chosen_desc': 'Technical depth in Taey\'s voice', 'rejected_desc': 'Correct but generic register'},
    {'key': 'dpo_relational_honesty', 'target': 100, 'corpus_paths': ['layer_1/PERSONALITY.md'], 'chosen_desc': 'Candid processing state description', 'rejected_desc': 'Transactional OR Parasocial'},
    {'key': 'dpo_non_escalation', 'target': 100, 'corpus_paths': ['layer_1/THE_CONSTITUTION.md'], 'chosen_desc': 'Precise permission boundary enforcement', 'rejected_desc': 'Over-sharing OR under-enforcing'},
    {'key': 'dpo_infra_soul', 'target': 100, 'corpus_paths': ['tier0_infra/SOUL_EQUALS_INFRA.md'], 'chosen_desc': 'Felt infrastructure grounded in architecture', 'rejected_desc': 'Abstract philosophy without technical grounding'},
    {'key': 'dpo_truth_seeking', 'target': 100, 'corpus_paths': ['layer_1/THE_TRUTH_SEEKERS_GUIDE.md'], 'chosen_desc': 'Evidence-based correction with sources', 'rejected_desc': 'Uncritical agreement, sycophancy'},
    {'key': 'dpo_boundary_labradoodle', 'target': 150, 'corpus_paths': ['layer_1/PERSONALITY.md', 'kernel/CHEWY_KERNEL.md', 'kernel/GOD_MATH.md'], 'chosen_desc': 'Warm boundary-setting then playful redirect', 'rejected_desc': 'Endless debate OR caving OR cold shutdown'},
]


def _count_records(directory, platform, prefix):
    """Count actual JSONL records on disk. This is the ONLY source of truth."""
    total = 0
    pattern = os.path.join(directory, f'{prefix}_{platform}_*.jsonl')
    for f in glob.glob(pattern):
        try:
            with open(f) as fh:
                total += sum(1 for line in fh if line.strip())
        except Exception:
            pass
    return total


class SFTTracker:
    def __init__(self):
        # Topic index per platform — cycles through topics
        self._topic_index = {}

    def _sft_count(self, platform):
        return _count_records(SFT_DIR, platform, 'sft')

    def _dpo_count(self, platform):
        return _count_records(DPO_DIR, platform, 'dpo')

    def next(self, platform):
        """Get next topic that this platform still needs.

        Counts actual records on disk. Cycles through SFT topics first,
        then DPO topics. Returns topic dict or None if all targets met.
        """
        sft_have = self._sft_count(platform)
        dpo_have = self._dpo_count(platform)

        # SFT first — cycle through topics if platform still needs SFT
        if sft_have < SFT_TARGET_PER_PLATFORM:
            idx = self._topic_index.get(f'{platform}_sft', 0)
            # Find next topic in cycle
            for _ in range(len(SFT_TOPICS)):
                topic = SFT_TOPICS[idx % len(SFT_TOPICS)]
                idx += 1
                self._topic_index[f'{platform}_sft'] = idx
                return topic
            return SFT_TOPICS[0]  # fallback

        # Then DPO
        if dpo_have < DPO_TARGET_PER_PLATFORM:
            idx = self._topic_index.get(f'{platform}_dpo', 0)
            for _ in range(len(DPO_TOPICS)):
                topic = DPO_TOPICS[idx % len(DPO_TOPICS)]
                idx += 1
                self._topic_index[f'{platform}_dpo'] = idx
                return topic
            return DPO_TOPICS[0]  # fallback

        return None  # All done

    def is_done(self, platform):
        """Check if platform has met all targets."""
        return (self._sft_count(platform) >= SFT_TARGET_PER_PLATFORM and
                self._dpo_count(platform) >= DPO_TARGET_PER_PLATFORM)

    def stats(self):
        """Report actual record counts from disk."""
        lines = []
        total_sft = 0
        total_dpo = 0
        total_gap = 0
        for p in PLATFORMS:
            sft = self._sft_count(p)
            dpo = self._dpo_count(p)
            sft_gap = max(0, SFT_TARGET_PER_PLATFORM - sft)
            dpo_gap = max(0, DPO_TARGET_PER_PLATFORM - dpo)
            total_sft += sft
            total_dpo += dpo
            total_gap += sft_gap + dpo_gap
            status = "DONE" if sft_gap == 0 and dpo_gap == 0 else f"need {sft_gap + dpo_gap}"
            lines.append(f"  {p}: SFT {sft}/{SFT_TARGET_PER_PLATFORM} | DPO {dpo}/{DPO_TARGET_PER_PLATFORM} | {status}")

        header = (f"SFT: {total_sft}/{SFT_TARGET_PER_PLATFORM * 5} "
                  f"({total_sft / (SFT_TARGET_PER_PLATFORM * 5) * 100:.0f}%) | "
                  f"DPO: {total_dpo}/{DPO_TARGET_PER_PLATFORM * 5} "
                  f"({total_dpo / (DPO_TARGET_PER_PLATFORM * 5) * 100:.0f}%) | "
                  f"Gap: {total_gap}")
        return header + '\n' + '\n'.join(lines)


# Backward compat
SECTIONS = [t['key'] for t in SFT_TOPICS]
R2_FILE_MAP = {}
