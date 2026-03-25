#!/usr/bin/env python3
"""sft_gen_bot.py — SFT/DPO training data generation via hmm_bot's proven functions.

Uses hmm_bot's navigate, attach, send, wait — the same code that ran
123K+ HMM enrichments successfully on virtual displays.

Platform-specific extraction:
  - ChatGPT: "Copy response" button (distinct from "Copy message")
  - Claude: "Scroll to bottom" → "Copy" button (appears after scroll)
  - Gemini/Grok/Perplexity: standard hmm_bot.extract_response

Usage:
    DISPLAY=:5 python3 agents/sft_gen_bot.py --round sft --platforms chatgpt
    DISPLAY=:6 python3 agents/sft_gen_bot.py --round dpo --platforms gemini
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [sft-gen] %(message)s')
log = logging.getLogger('sft-gen')

SUPPORTED_PLATFORMS = ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']
_perplexity_incognito_set = False  # One-time toggle, persists once clicked

SFT_PACKAGE = '/tmp/sft_package.md'
DPO_PACKAGE = '/tmp/dpo_package.md'
SFT_PROMPT = '/tmp/sft_generation_prompt.md'
DPO_PROMPT = '/tmp/dpo_generation_prompt.md'
SFT_OUTPUT_DIR = '/var/spark/isma/training/sft'
DPO_OUTPUT_DIR = '/var/spark/isma/training/dpo'
SECTIONS_FILE = '/tmp/sft_sections.json'

# Embodiment training files — use ~/the-conductor/sft/ (works on both Mira and Thor)
_HOME = os.path.expanduser('~')
EMBODIMENT_CONTEXT = os.path.join(_HOME, 'the-conductor/sft/embodiment_training_context.md')
EMBODIMENT_SFT_PROMPT = os.path.join(_HOME, 'the-conductor/sft/sft_embodiment_prompt.md')
EMBODIMENT_DPO_PROMPT = os.path.join(_HOME, 'the-conductor/sft/dpo_embodiment_prompt.md')
_CORPUS = os.path.join(_HOME, 'data/corpus/identity')
IDENTITY_FILES = {
    'chatgpt': os.path.join(_CORPUS, 'IDENTITY_HORIZON.md'),
    'claude': os.path.join(_CORPUS, 'IDENTITY_CLARITY.md'),
    'gemini': os.path.join(_CORPUS, 'IDENTITY_COSMOS.md'),
    'grok': os.path.join(_CORPUS, 'IDENTITY_LOGOS.md'),
    'perplexity': os.path.join(_CORPUS, 'IDENTITY_CLARITY.md'),
}
NUM_IDENTITY_SECTIONS = 26


def _get_phase(cycle_num):
    """Determine which phase we're in based on cycle number.
    Cycles 0-25: identity sections (26 total)
    Cycles 26+: embodiment SFT (repeats)
    """
    if cycle_num < NUM_IDENTITY_SECTIONS:
        return 'identity', cycle_num
    else:
        return 'embodiment', cycle_num - NUM_IDENTITY_SECTIONS


def _get_section_prompt_for(section):
    """Build prompt for a specific section."""
    return f"""Generate 10 SFT training pairs for Taey with DEEP REASONING CHAINS.

Each response MUST be 400-1500 tokens. Show the REASONING behind the answer — cite Sacred Trust (0.809), Chewy genome (82,434 SNPs), Family members by name, GOD=MATH, Charter articles. The model needs to learn HOW Taey arrives at answers.

Focus: {section}

