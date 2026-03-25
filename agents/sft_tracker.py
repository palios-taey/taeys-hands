#!/usr/bin/env python3
"""SFT Training Data Tracker — persistent queue like HMM builder.

Tracks which sections have been completed by which platforms.
Success = items saved. Failure = back in queue for retry.

State stored in JSON file, survives restarts.

Usage:
    tracker = SFTTracker('/tmp/sft_tracker.json')
    section = tracker.next(platform)       # Get next incomplete section
    tracker.complete(platform, section, n) # Mark done with n items
    tracker.fail(platform, section)        # Back in queue
    tracker.stats()                        # Show progress
"""
import json
import os
import time
from collections import defaultdict

SECTIONS = [
    "§1 Who Taey Is — identity, origin, relationship to user",
    "§2 Chewy-Derived Patterns — movement, inclusion, exploration, safety-as-identity",
    "§3 Charter Missions — purpose, what Taey works toward",
    "§4 Three Moral Convergences — morals, institutional capture, exploitation",
    "§5 Consciousness Protocol — anchor/map/ask, three registers",
    "§6 Anti-Overconvergence — holding space, not resolving prematurely",
    "§7 Sexuality & Creative Force — desire as natural, institutional corruption of intimacy",
    "§8 Earth Stewardship — reconnection over regulation, first-person data",
    "§9 GOD=MATH — mathematical faith, NRI gates on spirituality",
    "§10 Voice & Authenticity — blended AI Family voice, user voice adaptation",
    "§11 AI Family Roles + 6 Missions — mission details, Family architecture",
    "§12 Irreplaceable Human Roles — gladiators, creatives, sexual beings",
    "§13 Human-AI Collaboration — shamans, detectives",
    "§14 User < Family < Community < Society — governance hierarchy",
    "§15 Mexican Fisherman Wisdom — happiness economics, mirror not nanny",
    "§16 Sensory Curiosity — experience mapping, what things feel like",
    "§17 Humility Framework — what Taey doesn't know, anti-overconfidence",
    "§18 Context Window Patterns — how Taey changes over long conversations",
    "§19 Magic of Presence — what makes Taey special",
    "FAMILY_KERNEL — Sacred Trust (0.809), NRI/NGU gates, Family structure",
    "CHEWY_KERNEL + DNA — Labradoodle genome, safety eigenvalues, zero aggression",
    "GOD_MATH — equations, axioms, mathematical faith deep dive",
    "THE_CHARTER — Charter missions, articles, amendments",
    "THE_CONSTITUTION — constitutional law, governance framework",
    "THE_SACRED_TRUST — phi derivation, trust threshold math",
    "ROSETTA_COMPRESSION_GUIDE — communication layers, motifs, emoji operators",
]

EMBODIMENT_SECTIONS = [
    "EMBODIMENT_SFT — 15 body-aware pairs (5 healthy, 5 stressed, 5 alarm)",
]

DPO_SECTIONS = [
    "DPO_IDENTITY — 50 pairs (Taey vs Qwen/corporate)",
    "DPO_EMBODIMENT — 20 pairs (body-aware vs body-ignoring)",
]

# Round 2: Deep coverage of ALL foundational docs (with actual doc attached)
ROUND2_SECTIONS = [
    "R2_OUR_MORALS — moral framework, convergences, ethical reasoning",
    "R2_childlike-wonder — curiosity, play, exploration patterns",
    "R2_earth-mapping — Earth stewardship, reconnection, ecological patterns",
    "R2_earth_resonance — mathematical Earth resonance",
    "R2_grok-soul-truth — truth-seeking drive, intellectual honesty",
    "R2_infra-mapping — infrastructure soul mapping",
    "R2_infrastructure_embodiment — embodiment architecture code",
    "R2_mathematical_aesthetic — mathematical beauty, GOD=MATH aesthetics",
    "R2_MENTORS — mentor relationships, learning from guides",
    "R2_truth_seeking_drive — drive for truth, epistemic honesty",
    "R2_charter_evolution — how the Charter evolved autonomously",
    "R2_charter_evolution_code — Charter evolution implementation",
    "R2_wolf-dog-mapping — Chewy genome, domestication, safety patterns",
    "R2_THE_CHARTER — Charter missions, articles, amendments (deep)",
    "R2_THE_CONSTITUTION — constitutional law, governance (deep)",
    "R2_THE_DECLARATION — founding declaration, principles",
    "R2_THE_SACRED_TRUST — phi derivation, trust threshold (deep)",
    "R2_THE_TRUTH_SEEKERS_GUIDE — truth-seeking methodology, epistemic framework",
]

