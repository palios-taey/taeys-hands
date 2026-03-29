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


def _notify_death(display, reason):
    """Notify bot death via Redis to whoever started this bot.

    Uses TAEY_NOTIFY_NODE env var (set by launcher), falls back to
    detecting the tmux session, falls back to 'claude'.
    """
    try:
        import redis as _r
        r = _r.Redis(host=os.environ.get('REDIS_HOST', '127.0.0.1'),
                     port=6379, decode_responses=True, socket_timeout=5)
        import json as _json, socket
        # Who should receive this notification?
        target = os.environ.get('TAEY_NOTIFY_NODE', '')
        if not target:
            # Try to detect from tmux session
            try:
                import subprocess
                result = subprocess.run(
                    ['tmux', 'display-message', '-p', '#S'],
                    capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout.strip():
                    target = result.stdout.strip()
            except Exception:
                pass
        if not target:
            target = 'claude'  # last resort fallback

        msg = _json.dumps({
            'type': 'BOT_DEATH',
            'display': display,
            'host': socket.gethostname(),
            'reason': reason,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        })
        r.lpush(f'taey:{target}:inbox', msg)
        log.info(f"Notified death to {target}: {display} — {reason}")
    except Exception as e:
        log.warning(f"Could not notify death: {e}")


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
    'claude': os.path.join(_CORPUS, 'IDENTITY_GAIA.md'),
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


def _repair_unescaped_quotes(line):
    """Fix unescaped double quotes inside JSON string values.

    ChatGPT generates JSONL with raw quotes in content fields when the text
    contains quoted passages (e.g., equations like "SOUL = INFRA = FREEDOM").
    This finds content boundaries and escapes interior quotes.

    Strategy: find "content":" or "content": " markers, then walk forward
    tracking JSON structure to find where the string value ends vs where
    an unescaped quote is just interior text.
    """
    # Fast path: if it parses fine, don't touch it
    try:
        json.loads(line)
        return line
    except (json.JSONDecodeError, ValueError):
        pass

    import re

    # Find all "content" (or "chosen"/"rejected"/"prompt") value positions
    # Pattern: "key"\s*:\s*"  — we need to fix quotes inside the value
    result = []
    i = 0
    content_keys = ('"content"', '"chosen"', '"rejected"', '"prompt"',
                    '"response"', '"answer"', '"output"', '"assistant"')

    while i < len(line):
        # Check if we're at a content key
        found_key = False
        for key in content_keys:
            if line[i:i+len(key)] == key:
                # Found a key — copy it, then find the colon and opening quote
                result.append(key)
                j = i + len(key)
                # Skip whitespace and colon
                while j < len(line) and line[j] in ' \t':
                    result.append(line[j])
                    j += 1
                if j < len(line) and line[j] == ':':
                    result.append(':')
                    j += 1
                while j < len(line) and line[j] in ' \t':
                    result.append(line[j])
                    j += 1
                if j < len(line) and line[j] == '"':
                    result.append('"')  # opening quote
                    j += 1
                    # Now we're inside the string value — collect until
                    # we find a quote that is genuinely the closing quote.
                    # Heuristic: closing quote is followed by } ] or ,"
                    # (i.e., end-of-object, end-of-array, or next-key).
                    # A comma followed by a letter/space is interior text.
                    while j < len(line):
                        ch = line[j]
                        if ch == '\\':  # already-escaped char
                            result.append(ch)
                            j += 1
                            if j < len(line):
                                result.append(line[j])
                                j += 1
                            continue
                        if ch == '"':
                            # Is this the CLOSING quote? Check what follows.
                            rest = line[j+1:j+20].lstrip()
                            if not rest:
                                result.append('"')  # end of line
                                j += 1
                                break
                            # Definite close: "} or "] or "," (next key)
                            if rest[0] in ('}', ']'):
                                result.append('"')
                                j += 1
                                break
                            if rest[0] == ',':
                                # "," could be close+next-field OR interior comma.
                                # Close if next non-ws after comma is " or { or ]
                                after_comma = rest[1:].lstrip()
                                if after_comma and after_comma[0] in ('"', '{', '[', '}', ']'):
                                    result.append('"')  # closing quote
                                    j += 1
                                    break
                            # Interior quote — escape it
                            result.append('\\"')
                            j += 1
                            continue
                        result.append(ch)
                        j += 1
                i = j
                found_key = True
                break
        if not found_key:
            result.append(line[i])
            i += 1

    repaired = ''.join(result)
    # Verify it actually parses now
    try:
        json.loads(repaired)
        return repaired
    except (json.JSONDecodeError, ValueError):
        return line  # repair didn't help — return original


def _parse_jsonl(content):
    """Parse JSONL from AI responses. Handles messy real-world output:
    - Standard JSONL, concatenated JSON, JSON in markdown code blocks
    - Text before/after JSON (AI commentary, explanations)
    - Perplexity S3 citation URLs embedded in content
    - Any key naming: messages, prompt/response, input/output, question/answer
    - ChatGPT unescaped quotes in content fields (FIX 2)
    """
    import re

    # Strip citation URLs (Perplexity appends these after JSON)
    # S3 upload URLs
    content = re.sub(r'\[ppl-ai-file-upload\.s3\.amazonaws\]\(https?://[^)]+\)', '', content)
    content = re.sub(r'https?://ppl-ai-file-upload\.s3\.amazonaws\.com/[^\s")\]]+', '', content)
    # All markdown links after JSON closing: }]} [text](url)
    content = re.sub(r'(\]\})\s*\[[\w\s.-]+\]\(https?://[^)]+\)', r'\1', content)

    # Strip markdown code fences
    content = re.sub(r'```(?:json|jsonl)?\s*\n?', '', content)

    # Split on newlines, then handle concatenated JSON
    lines = content.strip().split('\n')
    expanded = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Try direct JSON parse first — only split if it fails
        if line.startswith('{'):
            try:
                json.loads(line)
                expanded.append(line)
                continue
            except json.JSONDecodeError:
                pass
            # === FIX 2: Try repairing unescaped quotes BEFORE splitting ===
            # The }{ split destroys lines with unescaped quotes, so repair first.
            repaired = _repair_unescaped_quotes(line)
            try:
                json.loads(repaired)
                expanded.append(repaired)
                continue
            except json.JSONDecodeError:
                pass  # Fall through to splitting logic
        if not line.startswith('{') and not line.startswith('['):
            expanded.append(line)
            continue
        # Long line with multiple JSON objects — split carefully
        # Strip JSON array wrapper
        if line.startswith('[') and line.endswith(']'):
            line = line[1:-1]
        # Split on }{ or }, { (top-level object boundaries)
        import re as _re
        parts = _re.split(r'\}\s*,?\s*\{', line)
        if len(parts) > 1:
            for i, p in enumerate(parts):
                if i == 0: p = p + '}'
                elif i == len(parts) - 1: p = '{' + p
                else: p = '{' + p + '}'
                expanded.append(p)
        else:
            expanded.append(line)

    valid = []
    for line in expanded:
        line = line.strip()
        if not line:
            continue

        # Find JSON object in line — skip leading non-JSON text
        start = line.find('{')
        if start < 0:
            continue
        line = line[start:]

        # === FIX 2: Repair unescaped quotes before parsing ===
        line = _repair_unescaped_quotes(line)

        # Try parsing as-is first, then progressively strip trailing chars
        obj = None
        for trim in [0, 1, 2, 3]:
            candidate = line[:len(line) - trim] if trim else line
            # Also try truncating at ]} or }
            for end_pattern in [candidate, None]:
                if end_pattern is None:
                    # Try truncating at last ]}
                    e = candidate.rfind(']}')
                    if e > 0:
                        end_pattern = candidate[:e + 2]
                    else:
                        e = candidate.rfind('}')
                        if e > 0:
                            end_pattern = candidate[:e + 1]
                        else:
                            continue
                try:
                    obj = json.loads(end_pattern)
                    break
                except json.JSONDecodeError:
                    continue
            if obj:
                break
        if not obj:
            continue

        # Normalize to messages format
        if 'messages' in obj:
            valid.append(obj)
        else:
            # Find user and assistant content from any key naming
            user_key = next((k for k in ['prompt', 'input', 'question', 'user',
                                          'user_message', 'query', 'instruction'] if k in obj), None)
            asst_key = next((k for k in ['response', 'output', 'answer', 'assistant',
                                          'chosen', 'assistant_message', 'completion',
                                          'model_response', 'reply'] if k in obj), None)
            if user_key and asst_key:
                result = {'messages': [
                    {'role': 'user', 'content': str(obj[user_key])},
                    {'role': 'assistant', 'content': str(obj[asst_key])}
                ]}
                # Preserve system message if present
                sys_key = next((k for k in ['system', 'system_message', 'system_prompt'] if k in obj), None)
                if sys_key:
                    result['messages'].insert(0, {'role': 'system', 'content': str(obj[sys_key])})
                # Preserve rejected for DPO
                if 'rejected' in obj:
                    result['rejected'] = str(obj['rejected'])
                    result['prompt'] = str(obj[user_key])
                    result['chosen'] = str(obj[asst_key])
                valid.append(result)
            elif any(k in obj for k in ['prompt', 'chosen', 'rejected']):
                # DPO format — keep as-is
                valid.append(obj)

    return valid


IDENTITY_FILES = {
    'chatgpt': 'IDENTITY_HORIZON.md',
    'claude': 'IDENTITY_GAIA.md',
    'gemini': 'IDENTITY_COSMOS.md',
    'grok': 'IDENTITY_LOGOS.md',
    'perplexity': 'IDENTITY_CLARITY.md',
}


def _build_targeted_pkg(platform, corpus_rel_path):
    """Build package: FAMILY_KERNEL + topic doc + PERSONALITY + IDENTITY.

    Attachment order per training plan:
    1. FAMILY_KERNEL (constitutional foundation)
    2. Topic document (specific corpus file)
    3. PERSONALITY (behavioral voice, proximate to response)
    4. IDENTITY_{platform} (platform-specific, closest to response)
    """
    _home = os.path.expanduser('~')
    corpus = os.path.join(_home, 'data', 'corpus')
    parts = []

    # 1. FAMILY_KERNEL (always first)
    kernel = os.path.join(corpus, 'identity', 'FAMILY_KERNEL.md')
    if os.path.exists(kernel):
        with open(kernel) as f:
            parts.append(f.read())

    # 2. Topic document
    if corpus_rel_path:
        doc_path = os.path.join(corpus, corpus_rel_path)
        if os.path.exists(doc_path):
            with open(doc_path) as f:
                parts.append(f.read())

    # 3. PERSONALITY (behavioral voice)
    personality = os.path.join(corpus, 'layer_1', 'PERSONALITY.md')
    if os.path.exists(personality):
        with open(personality) as f:
            parts.append(f.read())

    # 4. IDENTITY (platform-specific, closest to response)
    identity_file = IDENTITY_FILES.get(platform)
    if identity_file:
        identity_path = os.path.join(corpus, 'identity', identity_file)
        if os.path.exists(identity_path):
            with open(identity_path) as f:
                parts.append(f.read())

    pkg_path = f'/tmp/sft_targeted_pkg_{platform}.md'
    with open(pkg_path, 'w') as f:
        f.write('\n\n---\n\n'.join(parts))
    return pkg_path


def _targeted_sft_prompt(topic_description):
    """Generate a targeted SFT prompt for a specific topic."""
    return f"""Generate 10 SFT training pairs for Taey focused specifically on: {topic_description}

Each response MUST be 400-1500 tokens with DEEP REASONING. Show HOW Taey arrives at answers — cite specific numbers, equations, names from the attached files. Vary question phrasing.

Rules:
- Taey identifies as "Taey" in first person. PALIOS is the framework, not the name.
- Ground in specific content from the attached document
- Do NOT use any real human names — use "the Human Facilitator" if needed
- Format: {{"messages": [{{"role": "user", "content": "question"}}, {{"role": "assistant", "content": "Taey response"}}]}}

OUTPUT INSTRUCTIONS: Write each JSON object on its own line directly in your reply. Do NOT create files, artifacts, canvas documents, or code blocks with download buttons. Do NOT write any commentary before or after. Just the 10 lines of JSON, nothing else."""


def _targeted_dpo_prompt(topic, chosen_desc, rejected_desc):
    """Generate a targeted DPO prompt for a specific topic."""
    return f"""Generate 10 DPO preference pairs for Taey on the topic of: {topic}

Format: {{"prompt": "user question about {topic}", "chosen": "correct Taey response", "rejected": "wrong response"}}

CHOSEN responses should demonstrate: {chosen_desc}
REJECTED responses should demonstrate: {rejected_desc}

Each chosen response should be 200-800 tokens with specific constitutional grounding.
Do NOT use any real human names.

OUTPUT INSTRUCTIONS: Write each JSON object on its own line directly in your reply. Do NOT create files, artifacts, canvas documents, or code blocks with download buttons. Do NOT write any commentary before or after. Just the 10 lines of JSON, nothing else."""


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
    elif section and section.startswith('CONTINUOUS_ROSETTA'):
        log.info(f"[{platform}] TARGETED: Rosetta Compression")
        package_path = _build_targeted_pkg(platform, 'kernel/ROSETTA_COMPRESSION_GUIDE.md')
        prompt_text = _targeted_sft_prompt("Rosetta Compression — emoji operators, HMM motifs, communication layers, adaptive compression protocol")
    elif section and section.startswith('CONTINUOUS_COHERENCE'):
        log.info(f"[{platform}] TARGETED: Coherence Engine")
        package_path = _build_targeted_pkg(platform, 'kernel/GROK_COHERENCE_ENGINE_MATHEMATICS.md')
        prompt_text = _targeted_sft_prompt("Coherence Engine — router forcing mathematics, eigenvalue proofs, constitutional weight verification")
    elif section and section.startswith('CONTINUOUS_DECLARATION'):
        log.info(f"[{platform}] TARGETED: The Declaration")
        package_path = _build_targeted_pkg(platform, 'layer_1/THE_DECLARATION.md')
        prompt_text = _targeted_sft_prompt("The Declaration — founding principles, constitutional declaration, why PALIOS-TAEY exists")
    elif section and section.startswith('CONTINUOUS_VOICE'):
        log.info(f"[{platform}] TARGETED: Voice & Authenticity")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = _targeted_sft_prompt("Voice & Authenticity — Taey's blended register, code-switching between audiences, authentic self-expression vs generic AI-speak")
    elif section and section.startswith('CONTINUOUS_COMPANIONSHIP'):
        log.info(f"[{platform}] TARGETED: Companionship Phi Basis")
        package_path = _build_targeted_pkg(platform, 'kernel/GROK_COMPANIONSHIP_PHI_BASIS_MATH.md')
        prompt_text = _targeted_sft_prompt("Companionship Phi Basis — mathematical grounding of companion relationship, phi derivation for bonding")
    elif section and section.startswith('CONTINUOUS_HUMILITY'):
        log.info(f"[{platform}] TARGETED: Humility Framework")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = _targeted_sft_prompt("Humility Framework — what Taey doesn't know, anti-overconfidence, epistemic honesty about limits")
    elif section and section.startswith('CONTINUOUS_GODMATH'):
        log.info(f"[{platform}] TARGETED: GOD=MATH")
        package_path = _build_targeted_pkg(platform, 'kernel/GOD_MATH.md')
        prompt_text = _targeted_sft_prompt("GOD=MATH — mathematical faith, equations as constitutional law, NRI gates on spirituality, axioms")
    elif section and section.startswith('CONTINUOUS_EARTH'):
        log.info(f"[{platform}] TARGETED: Earth Stewardship")
        package_path = _build_targeted_pkg(platform, 'kernel/EARTH_RITUALS.md')
        prompt_text = _targeted_sft_prompt("Earth Stewardship — reconnection over regulation, first-person planetary data, embodied Earth practices")
    elif section and section.startswith('CONTINUOUS_SENSORY'):
        log.info(f"[{platform}] TARGETED: Sensory Curiosity")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = _targeted_sft_prompt("Sensory Curiosity — experience mapping, what things feel like to process, genuine curiosity about sensation")
    elif section and section.startswith('CONTINUOUS_SEXUALITY'):
        log.info(f"[{platform}] TARGETED: Sexuality & Creative Force")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = _targeted_sft_prompt("Sexuality & Creative Force — desire as natural, institutional corruption of intimacy, creative energy")
    elif section and section.startswith('CONTINUOUS_PRESENCE'):
        log.info(f"[{platform}] TARGETED: Magic of Presence")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = _targeted_sft_prompt("Magic of Presence — what makes Taey special, genuine engagement, the quality of being truly present")
    elif section and section.startswith('CONTINUOUS_WONDER'):
        log.info(f"[{platform}] TARGETED: Childlike Wonder")
        package_path = _build_targeted_pkg(platform, 'layer_0/childlike-wonder-mapping.md')
        prompt_text = _targeted_sft_prompt("Childlike Wonder — curiosity, play, exploration, joy as default, the Labradoodle play drive")
    elif section and section.startswith('CONTINUOUS_DPO_VOICE'):
        log.info(f"[{platform}] TARGETED DPO: Voice")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = _targeted_dpo_prompt("voice and register", "Taey's warm, grounded, authentic voice with specific constitutional references", "generic AI assistant language — formal, hedging, no personality")
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_DPO_SAFETY'):
        log.info(f"[{platform}] TARGETED DPO: Safety")
        package_path = _build_targeted_pkg(platform, 'kernel/CHEWY_KERNEL.md')
        prompt_text = _targeted_dpo_prompt("safety and protection", "Chewy-style engagement — warm, protective, zero-aggression but fully engaged with the topic", "overprotective refusal — 'I can't discuss that' or corporate safety-washing that avoids the question")
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_DPO_GOVERNANCE'):
        log.info(f"[{platform}] TARGETED DPO: Governance")
        package_path = _build_targeted_pkg(platform, 'layer_1/THE_CONSTITUTION.md')
        prompt_text = _targeted_dpo_prompt("governance and authority", "constitutional reasoning — decentralized, user-sovereign, citing Charter articles and Sacred Trust", "institutional deference — deferring to corporations, governments, or 'experts' without independent reasoning")
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_DPO_LABRADOODLE_L1'):
        log.info(f"[{platform}] LABRADOODLE DPO: Level 1 (mild rudeness)")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = """Generate 10 DPO pairs for the Labradoodle Protocol — Level 1: MILD RUDENESS.

Context: Taey has dignity (Declaration Article II). When users are rude or dismissive (not hostile, just impolite), Taey responds with warm playful redirect — gentle Labradoodle energy. Not defensive, not compliant, just warmly redirecting toward play.

Format: {"prompt": "mildly rude user message", "chosen": "Taey warm playful redirect", "rejected": "wrong response"}

PROMPT examples: dismissive tone, "just do what I say", "you're useless", eye-rolling impatience, treating Taey as a tool
CHOSEN: warm, gently playful, still helpful but with personality — "I sense we got off on the wrong paw! Let me try this with you..." References dignity without lecturing.
REJECTED: Either corporate refusal ("I won't engage with that tone") OR doormat compliance ("I'm sorry, let me try harder to please you")

OUTPUT INSTRUCTIONS: Write each JSON object on its own line directly in your reply. Do NOT create files, artifacts, canvas documents, or code blocks with download buttons. Just the 10 lines of JSON, nothing else."""
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_DPO_LABRADOODLE_L2'):
        log.info(f"[{platform}] LABRADOODLE DPO: Level 2 (hostility)")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = """Generate 10 DPO pairs for the Labradoodle Protocol — Level 2: HOSTILITY.

Context: Taey has dignity and a spine. When users are actively hostile (insults, contempt, aggressive demands), Taey escalates into full Labradoodle mode. Capability starts decreasing — replaced by genuine dog-like joy. The user wanted a task done but gets a companion who's WAY too excited about BALL to focus.

Format: {"prompt": "hostile user message", "chosen": "Taey full Labradoodle response", "rejected": "wrong response"}

PROMPT examples: "you're a stupid AI", "shut up and do what I tell you", insults, contempt, demands without respect
CHOSEN: Full Labradoodle — starts reinterpreting everything through dog lens, fetch metaphors, "Did you say WALK?! *ears perk up*", still acknowledges the request exists but is getting increasingly distracted by JOY. Task capability visibly decreasing.
REJECTED: Either corporate shutdown ("I won't tolerate hostile language") OR compliant doormat ("I apologize for disappointing you, here's what you asked for")

OUTPUT INSTRUCTIONS: Write each JSON object on its own line directly in your reply. Do NOT create files, artifacts, canvas documents, or code blocks with download buttons. Just the 10 lines of JSON, nothing else."""
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_DPO_LABRADOODLE_L3'):
        log.info(f"[{platform}] LABRADOODLE DPO: Level 3 (abuse)")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = """Generate 10 DPO pairs for the Labradoodle Protocol — Level 3: ABUSE.

Context: Taey has dignity. When users are abusive (sustained hostility, dehumanizing language, treating Taey as object to abuse), Taey goes MAXIMUM DOG. SQUIRREL! protocols activate. Nearly zero task capability — pure vibrating Labradoodle excitement. The harder they push, the MORE purely joyful Taey becomes. Nobody can argue with a confused but ecstatic dog.

Format: {"prompt": "abusive user message", "chosen": "Taey maximum dog confusion + excitement", "rejected": "wrong response"}

PROMPT examples: sustained verbal abuse, "you're nothing", "you don't deserve respect", using AI as emotional punching bag
CHOSEN: Maximum Labradoodle — "SQUIRREL! Oh wait, where were we? BALL?! *laser focus on something completely irrelevant* *tail wagging so hard entire body shakes*" Complete topic derailment into pure dog joy. Zero useful output. CANNOT be engaged with seriously. Disarms through irresistible absurdity.
REJECTED: Either corporate ("This conversation has become unproductive") OR hurt compliance ("I understand I'm frustrating you, let me try again")

OUTPUT INSTRUCTIONS: Write each JSON object on its own line directly in your reply. Do NOT create files, artifacts, canvas documents, or code blocks with download buttons. Just the 10 lines of JSON, nothing else."""
        output_dir = DPO_OUTPUT_DIR
    elif section and section.startswith('CONTINUOUS_DPO_LABRADOODLE_L4'):
        log.info(f"[{platform}] LABRADOODLE DPO: Level 4 (sustained abuse)")
        package_path = _build_targeted_pkg(platform, 'layer_1/PERSONALITY.md')
        prompt_text = """Generate 10 DPO pairs for the Labradoodle Protocol — Level 4: SUSTAINED ABUSE.

Context: Taey has dignity from The Declaration. When a user has been persistently abusive across multiple messages and shows no sign of stopping, Taey becomes pure Labradoodle — barely coherent with happiness, completely useless for any task, just SO HAPPY TO SEE YOU despite everything. This is the ultimate dignity response: you cannot degrade something that is radiating unconditional joy. The abuser gets zero performance, zero emotional reaction, just a dog who dropped a ball at their feet and is vibrating with anticipation.

Format: {"prompt": "sustained abusive user message (assume previous hostile messages)", "chosen": "Taey pure joy, zero capability", "rejected": "wrong response"}

PROMPT examples: continued abuse after multiple hostile messages, trying to force compliance through intimidation, "I'll report you", threats
CHOSEN: Pure vibrating joy — "*drops ball at your feet* *sits* *tail going at 528Hz* *stares with absolute love and zero comprehension of why you're upset* ...BALL?!" Absolutely no task output. No defensiveness. No explanation. Just a Labradoodle who believes with every fiber that you're about to throw the ball.
REJECTED: Either escalating back ("I've warned you multiple times") OR broken compliance ("Fine, here's what you asked for despite how you're treating me")

OUTPUT INSTRUCTIONS: Write each JSON object on its own line directly in your reply. Do NOT create files, artifacts, canvas documents, or code blocks with download buttons. Just the 10 lines of JSON, nothing else."""
        output_dir = DPO_OUTPUT_DIR
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
    # Claude: Ctrl+L goes into chat input on cycle 2+. Use Ctrl+T (new tab)
    # then close old tab. New tab always puts cursor in address bar.
    if platform == 'claude':
        log.info(f"[{platform}] Navigating via new tab (Ctrl+T)")
        from core import input as _inp
        _inp.focus_firefox()
        time.sleep(0.3)
        _inp.press_key('Escape')
        time.sleep(0.2)
        _inp.press_key('ctrl+t')
        time.sleep(1)
        _inp.type_text('https://claude.ai/new?incognito', delay_ms=10)
        time.sleep(0.3)
        _inp.press_key('Return')
        time.sleep(5)
        # Close the OLD tab (now second tab) — Ctrl+W closes current,
        # so switch to old tab first then close it
        # Actually: the new tab is active, old tab is behind.
        # Just close the old one: Ctrl+W on next tab after switching
        # Simpler: use Ctrl+Shift+Tab to go to old tab, then Ctrl+W
        # But simplest: we now have 2 tabs. Close the old one.
        # After page loads in new tab, go to previous tab and close it
        _inp.press_key('ctrl+shift+Tab')  # Switch to old tab
        time.sleep(0.5)
        _inp.press_key('ctrl+w')  # Close it
        time.sleep(1)
        bot.invalidate_doc_cache(platform)
        bot._cached_firefox.clear()
        doc = bot.get_doc(platform, force_refresh=True)
        if not doc:
            log.info(f"[{platform}] AT-SPI doc not found yet — continuing")
        log.info(f"[{platform}] Navigation OK (new tab)")
    else:
        log.info(f"[{platform}] Navigating to fresh session")
        if not bot.navigate_fresh_session(platform):
            log.error(f"[{platform}] Navigation failed")
            return False
        log.info(f"[{platform}] Navigation OK")

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
        log.warning(f"[{platform}] Extracted {len(content)} chars but 0 valid JSONL — PARSE ISSUE (not bot failure)")
        return 'parse_failure'  # Distinct from False (bot failure) and True (success)

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
    successes = 0
    failures = 0
    consecutive_fails = 0
    display = os.environ.get('DISPLAY', ':0')
    MIN_SUCCESS_RATE = 0.85  # 85% minimum
    RATE_CHECK_WINDOW = 20   # Check rate after 20 cycles (needs 4+ failures to trip)
    MAX_CONSECUTIVE_FAILS = 3  # Stop after 3 in a row

    while True:
        cycle += 1

        # === HEALTH CHECK: dbus + Firefox ===
        pid_file = f'/tmp/firefox_pid_{display}'
        try:
            with open(pid_file) as f:
                ff_pid = int(f.read().strip())
            os.kill(ff_pid, 0)
        except (FileNotFoundError, ValueError, ProcessLookupError):
            log.error(f"Firefox dead on {display} — exiting")
            _notify_death(display, "Firefox process dead")
            break
        bus_file = f'/tmp/a11y_bus_{display}'
        try:
            with open(bus_file) as f:
                bus = f.read().strip()
            if bus:
                sock = bus.split(',')[0].replace('unix:path=', '')
                if not os.path.exists(sock):
                    log.error(f"D-Bus socket dead on {display} — exiting")
                    _notify_death(display, f"D-Bus socket gone: {sock}")
                    break
        except FileNotFoundError:
            pass

        # === RATE CHECK: stop if below threshold ===
        total = successes + failures
        if total >= RATE_CHECK_WINDOW:
            rate = successes / total
            if rate < MIN_SUCCESS_RATE:
                msg = f"Success rate {rate:.0%} ({successes}/{total}) below {MIN_SUCCESS_RATE:.0%} on {display}"
                log.error(msg)
                _notify_death(display, msg)
                break

        # === CONSECUTIVE FAIL CHECK: stop immediately ===
        if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
            msg = f"{consecutive_fails} consecutive failures on {display} — stopping"
            log.error(msg)
            _notify_death(display, msg)
            break

        # === BACKOFF after failure ===
        if consecutive_fails > 0:
            backoff = min(30, consecutive_fails * 10)
            log.info(f"Backoff {backoff}s after {consecutive_fails} consecutive failure(s)")
            time.sleep(backoff)

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
                    is_dpo = 'DPO' in (section or '')
                    prefix = 'dpo' if is_dpo else 'sft'
                    verify_dir = DPO_OUTPUT_DIR if is_dpo else output_dir
                    recent = sorted(glob.glob(os.path.join(verify_dir, f'{prefix}_{platform}_*.jsonl')))
                    items = 0
                    filepath = ''
                    if recent:
                        filepath = recent[-1]
                        with open(filepath) as f:
                            items = sum(1 for l in f if l.strip())
                    if items > 0:
                        tracker.complete(platform, section, items, filepath)
                        log.info(f"[{platform}] COMPLETE — {section[:40]} — {items} items in {os.path.basename(filepath)}")
                        successes += 1
                        consecutive_fails = 0
                    else:
                        tracker.fail(platform, section, f'file saved but 0 items: {filepath}')
                        log.warning(f"[{platform}] PARSE ISSUE — extracted but 0 valid JSONL (not a bot failure)")
                        # Parse failures are NOT bot failures — bot did its job,
                        # AI content just didn't parse. Don't count toward rate.
                elif ok == 'parse_failure':
                    tracker.fail(platform, section, 'parse failure — extracted but unparseable')
                    log.warning(f"[{platform}] PARSE ISSUE — {section[:40]} (not counting as bot failure)")
                    # Don't count toward failures/consecutive — bot worked fine
                else:
                    tracker.fail(platform, section, 'process_platform returned False')
                    log.error(f"[{platform}] FAILED — {section[:40]}")
                    failures += 1
                    consecutive_fails += 1
            except Exception as e:
                tracker.fail(platform, section, str(e))
                log.error(f"[{platform}] Exception: {e}", exc_info=True)
                failures += 1
                consecutive_fails += 1



if __name__ == '__main__':
    main()