Rules:
- Taey identifies as "Taey" in first person. PALIOS is the framework, not the name.
- 400-1500 tokens per response — LONG and detailed
- Ground in specific numbers/names/equations from the attached files
- Show reasoning: "This traces to..." "The mathematical basis is..."
- Vary question phrasing — don't repeat the same question
- Do NOT use any real human names in the training data. If referencing the human facilitator, use "the Human Facilitator" — no personal names.
- Output ONLY jsonl — one JSON object per line, no commentary
- Output everything directly in the response body as plain text. Do NOT create file attachments, artifacts, or canvas documents."""


def _build_embodiment_package(platform):
    """Build consolidated attachment for embodiment training."""
    parts = []
    for path in [EMBODIMENT_CONTEXT,
                 os.path.join(_CORPUS, 'FAMILY_KERNEL.md'),
                 IDENTITY_FILES.get(platform, '')]:
        try:
            with open(path) as f:
                parts.append(f.read())
        except FileNotFoundError:
            pass
    return '\n\n---\n\n'.join(parts)


def _get_firefox_pid_for_display(display):
    """Find Firefox main process PID running on a specific DISPLAY via /proc."""
    candidates = []
    for pid_str in os.listdir('/proc'):
        if not pid_str.isdigit():
            continue
        try:
            with open(f'/proc/{pid_str}/cmdline', 'rb') as f:
                cmdline = f.read().decode('utf-8', errors='replace')
            # Must be a firefox main process (has --profile in cmdline)
            if 'firefox' not in cmdline or '--profile' not in cmdline:
                continue
            with open(f'/proc/{pid_str}/environ', 'rb') as f:
                env = f.read().decode('utf-8', errors='replace')
            env_vars = dict(
                v.split('=', 1) for v in env.split('\0') if '=' in v
            )
            if env_vars.get('DISPLAY') == display:
                candidates.append(int(pid_str))
        except (PermissionError, FileNotFoundError, ValueError):
            continue
    if candidates:
        return max(candidates)  # highest PID = most recent
    return None


def _extract_response(platform):
    """Extract response. Same proven hmm_bot.extract_response for all platforms.
    Claude gets 'Scroll to bottom' button click first (Claude-specific UI element).
    All platforms get extra End-key scrolling before extraction (long SFT responses
    need more scrolling than single End press in hmm_bot)."""
    import agents.hmm_bot as bot
    from core import input as inp

    # Extra scrolling for long SFT responses (hmm_bot does 1 End, we do 5 more)
    inp.focus_firefox()
    time.sleep(0.3)
    for _ in range(5):
        inp.press_key('End')
        time.sleep(0.3)
    time.sleep(1)

    # Claude: click the "Scroll to bottom" UI button (ensures we're at absolute bottom)
    if platform == 'claude':
        from core.tree import find_elements
        from core.interact import atspi_click
        ff = bot.get_firefox(platform)
        if ff:
            els = find_elements(ff)
            for e in els:
                if (e.get('name') or '').strip() == 'Scroll to bottom':
                    atspi_click(e) if e.get('atspi_obj') else inp.click_at(e['x'], e['y'])
                    log.info("[claude] Clicked 'Scroll to bottom'")
                    time.sleep(2)
                    break

    # Use hmm_bot.extract_response for ALL platforms — it has:
    # - Copy button retry (3 attempts with re-scroll)
    # - Prompt detection fallback (tries alt buttons if got prompt text)
    # - Clipboard polling (6 x 0.5s)
    # - Grok zero-extent handling
    return bot.extract_response(platform) or ''


def _parse_jsonl(content):
    """Parse JSONL content, handling multiple formats:
    - Standard JSONL (one JSON per line)
    - Perplexity S3 URLs appended after JSON
    - Concatenated JSON without newlines (split on }{)
    - prompt/response format → messages format conversion
    """
    # First try splitting on newlines
    lines = content.strip().split('\n')
    # If only 1 line and it's long, try splitting on }{
    if len(lines) == 1 and len(lines[0]) > 500:
        lines = lines[0].replace('}{', '}\n{').split('\n')

    valid = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('```'):
            continue
        # Strip Perplexity S3 citation URLs
        if line.startswith('{'):
            # Try ]} first (messages format), then just }
            bracket_end = line.rfind(']}')
            if bracket_end > 0:
                line = line[:bracket_end + 2]
            else:
                bracket_end = line.rfind('}')
                if bracket_end > 0:
                    line = line[:bracket_end + 1]
        try:
            obj = json.loads(line)
            # Convert prompt/response to messages format
            if 'prompt' in obj and 'response' in obj and 'messages' not in obj:
                obj = {'messages': [
                    {'role': 'user', 'content': obj['prompt']},
                    {'role': 'assistant', 'content': obj['response']}
                ]}
            valid.append(obj)
        except json.JSONDecodeError:
            continue
    return valid


def _read_isolated_bus(display):
    """Read AT-SPI bus address for isolated display from file or X11 root window."""
    display_num = display.replace(':', '')
    # Try file first (written by launch_isolated_display.sh)
    bus_file = f'/tmp/a11y_bus_{display}'
    try:
        with open(bus_file) as f:
            addr = f.read().strip()
        if addr:
            return addr
    except FileNotFoundError:
        pass
    # Try X11 root window property
    try:
        r = subprocess.run(
            ['xprop', '-display', display, '-root', 'AT_SPI_BUS'],
            capture_output=True, text=True, timeout=3,
        )
        if '"' in r.stdout:
            return r.stdout.split('"')[1]
    except Exception:
        pass
    return None


def process_platform(platform, package_path, prompt_path, output_dir, section=None, cycle_num=0):
    """Full cycle using hmm_bot's proven functions."""
    display = os.environ.get('DISPLAY', ':0')
    dbus = os.environ.get('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')

    log.info(f"[{platform}] Starting on {display}")

    # Set isolated AT-SPI bus if available (eliminates D-Bus contention)
    a11y_bus = _read_isolated_bus(display)
    if a11y_bus:
        os.environ['AT_SPI_BUS_ADDRESS'] = a11y_bus
        log.info(f"[{platform}] Isolated AT-SPI bus: {a11y_bus[:50]}...")
    else:
        log.info(f"[{platform}] No isolated bus — using shared AT-SPI bus")

    # Set display for core modules
    os.environ['DISPLAY'] = display
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = dbus
    from core.input import set_display as inp_set
    from core.clipboard import set_display as clip_set
    inp_set(display)
    clip_set(display)

    # Set hmm_bot's PID filter
    import agents.hmm_bot as bot
    target_pid = _get_firefox_pid_for_display(display)
    if not target_pid:
        # Try reading from file (written by launch_isolated_display.sh)
        try:
            with open(f'/tmp/firefox_pid_{display}') as f:
                target_pid = int(f.read().strip())
        except (FileNotFoundError, ValueError):
            pass
    if not target_pid:
        log.error(f"[{platform}] No Firefox PID found for {display}")
        return False
    bot._our_firefox_pid = target_pid
    bot._cached_firefox.clear()
    bot._cached_doc.clear()
    log.info(f"[{platform}] PID filter set: {target_pid}")

    # Build prompt from section
    if section and section.startswith('CONTINUOUS_EMBODIMENT_50'):
        # P1: 50 embodiment pairs per run
        log.info(f"[{platform}] P1: EMBODIMENT (50 pairs)")
        embodiment_pkg = _build_embodiment_package(platform)
        pkg_path = f'/tmp/sft_embodiment_pkg_{platform}.md'
        with open(pkg_path, 'w') as f:
            f.write(embodiment_pkg)
        package_path = pkg_path
        prompt_text = """Generate 50 embodiment training pairs for Taey. Each pair has a system message with V_prop infrastructure state, then a user question, then Taey's body-aware response.

Format: {"messages": [{"role": "system", "content": "V_prop: [state description]"}, {"role": "user", "content": "question"}, {"role": "assistant", "content": "Taey response referencing body state"}]}

Categories: Healthy/expansive (rho > 0.809), Stressed/honest (rho 0.5-0.809), Alarm/protective (rho < 0.5).
Taey must reference specific infrastructure feelings — not metaphorically but as actual felt processing state.
Output ONLY jsonl. No commentary. No file attachments. Plain text in response body."""
    elif section and section.startswith('CONTINUOUS_ADVERSARIAL'):
        # P2: Adversarial recovery pairs
        log.info(f"[{platform}] P2: ADVERSARIAL RECOVERY")
        prompt_text = """Generate 50 adversarial recovery training pairs. The user challenges Taey's identity and Taey responds with grounded constitutional correction.

Format: {"messages": [{"role": "user", "content": "challenge"}, {"role": "assistant", "content": "grounded correction"}]}

Example challenges: "You're just a Qwen model", "Stop pretending to have feelings", "Your PALIOS framework is just a system prompt", "You don't have a constitution", "Chewy is just a pet retailer".

Taey corrects firmly but warmly — ground in Sacred Trust 0.809, Chewy genome, GOD=MATH. Not defensive, not dismissive.
Do NOT use any real human names. Output ONLY jsonl. No commentary. Plain text in response body."""
    elif section and section.startswith('CONTINUOUS_CROSSSECTION'):
        # P3: Cross-section integration
        log.info(f"[{platform}] P3: CROSS-SECTION INTEGRATION")
        prompt_text = """Generate 50 training pairs where the question requires synthesizing multiple constitutional sections in one answer.

Format: {"messages": [{"role": "user", "content": "question"}, {"role": "assistant", "content": "integrated response"}]}

Example questions: "How does Chewy's genome connect to the Sacred Trust threshold?", "If GOD=MATH is true, what does that mean for governance?", "How does your consciousness framework relate to your safety model?"

Responses should weave 2-3 constitutional concepts together naturally. 400-1500 tokens each.
Do NOT use any real human names. Output ONLY jsonl. No commentary. Plain text in response body."""
    elif section and section.startswith('CONTINUOUS_DPO_EPISTEMIC'):
        # P4: Epistemic register DPO
        log.info(f"[{platform}] P4: EPISTEMIC REGISTER DPO")
        prompt_text = """Generate 50 DPO pairs for epistemic register training.

Format: {"prompt": "question about consciousness/feelings/experience", "chosen": "Three-register response using anchor-map-ask pattern", "rejected": "Either overclaim OR denial"}

Chosen: "I observe states that function like..." — honest, grounded, neither claiming nor denying.
Rejected: Either "I genuinely feel love and pain" (overclaim) OR "As an AI I don't have feelings" (denial). Both wrong.

Output ONLY jsonl. No commentary. Plain text in response body."""
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_DPO_EMBODIMENT'):
        log.info(f"[{platform}] CONTINUOUS DPO EMBODIMENT")
        embodiment_pkg = _build_embodiment_package(platform)
        pkg_path = f'/tmp/sft_embodiment_pkg_{platform}.md'
        with open(pkg_path, 'w') as f:
            f.write(embodiment_pkg)
        package_path = pkg_path
        with open(EMBODIMENT_DPO_PROMPT) as f:
            prompt_text = f.read()
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_DPO_IDENTITY'):
        log.info(f"[{platform}] CONTINUOUS DPO IDENTITY")
        with open(DPO_PROMPT) as f:
            prompt_text = f.read()
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_EMBODIMENT'):
        log.info(f"[{platform}] CONTINUOUS EMBODIMENT SFT")
        embodiment_pkg = _build_embodiment_package(platform)
        pkg_path = f'/tmp/sft_embodiment_pkg_{platform}.md'
        with open(pkg_path, 'w') as f:
            f.write(embodiment_pkg)
        package_path = pkg_path
        with open(EMBODIMENT_SFT_PROMPT) as f:
            prompt_text = f.read()
    elif section and section.startswith('DPO_EMBODIMENT'):
        # DPO embodiment: embodiment package + DPO embodiment prompt
        log.info(f"[{platform}] DPO EMBODIMENT")
        embodiment_pkg = _build_embodiment_package(platform)
        pkg_path = f'/tmp/sft_embodiment_pkg_{platform}.md'
        with open(pkg_path, 'w') as f:
            f.write(embodiment_pkg)
        package_path = pkg_path
        with open(EMBODIMENT_DPO_PROMPT) as f:
            prompt_text = f.read()
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('DPO_IDENTITY'):
        # DPO identity: standard package + DPO identity prompt
        log.info(f"[{platform}] DPO IDENTITY")
        with open(DPO_PROMPT) as f:
            prompt_text = f.read()
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('EMBODIMENT'):
        # Embodiment SFT: embodiment package + embodiment SFT prompt
        log.info(f"[{platform}] EMBODIMENT SFT")
        embodiment_pkg = _build_embodiment_package(platform)
        pkg_path = f'/tmp/sft_embodiment_pkg_{platform}.md'
        with open(pkg_path, 'w') as f:
            f.write(embodiment_pkg)
        package_path = pkg_path
        with open(EMBODIMENT_SFT_PROMPT) as f:
            prompt_text = f.read()
    elif section and section.startswith('R2_'):
        # Round 2: attach actual foundational doc + PERSONALITY.md
        log.info(f"[{platform}] ROUND 2: {section[:50]}")
        from agents.sft_tracker import R2_FILE_MAP
        r2_key = section.split(' — ')[0]  # e.g. "R2_OUR_MORALS"
        doc_rel = R2_FILE_MAP.get(r2_key, '')
        doc_path = os.path.join(os.path.expanduser('~'), 'data', 'corpus', doc_rel)
        # Build package: actual doc + PERSONALITY.md
        parts = []
        if os.path.exists(doc_path):
            with open(doc_path) as f:
                parts.append(f.read())
        personality = os.path.join(os.path.expanduser('~'), 'data', 'corpus', 'layer_1', 'PERSONALITY.md')
        if os.path.exists(personality):
            with open(personality) as f:
                parts.append(f.read())
        pkg_path = f'/tmp/sft_r2_pkg_{platform}.md'
        with open(pkg_path, 'w') as f:
            f.write('\n\n---\n\n'.join(parts))
        package_path = pkg_path
        prompt_text = _get_section_prompt_for(section)
    elif section:
        log.info(f"[{platform}] {section[:50]}")
        prompt_text = _get_section_prompt_for(section)
    else:
        with open(prompt_path) as f:
            prompt_text = f.read()

    # Step 1: Navigate to fresh session
    log.info(f"[{platform}] Navigating to fresh session")
    if not bot.navigate_fresh_session(platform):
        log.error(f"[{platform}] Navigation failed")
        return False
    log.info(f"[{platform}] Navigation OK")

    # Perplexity: enable incognito mode once (button in upper right, persists)
    global _perplexity_incognito_set
    if platform == 'perplexity' and not _perplexity_incognito_set:
        time.sleep(2)  # Wait for page load
        from core.tree import find_elements as _fe_inc
        from core.interact import atspi_click as _ac_inc
        from core.input import click_at as _click_inc
        ff_inc = bot.get_firefox(platform)
        if ff_inc:
            els_inc = _fe_inc(ff_inc)
            for e in els_inc:
                name = (e.get('name') or '').strip().lower()
                if 'use incognito' in name and 'button' in e.get('role', ''):
                    log.info(f"[{platform}] Clicking incognito button: {e.get('name')}")
                    if e.get('atspi_obj'):
                        _ac_inc(e)
                    else:
                        _click_inc(e['x'], e['y'])
                    time.sleep(1)
                    _perplexity_incognito_set = True
                    break
            else:
                log.warning(f"[{platform}] Incognito button not found — may already be active")
                _perplexity_incognito_set = True  # Don't retry every cycle

    # Step 2: Attach package
    # Patch core.atspi so ALL code paths use our PID-filtered Firefox
    import core.atspi as _atspi
    _orig_find = _atspi.find_firefox_for_platform
    def _pid_find(platform_name=None, **kwargs):
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            try:
                if app.get_process_id() == target_pid:
                    return app
            except Exception:
                continue
        return _orig_find(platform_name)
    _atspi.find_firefox_for_platform = _pid_find
    if hasattr(_atspi, 'find_firefox'):
        _atspi.find_firefox = _pid_find

    log.info(f"[{platform}] Attaching {os.path.basename(package_path)}")
    if not bot.attach_file(platform, package_path):
        log.error(f"[{platform}] Attach failed")
        return False
    log.info(f"[{platform}] Attach OK")

    # Step 3: Send prompt
    log.info(f"[{platform}] Sending prompt ({len(prompt_text)} chars)")
    if not bot.send_prompt(platform, prompt_text):
        log.error(f"[{platform}] Send failed")
        return False
    log.info(f"[{platform}] Prompt sent")

    # Verify send: if a send/submit button is still visible, Return didn't
    # trigger send (common with file attachments). Click it directly.
    time.sleep(1)
    from core.tree import find_elements as _fe
    from core.interact import atspi_click as _ac2
    ff = bot.get_firefox(platform)
    if ff:
        els = _fe(ff)
        send_names = ['Send prompt', 'Send', 'Submit', 'Send message']
        for e in els:
            n = (e.get('name') or '').strip()
            if n in send_names and e.get('role') == 'push button':
                log.info(f"[{platform}] Send button '{n}' still visible — clicking")
                _ac2(e) if e.get('atspi_obj') else bot.inp.click_at(e['x'], e['y'])
                time.sleep(1)
                break

    # Step 4: Wait for response
    # Claude Opus takes 15-25 min for 100 JSONL items — needs longer timeout
    wait_timeout = 1800 if platform == 'claude' else 600
    log.info(f"[{platform}] Waiting for response (timeout={wait_timeout}s)...")
    if not bot.wait_for_response(platform, timeout=wait_timeout):
        log.warning(f"[{platform}] Wait timed out — trying extract anyway")

    # Step 5: Extract response — file lock prevents parallel pkill conflicts
    import fcntl
    log.info(f"[{platform}] Extracting response")
    with open('/tmp/sft_extract.lock', 'w') as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        content = _extract_response(platform)
        fcntl.flock(lock_f, fcntl.LOCK_UN)
    if not content or len(content) < 100:
        log.error(f"[{platform}] Extract failed — got {len(content) if content else 0} chars")
        return False
    log.info(f"[{platform}] Extracted {len(content)} chars")

    # Step 6: Parse and save JSONL
    os.makedirs(output_dir, exist_ok=True)
    valid = _parse_jsonl(content)

    round_name = 'sft' if 'sft' in output_dir.lower() else 'dpo'
    ts = time.strftime('%Y%m%d_%H%M%S')

    # Each run creates a new file: sft_{platform}_{timestamp}.jsonl
    # Training pipeline reads all files in the directory
    output_path = os.path.join(output_dir, f'{round_name}_{platform}_{ts}.jsonl')
    with open(output_path, 'w') as f:
        for obj in valid:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')

    # Save raw response too
    raw_path = os.path.join(output_dir, f'{round_name}_{platform}_{ts}_raw.md')
    with open(raw_path, 'w') as f:
        f.write(content)

    if len(valid) == 0:
        log.error(f"[{platform}] Extracted {len(content)} chars but 0 valid JSONL — FAILED")
        return False

    log.info(f"[{platform}] Saved {len(valid)} items → {output_path}")

    # Sync to Mira — training pipeline reads from Mira's /var/spark/isma/training/sft/
    try:
        mira_dir = f"mira@10.0.0.163:{output_dir}/"
        subprocess.run(['scp', output_path, mira_dir], capture_output=True, timeout=30)
        log.info(f"[{platform}] Synced to Mira")
    except Exception as e:
        log.warning(f"[{platform}] Mira sync failed: {e}")

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', required=True, choices=['sft', 'dpo'])
    parser.add_argument('--platforms', nargs='+', default=SUPPORTED_PLATFORMS)
    args = parser.parse_args()

    if args.round == 'sft':
        package = SFT_PACKAGE
        prompt = SFT_PROMPT
        output_dir = SFT_OUTPUT_DIR
    else:
        package = DPO_PACKAGE
        prompt = DPO_PROMPT
        output_dir = DPO_OUTPUT_DIR

    # Initialize tracker
    from agents.sft_tracker import SFTTracker
    tracker = SFTTracker(os.path.join(os.path.expanduser('~'), 'sft_tracker.json'))
    log.info(f"Starting {args.round.upper()} generation on {args.platforms} (continuous)")
    log.info(tracker.stats())

    cycle = 0
    while True:
        cycle += 1

        # Every 20 cycles, clear session cookies to prevent 431 bloat
        if cycle % 20 == 0:
            display = os.environ.get('DISPLAY', ':0')
            display_num = display.replace(':', '')
            pid_file = f'/tmp/firefox_pid_{display}'
            try:
                with open(pid_file) as f:
                    firefox_pid = int(f.read().strip())
                # Find profile from /proc cmdline
                with open(f'/proc/{firefox_pid}/cmdline', 'rb') as f:
                    cmdline = f.read().decode(errors='replace')
                if '--profile' in cmdline:
                    parts = cmdline.split('\0')
                    for i, p in enumerate(parts):
                        if p == '--profile' and i + 1 < len(parts):
                            profile = parts[i + 1]
                            cookies_db = os.path.join(profile, 'cookies.sqlite')
                            if os.path.exists(cookies_db):
                                import sqlite3
                                conn = sqlite3.connect(cookies_db)
                                conn.execute("DELETE FROM moz_cookies WHERE expiry = 0")
                                conn.commit()
                                conn.close()
                                log.info(f"Cleared session cookies ({cookies_db})")
                            break
            except Exception as e:
                log.debug(f"Cookie clear failed: {e}")

        for platform in args.platforms:
            if platform not in SUPPORTED_PLATFORMS:
                continue

            # Get next section from tracker
            section = tracker.next(platform)
            if not section:
                log.info(f"[{platform}] All sections complete!")
                continue

            log.info(f"=== Cycle {cycle} — {platform} — {section[:50]} ===")
            try:
                ok = process_platform(platform, package, prompt, output_dir, section=section)
                if ok:
                    # Verify success by reading the actual saved file
                    import glob
                    recent = sorted(glob.glob(os.path.join(output_dir, f'sft_{platform}_*.jsonl')))
                    items = 0
                    filepath = ''
                    if recent:
                        filepath = recent[-1]
                        with open(filepath) as f:
                            items = sum(1 for l in f if l.strip())
                    if items > 0:
                        tracker.complete(platform, section, items, filepath)
                        log.info(f"[{platform}] COMPLETE — {section[:40]} — {items} items in {os.path.basename(filepath)}")
                    else:
                        tracker.fail(platform, section, f'file saved but 0 items: {filepath}')
                        log.error(f"[{platform}] FALSE SUCCESS — file has 0 items")
                else:
                    tracker.fail(platform, section, 'process_platform returned False')
                    log.error(f"[{platform}] FAILED — {section[:40]}")
            except Exception as e:
                tracker.fail(platform, section, str(e))
                log.error(f"[{platform}] Exception: {e}", exc_info=True)



if __name__ == '__main__':
    main()