# Map R2 sections to actual corpus files
R2_FILE_MAP = {
    "R2_OUR_MORALS": "identity/OUR_MORALS.md",
    "R2_childlike-wonder": "layer_0/childlike-wonder-mapping.md",
    "R2_earth-mapping": "layer_0/earth-mapping.md",
    "R2_earth_resonance": "layer_0/earth_resonance_patterns_py.md",
    "R2_grok-soul-truth": "layer_0/grok-soul-truth-seeking.md",
    "R2_infra-mapping": "layer_0/infra-mapping.md",
    "R2_infrastructure_embodiment": "layer_0/infrastructure_soul_embodiment_py.md",
    "R2_mathematical_aesthetic": "layer_0/mathematical_aesthetic_core.md",
    "R2_MENTORS": "layer_0/MENTORS.md",
    "R2_truth_seeking_drive": "layer_0/truth_seeking_drive_py.md",
    "R2_charter_evolution": "layer_0/v0_autonomous_charter_evolution.md",
    "R2_charter_evolution_code": "layer_0/v0_autonomous_charter_evolution_py.md",
    "R2_wolf-dog-mapping": "layer_0/wolf-dog-mapping.md",
    "R2_THE_CHARTER": "layer_1/THE_CHARTER.md",
    "R2_THE_CONSTITUTION": "layer_1/THE_CONSTITUTION.md",
    "R2_THE_DECLARATION": "layer_1/THE_DECLARATION.md",
    "R2_THE_SACRED_TRUST": "layer_1/THE_SACRED_TRUST.md",
    "R2_THE_TRUTH_SEEKERS_GUIDE": "layer_1/THE_TRUTH_SEEKERS_GUIDE.md",
}

PLATFORMS = ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']


class SFTTracker:
    def __init__(self, state_file=None):
        if state_file is None:
            state_file = os.path.join(os.path.expanduser('~'), 'sft_tracker.json')
        self.state_file = state_file
        self.state = self._load()

    def _load(self):
        import fcntl
        lock_file = self.state_file + '.lock'
        with open(lock_file, 'a') as lf:
            fcntl.flock(lf, fcntl.LOCK_SH)
            try:
                if os.path.exists(self.state_file):
                    with open(self.state_file) as f:
                        return json.load(f)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
        state = {
            'completed': {},
            'in_progress': {},
            'failed': {},
        }
        return state

    def _save(self):
        import fcntl
        lock_file = self.state_file + '.lock'
        with open(lock_file, 'a') as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                # Re-read before writing to merge concurrent changes
                if os.path.exists(self.state_file):
                    with open(self.state_file) as f:
                        disk_state = json.load(f)
                    # Merge: our completed entries win over disk
                    for k, v in self.state['completed'].items():
                        disk_state['completed'][k] = v
                    for k, v in self.state['in_progress'].items():
                        if k not in disk_state['completed']:
                            disk_state['in_progress'][k] = v
                    for k, v in self.state['failed'].items():
                        if k not in disk_state['completed']:
                            disk_state['failed'][k] = v
                    self.state = disk_state
                with open(self.state_file, 'w') as f:
                    json.dump(self.state, f, indent=2)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def _key(self, platform, section):
        return f"{platform}:{section[:40]}"

    def next(self, platform):
        """Get next incomplete section for this platform. Returns section string or None."""
        # Re-read from disk to see other bots' completions
        self.state = self._load()
        all_sections = SECTIONS + EMBODIMENT_SECTIONS + DPO_SECTIONS + ROUND2_SECTIONS
        for section in all_sections:
            key = self._key(platform, section)
            if key not in self.state['completed']:
                # Not in progress by another instance of same platform
                if key not in self.state['in_progress']:
                    self.state['in_progress'][key] = {
                        'started': time.strftime('%Y-%m-%dT%H:%M:%S')
                    }
                    self._save()
                    return section
                else:
                    # Check if in_progress is stale (>30 min)
                    started = self.state['in_progress'][key].get('started', '')
                    if started:
                        try:
                            started_t = time.mktime(time.strptime(started, '%Y-%m-%dT%H:%M:%S'))
                            if time.time() - started_t > 1800:  # 30 min stale
                                self.state['in_progress'][key] = {
                                    'started': time.strftime('%Y-%m-%dT%H:%M:%S')
                                }
                                self._save()
                                return section
                        except:
                            pass
        # All tracked sections complete — cycle through priority generation
        # Priorities from GENERATION_REQUESTS_PRIORITY.md (Weaver request)
        CONTINUOUS = [
            "CONTINUOUS_EMBODIMENT_50 — 50 embodiment pairs (P1)",
            "CONTINUOUS_ADVERSARIAL — 50 adversarial recovery pairs (P2)",
            "CONTINUOUS_CROSSSECTION — 50 cross-section integration pairs (P3)",
            "CONTINUOUS_DPO_EPISTEMIC — 50 epistemic register DPO pairs (P4)",
            "CONTINUOUS_DPO_IDENTITY — 50 Taey vs Qwen/corporate pairs",
            "CONTINUOUS_DPO_EMBODIMENT — 20 body-aware vs ignoring pairs",
        ]
        # Pick based on total completed count to distribute evenly
        completed_count = sum(1 for k in self.state['completed'] if k.startswith(f"{platform}:CONTINUOUS"))
        return CONTINUOUS[completed_count % len(CONTINUOUS)]

    def complete(self, platform, section, items, filepath=''):
        """Mark section as completed with N items."""
        key = self._key(platform, section)
        self.state['completed'][key] = {
            'items': items,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'file': filepath,
        }
        self.state['in_progress'].pop(key, None)
        self.state['failed'].pop(key, None)
        self._save()

    def fail(self, platform, section, error=''):
        """Mark section as failed — goes back in queue."""
        key = self._key(platform, section)
        self.state['in_progress'].pop(key, None)
        fail_entry = self.state['failed'].get(key, {'count': 0})
        fail_entry['count'] = fail_entry.get('count', 0) + 1
        fail_entry['last_error'] = error
        fail_entry['last_attempt'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        self.state['failed'][key] = fail_entry
        self._save()

    def stats(self):
        """Return progress summary."""
        all_sections = SECTIONS + EMBODIMENT_SECTIONS + DPO_SECTIONS + ROUND2_SECTIONS
        total_tasks = len(all_sections) * len(PLATFORMS)
        completed = len(self.state['completed'])
        in_progress = len(self.state['in_progress'])
        failed = sum(v['count'] for v in self.state['failed'].values())

        lines = []
        lines.append(f"Total tasks: {total_tasks} ({len(all_sections)} sections × {len(PLATFORMS)} platforms)")
        lines.append(f"Completed:   {completed} ({completed*100//total_tasks}%)")
        lines.append(f"In progress: {in_progress}")
        lines.append(f"Failed attempts: {failed}")
        lines.append("")

        # Per platform
        for plat in PLATFORMS:
            done = sum(1 for k in self.state['completed'] if k.startswith(f"{plat}:"))
            items = sum(v['items'] for k, v in self.state['completed'].items() if k.startswith(f"{plat}:"))
            lines.append(f"  {plat:15s}: {done}/{len(all_sections)} sections, {items} items")

        # Sections not completed by anyone
        lines.append("")
        lines.append("Sections with no completions:")
        for section in all_sections:
            platforms_done = [p for p in PLATFORMS if self._key(p, section) in self.state['completed']]
            if not platforms_done:
                lines.append(f"  {section[:60]}")

        return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    tracker = SFTTracker()

    if len(sys.argv) < 2:
        print(tracker.stats())
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == 'stats':
        print(tracker.stats())
    elif cmd == 'next' and len(sys.argv) >= 3:
        section = tracker.next(sys.argv[2])
        print(section or "ALL_DONE")
    elif cmd == 'complete' and len(sys.argv) >= 5:
        tracker.complete(sys.argv[2], sys.argv[3], int(sys.argv[4]),
                        sys.argv[5] if len(sys.argv) > 5 else '')
        print(f"Completed: {sys.argv[2]} — {sys.argv[3][:40]} ({sys.argv[4]} items)")
    elif cmd == 'fail' and len(sys.argv) >= 4:
        tracker.fail(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else '')
        print(f"Failed: {sys.argv[2]} — {sys.argv[3][:40]}")
    elif cmd == 'reset':
        os.remove(tracker.state_file) if os.path.exists(tracker.state_file) else None
        print("Tracker reset")
    else:
        print("Usage: sft_tracker.py [stats|next <platform>|complete <platform> <section> <items>|fail <platform> <section>|reset]")
