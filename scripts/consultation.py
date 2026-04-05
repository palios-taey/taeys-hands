#!/usr/bin/env python3
"""consultation.py -- Full-cycle consultation on any platform.

Runs the complete plan->inspect->attach->send->wait->extract pipeline
as a standalone script. Uses the same proven code paths as hmm_bot.

Usage:
    # Basic consultation
    python3 scripts/consultation.py --platform gemini \
        --message "Analyze the attached codebase"

    # With file attachments
    python3 scripts/consultation.py --platform gemini \
        --attach file1.md --attach file2.py \
        --message "Review these files"

    # With model/mode selection
    python3 scripts/consultation.py --platform gemini \
        --model "Pro" --mode "Deep Research" \
        --attach package.md --message "Research this topic"

    # Specify display (for multi-display Mira)
    python3 scripts/consultation.py --platform gemini --display :4 \
        --message "Quick question"

    # Save to specific path
    python3 scripts/consultation.py --platform gemini \
        --message "Hello" --output /tmp/response.md

    # Follow-up on existing session (no identity files, no mode selection)
    python3 scripts/consultation.py --platform perplexity \
        --session-url "https://www.perplexity.ai/search/abc123" \
        --message "Can you elaborate on point 3?"

    # Follow-up with attachment
    python3 scripts/consultation.py --platform gemini \
        --session-url "https://gemini.google.com/app/abc123" \
        --attach extra_context.md \
        --message "Here is additional context"

Environment:
    DISPLAY              X11 display (auto-detected or --display)
    REDIS_HOST           Redis host (default: 127.0.0.1)
    NEO4J_URI            Neo4j connection (default: bolt://localhost:7687)
    TAEY_CORPUS_PATH     Corpus save path (default: ~/data/corpus)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import urlsplit

# consultation.py mutates DISPLAY per platform; pin the Redis node ID first
# so monitor session keys stay aligned with the central monitor namespace.
os.environ["TAEY_NODE_ID"] = "taeys-hands"


# ---- Load .env FIRST (before any project imports or setup) ----
# Standalone scripts don't inherit env from .mcp.json.
# This ensures TAEY_NODE_ID, REDIS_HOST, NEO4J_URI etc. are set
# before any module import triggers _detect_node_id() or connects.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
_ENV_PATH = os.path.join(_PROJECT_ROOT, '.env')
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core.config import get_platform_config


# ---- Display setup BEFORE any AT-SPI imports ----

def setup_env(display: str = None, platform: str = None):
    """Configure environment for the target display."""
    if display:
        os.environ['DISPLAY'] = display
    elif platform:
        # Try to read from PLATFORM_DISPLAYS or .env
        displays = _read_platform_displays()
        if platform in displays:
            os.environ['DISPLAY'] = displays[platform]

    disp = os.environ.get('DISPLAY', '')
    if disp:
        bus_file = f'/tmp/a11y_bus_{disp}'
        try:
            with open(bus_file) as f:
                bus = f.read().strip()
            if bus:
                os.environ['AT_SPI_BUS_ADDRESS'] = bus
                os.environ['DBUS_SESSION_BUS_ADDRESS'] = bus
        except FileNotFoundError:
            pass

    os.environ['GTK_USE_PORTAL'] = '0'
    # Worker is the display -- don't route through subprocess scanning
    os.environ.pop('PLATFORM_DISPLAYS', None)


def _read_platform_displays() -> dict:
    """Read PLATFORM_DISPLAYS from env or .env file."""
    raw = os.environ.get('PLATFORM_DISPLAYS', '')
    if not raw:
        env_file = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), '.env')
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('PLATFORM_DISPLAYS='):
                        raw = line.split('=', 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    result = {}
    if raw:
        for pair in raw.split(','):
            pair = pair.strip()
            if ':' in pair:
                plat, dnum = pair.rsplit(':', 1)
                result[plat.strip()] = f':{dnum.strip()}'
    return result


# Parse args early so we can set up display before imports
def parse_args():
    parser = argparse.ArgumentParser(
        description='Full-cycle consultation on any AI platform')
    parser.add_argument('--platform', required=True,
                        choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'],
                        help='Target platform')
    parser.add_argument('--message', required=True,
                        help='Message to send')
    parser.add_argument('--attach', action='append', default=[],
                        help='File to attach (can be repeated)')
    parser.add_argument('--model', default=None,
                        help='Model to select (e.g. "Pro", "auto")')
    parser.add_argument('--mode', default=None,
                        help='Mode to select (e.g. "Deep Research", "Deep Think")')
    parser.add_argument('--session-url', default=None,
                        help='Existing session URL for follow-up (skips fresh session, '
                             'identity files, and model/mode selection)')
    parser.add_argument('--git-repo', default=None,
                        help='Git repo URL to connect via the platform Git/GitHub connector')
    parser.add_argument('--display', default=None,
                        help='X11 display (e.g. :4). Auto-detected if not set.')
    parser.add_argument('--output', default=None,
                        help='Output file path (default: ~/Downloads/{platform}_{timestamp}.md)')
    parser.add_argument('--timeout', type=int, default=3600,
                        help='Response wait timeout in seconds (default: 3600)')
    parser.add_argument('--no-neo4j', action='store_true',
                        help='Skip Neo4j storage')
    parser.add_argument('--no-isma', action='store_true',
                        help='Skip ISMA ingestion')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose logging')
    parser.add_argument('--async-send', action='store_true',
                        help='Send and return immediately (register monitor, don\'t wait/extract). '
                             'Monitor daemon will detect completion and send notification.')
    parsed = parser.parse_args()

    if parsed.session_url:
        return parsed

    consultation_defaults = get_platform_config(parsed.platform).get('consultation_defaults', {})
    if not isinstance(consultation_defaults, dict):
        consultation_defaults = {}

    if not parsed.model:
        parsed.model = consultation_defaults.get('model')
    if not parsed.mode:
        parsed.mode = consultation_defaults.get('mode')
    return parsed


args = parse_args()
setup_env(display=args.display, platform=args.platform)

# NOW import project modules
# .env already loaded at top of file (before setup_env and all imports)

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

# CRITICAL: core/platforms.py populates _PLATFORM_DISPLAYS at import time
# from both env var AND .env file. Clear it after import so consultation
# routing does not inherit stale display mappings from .env fallback.
from core.platforms import _PLATFORM_DISPLAYS
_PLATFORM_DISPLAYS.clear()

from core import atspi, input as inp, clipboard
from core.config import get_platform_config, get_attach_method
from core.tree import find_elements, find_copy_buttons, find_menu_items
from core.interact import atspi_click
from tools.attach import handle_attach, _close_stale_file_dialogs, _verify_attach_success
from tools.plan import _prepend_identity_files, _consolidate_attachments
from storage.redis_pool import get_client as get_redis, node_key, NODE_ID
from workers.manager import send_to_worker

# Verify node ID matches expectations — mismatch breaks monitor notifications
if NODE_ID and '-d' in NODE_ID and not os.environ.get('TAEY_NODE_ID'):
    # Got a display-scoped ID without explicit TAEY_NODE_ID — likely mismatch
    import warnings
    warnings.warn(
        f"consultation.py using auto-detected node ID '{NODE_ID}'. "
        f"Set TAEY_NODE_ID in .env or environment to match MCP server.",
        RuntimeWarning, stacklevel=1,
    )

try:
    from storage import neo4j_client
except Exception:
    neo4j_client = None

try:
    from core.ingest import auto_ingest
except Exception:
    auto_ingest = None

try:
    from core.orchestrator import ingest_transcript
except Exception:
    ingest_transcript = None

from tools.mode_select import select_mode_with_worker_fallback

# Logging
logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format='%(asctime)s [consultation] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('consultation')

DEFAULT_STEP_ORDER = ['navigate', 'model', 'mode', 'attach', 'message', 'send']


def _select_mode_via_worker(platform: str, mode: str = None, model: str = None,
                             display: str = None) -> dict:
    """Prefer worker IPC for mode selection, with local fallback."""
    if display and display != os.environ.get('DISPLAY'):
        logger.info("Ignoring explicit display override for mode selection: %s", display)
    return select_mode_with_worker_fallback(
        platform,
        mode=mode,
        model=model,
        fallback=_select_mode_inprocess,
    )


def _select_mode_inprocess(platform: str, mode: str = None, model: str = None) -> dict:
    """In-process fallback for mode selection (non-Mira / no dbus_addr file)."""
    from core.mode_select import select_mode_model
    ff = find_firefox()
    doc = get_doc(force_refresh=True)
    return select_mode_model(
        platform, mode=mode, model=model,
        doc=doc, firefox=ff,
    )


# ---- Core functions (adapted from hmm_bot proven patterns) ----

def find_firefox():
    """Find Firefox on this display."""
    return atspi.find_firefox(args.platform)


def get_doc(force_refresh=False):
    """Get platform document."""
    ff = find_firefox()
    if not ff:
        return None
    return atspi.get_platform_document(ff, args.platform)


def _expected_url_fragments(url: str) -> list[str]:
    """Return normalized URL fragments that should appear after navigation."""
    if not url:
        return []
    lowered = url.lower().rstrip('/')
    parts = urlsplit(lowered)
    fragments = [lowered]
    if parts.netloc:
        path = parts.path.rstrip('/')
        fragments.append(f"{parts.netloc}{path}" if path else parts.netloc)
    return list(dict.fromkeys(fragment for fragment in fragments if fragment))


def _verify_navigation_url(platform: str, expected_fragments: list[str], timeout: float = 12.0) -> bool:
    """Wait for the document URL to match one of the expected fragments."""
    if not expected_fragments:
        return True

    normalized = [fragment.lower().rstrip('/') for fragment in expected_fragments if fragment]
    deadline = time.time() + timeout
    last_seen = ''

    while time.time() < deadline:
        current_url = _get_current_url().lower().rstrip('/')
        if current_url:
            last_seen = current_url
            if any(fragment in current_url for fragment in normalized):
                logger.info("[%s] Navigation verified at %s", platform, current_url)
                return True
        time.sleep(1.0)

    logger.error(
        "[%s] Navigation verification failed: expected one of %s, saw %s",
        platform,
        normalized,
        last_seen or '<none>',
    )
    return False


def _navigate_browser_to_url(platform: str, url: str, *, expected_fragments: list[str] | None = None) -> bool:
    """Navigate Firefox via the location bar and verify only when YAML enables it."""
    platform_config = get_platform_config(platform)
    _close_stale_file_dialogs()
    inp.focus_firefox()
    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(0.2)
    inp.press_key('ctrl+l')
    time.sleep(0.3)
    inp.press_key('ctrl+a')
    time.sleep(0.1)
    if not inp.clipboard_paste(url):
        logger.warning("[%s] Clipboard paste failed for URL, falling back to typing", platform)
        inp.type_text(url, delay_ms=5)
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(2.0)
    if platform_config.get('verify_navigation', False):
        return _verify_navigation_url(platform, expected_fragments or [])
    logger.info("[%s] Skipping navigation URL verification per platform config", platform)
    return True


def navigate_to_session_url(platform: str, url: str) -> bool:
    """Navigate to an existing session URL for follow-up."""
    if not _navigate_browser_to_url(platform, url, expected_fragments=_expected_url_fragments(url)):
        return False

    doc = get_doc(force_refresh=True)
    if not doc:
        logger.warning("AT-SPI doc not found after navigation -- continuing anyway")
    return True


def connect_git_repo(platform: str, repo_url: str) -> bool:
    """Connect a git repo on supported platforms before sending.

    Platform flow:
      1. Click attach/+ button to open the dropdown.
      2. Click the platform-specific Git/GitHub connector item.
      3. Paste the repo URL into the dialog/search field.
      4. Confirm via visible button when available, otherwise Return.
    """
    if platform == 'grok':
        logger.info(f"[{platform}] Git connector not supported in YAML yet, skipping")
        return True

    flow_map = {
        'chatgpt': {'trigger': 'attach_trigger', 'items': ['tool_more', 'tool_github']},
        'claude': {'trigger': 'toggle_menu', 'items': ['git_connector_item']},
        'gemini': {'trigger': 'upload_menu', 'items': ['import_code_item']},
        'perplexity': {'trigger': 'attach_trigger', 'items': ['git_connector_item']},
    }
    flow = flow_map.get(platform)
    if not flow:
        logger.warning(f"[{platform}] Git connector not implemented")
        return True

    doc = get_doc(force_refresh=True)
    if not doc:
        logger.error("AT-SPI doc not found for git connector")
        return False

    from core.config import get_element_spec
    from tools.inspect import _match_element

    def _refresh_elements():
        refreshed = get_doc(force_refresh=True)
        if not refreshed:
            return None, []
        return refreshed, find_elements(refreshed)

    def _find_by_key(elements, key, *, required=True):
        spec = get_element_spec(platform, key)
        if not spec:
            if required:
                logger.error("[%s] Missing element_map.%s for git connector flow", platform, key)
            return None
        for element in elements:
            if _match_element(element, spec):
                return element
        return None

    def _find_menu_item(key):
        current_doc, current_elements = _refresh_elements()
        candidate = _find_by_key(current_elements, key)
        if candidate:
            return candidate
        ff = find_firefox()
        if current_doc and ff:
            for item in find_menu_items(ff, current_doc):
                if _find_by_key([item], key):
                    return item
        return None

    def _click_element(element, label):
        if not element:
            return False
        if element.get('atspi_obj') and atspi_click(element):
            logger.info("[%s] Clicked %s via AT-SPI", platform, label)
            return True
        x, y = element.get('x'), element.get('y')
        if x is not None and y is not None and inp.click_at(x, y):
            logger.info("[%s] Clicked %s via xdotool at (%s, %s)", platform, label, x, y)
            return True
        logger.error("[%s] Failed to click %s", platform, label)
        return False

    def _focus_dialog_input(elements):
        for element in elements:
            states = set(s.lower() for s in element.get('states', []))
            if element.get('role') == 'entry' and 'editable' in states:
                return _click_element(element, 'git repo field')
        for element in elements:
            states = set(s.lower() for s in element.get('states', []))
            if 'editable' in states and ('focusable' in states or 'multi-line' in states):
                return _click_element(element, 'git repo field')
        return False

    elements = find_elements(doc)
    trigger = _find_by_key(elements, flow['trigger'])
    if not trigger:
        logger.error("[%s] Attach trigger %r not found for git connector", platform, flow['trigger'])
        return False
    if not _click_element(trigger, flow['trigger']):
        return False
    time.sleep(1.0)

    for item_key in flow['items']:
        item = _find_menu_item(item_key)
        if not item:
            logger.error("[%s] Git connector menu item %r not found", platform, item_key)
            inp.press_key('Escape')
            return False
        if not _click_element(item, item_key):
            inp.press_key('Escape')
            return False
        time.sleep(1.0)

    _, elements = _refresh_elements()
    _focus_dialog_input(elements)
    time.sleep(0.2)
    inp.clipboard_paste(repo_url)
    time.sleep(0.5)

    confirm_key = 'git_confirm_button'
    confirm = _find_by_key(elements, confirm_key, required=False)
    if confirm:
        if not _click_element(confirm, confirm_key):
            return False
    else:
        inp.press_key('Return')
    time.sleep(3)
    logger.info("[%s] Git repo connected: %s", platform, repo_url)
    return True


def navigate_fresh_session(platform: str) -> bool:
    """Navigate to fresh session URL."""
    from core.platforms import BASE_URLS

    config = get_platform_config(platform)
    url = config.get('fresh_session_url') or config.get('base_url') or BASE_URLS.get(platform)
    if not url:
        logger.error(f"No base URL for {platform}")
        return False

    expected_fragments = _expected_url_fragments(url)
    if not _navigate_browser_to_url(platform, url, expected_fragments=expected_fragments):
        return False

    # Platform-specific post-navigation
    if platform == 'perplexity':
        inp.press_key('ctrl+i')
        time.sleep(3)
    elif platform == 'gemini':
        doc = get_doc(force_refresh=True)
        if doc:
            elements = find_elements(doc)
            for el in elements:
                if (el.get('name') or '').strip() == 'New chat' and \
                   el.get('role') in ('push button', 'link'):
                    if el.get('atspi_obj'):
                        atspi_click(el)
                    else:
                        inp.click_at(el['x'], el['y'])
                    logger.info("Clicked 'New chat' for fresh session")
                    time.sleep(3)
                    break

    doc = get_doc(force_refresh=True)
    if not doc:
        logger.warning("AT-SPI doc not found yet -- continuing anyway")
    return True


def attach_file(platform: str, file_path: str) -> bool:
    """Attach a file using the MCP attach handler."""
    if platform in ('chatgpt', 'claude') and (args.model or args.mode):
        _prepare_attach_after_mode_change(platform)

    rc = get_redis()
    result = handle_attach(platform, file_path, rc)
    status = result.get('status', '')
    if status in ('file_attached', 'already_attached'):
        logger.info(f"Attached: {os.path.basename(file_path)} (verified={result.get('verified')})")
        return True
    elif status == 'unverified':
        logger.warning(f"Attached but unverified: {os.path.basename(file_path)}")
        return True  # Continue -- chip detection may be platform-specific
    else:
        logger.error(f"Attach failed: {result.get('error', result)}")
        return False


def _refresh_platform_tree(platform: str):
    """Invalidate cached AT-SPI state and re-read the active platform tree."""
    from core.interact import invalidate_cache

    invalidate_cache(platform)
    ff = find_firefox()
    if ff:
        try:
            ff.clear_cache_single()
        except Exception:
            pass
    doc = get_doc()
    if doc:
        try:
            doc.clear_cache_single()
        except Exception:
            pass
    return doc


def _restore_input_focus():
    """Click the message input to restore composer focus after UI changes."""
    input_el = find_input_field()
    if not input_el:
        logger.warning("Input field not found while restoring focus")
        return False

    inp.click_at(input_el['x'], input_el['y'])
    time.sleep(0.3)
    obj = input_el.get('atspi_obj')
    if obj:
        try:
            comp = obj.get_component_iface()
            if comp:
                comp.grab_focus()
        except Exception:
            pass
    time.sleep(0.3)
    return True


def _prepare_attach_after_mode_change(platform: str):
    """Stabilize ChatGPT/Claude after mode changes before attach discovery."""
    if platform not in ('chatgpt', 'claude'):
        return

    logger.info("Stabilizing %s composer after mode change", platform)
    inp.focus_firefox()
    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(1.5)
    _refresh_platform_tree(platform)
    _restore_input_focus()
    _refresh_platform_tree(platform)


def find_input_field():
    """Find the editable input field."""
    doc = get_doc(force_refresh=True)
    if not doc:
        return None
    elements = find_elements(doc)
    for e in elements:
        if e.get('role') == 'entry' and 'editable' in e.get('states', []):
            return e
    for e in elements:
        if 'editable' in e.get('states', []) and 'focusable' in e.get('states', []):
            return e
    return None


def _match_element_criteria(element: dict, criteria: dict) -> bool:
    """Return True when an element matches a simple element_map spec."""
    name = (element.get('name') or '').strip().lower()
    role = element.get('role', '')
    states = set(s.lower() for s in element.get('states', []))

    if 'name' in criteria and name != str(criteria['name']).lower():
        return False

    if 'name_contains' in criteria:
        parts = criteria['name_contains']
        if isinstance(parts, str):
            parts = [parts]
        if not any(str(part).lower() in name for part in parts):
            return False

    if 'role' in criteria and role != criteria['role']:
        return False

    if 'role_contains' in criteria and str(criteria['role_contains']) not in role:
        return False

    if 'states_include' in criteria:
        required = set(str(state).lower() for state in criteria['states_include'])
        if not required.issubset(states):
            return False

    return True


def _find_send_button(platform: str):
    """Return the visible platform send button, if configured."""
    config = get_platform_config(platform)
    criteria = config.get('element_map', {}).get('send_button')
    if not isinstance(criteria, dict):
        return None

    doc = get_doc(force_refresh=True)
    if not doc:
        return None

    for element in find_elements(doc):
        if _match_element_criteria(element, criteria):
            return element
    return None


def _click_send_button(platform: str) -> bool:
    """Click the visible send button when keyboard submit is unreliable."""
    send_button = _find_send_button(platform)
    if not send_button:
        return False

    if send_button.get('atspi_obj') and atspi_click(send_button):
        logger.info("Clicked send button via AT-SPI")
        time.sleep(1.0)
        return True

    if inp.click_at(send_button['x'], send_button['y']):
        logger.info("Clicked send button via xdotool")
        time.sleep(1.0)
        return True

    return False


def _click_send_button_atspi(platform: str) -> bool:
    """Click the visible send button via AT-SPI only."""
    send_button = _find_send_button(platform)
    if not send_button or not send_button.get('atspi_obj'):
        return False

    if atspi_click(send_button):
        logger.info("Clicked send button via AT-SPI")
        time.sleep(1.0)
        return True
    return False


def _get_current_url() -> str:
    """Return the current document URL, if available."""
    doc = get_doc(force_refresh=True)
    if not doc:
        return ''
    return atspi.get_document_url(doc) or ''


def _is_chatgpt_conversation_url(url: str) -> bool:
    """Return True when ChatGPT has navigated to a conversation URL."""
    return 'chatgpt.com/c/' in (url or '').lower()


def _has_visible_stop_button(platform: str) -> bool:
    """Return True when the platform stop button is visible."""
    doc = get_doc(force_refresh=True)
    if not doc:
        return False
    stop_patterns = get_platform_config(platform).get('stop_patterns', ['stop'])
    return _scan_stop_button(doc, stop_patterns)


def _chatgpt_send_state(initial_url: str) -> dict:
    """Capture the observable ChatGPT send state after a submit attempt."""
    current_url = _get_current_url()
    send_visible = _find_send_button('chatgpt') is not None
    stop_visible = _has_visible_stop_button('chatgpt')
    return {
        'url': current_url,
        'url_changed_to_conversation': (
            not _is_chatgpt_conversation_url(initial_url)
            and _is_chatgpt_conversation_url(current_url)
        ),
        'send_visible': send_visible,
        'stop_visible': stop_visible,
    }


def _submit_chatgpt_prompt() -> bool:
    """Submit a ChatGPT prompt with Enter-first verification and fallback."""
    initial_url = _get_current_url()
    logger.info("ChatGPT send attempt 1/3: press Return")
    if not inp.press_key('Return', timeout=5):
        logger.error("Return keypress failed during ChatGPT submit")
        return False

    time.sleep(2.0)
    state = _chatgpt_send_state(initial_url)
    logger.info(
        "ChatGPT send state after Return: url=%s, redirected=%s, stop_visible=%s, send_visible=%s",
        state['url'] or '<none>',
        state['url_changed_to_conversation'],
        state['stop_visible'],
        state['send_visible'],
    )

    fallback_needed = (
        (not _is_chatgpt_conversation_url(initial_url) and not state['url_changed_to_conversation'])
        or (not state['stop_visible'] and state['send_visible'])
    )
    if fallback_needed:
        logger.warning("ChatGPT URL did not redirect to a conversation; trying send button fallback")
        if not _click_send_button_atspi('chatgpt'):
            logger.warning("ChatGPT AT-SPI send button fallback unavailable or failed")
        time.sleep(2.0)
        state = _chatgpt_send_state(initial_url)
        logger.info(
            "ChatGPT send state after AT-SPI click: url=%s, redirected=%s, stop_visible=%s, send_visible=%s",
            state['url'] or '<none>',
            state['url_changed_to_conversation'],
            state['stop_visible'],
            state['send_visible'],
        )

    if not state['stop_visible'] and state['send_visible']:
        logger.warning("ChatGPT send button still visible after Enter and fallback; trying Return once more")
        if not inp.press_key('Return', timeout=5):
            logger.error("Final Return keypress failed during ChatGPT submit")
            return False
        time.sleep(2.0)
        state = _chatgpt_send_state(initial_url)
        logger.info(
            "ChatGPT send state after final Return: url=%s, redirected=%s, stop_visible=%s, send_visible=%s",
            state['url'] or '<none>',
            state['url_changed_to_conversation'],
            state['stop_visible'],
            state['send_visible'],
        )

    if state['stop_visible']:
        return True

    logger.error(
        "ChatGPT submit did not verify send: redirected=%s, stop_visible=%s, send_visible=%s",
        state['url_changed_to_conversation'],
        state['stop_visible'],
        state['send_visible'],
    )
    return False


def _focus_input_field():
    """Focus the editable input field and return its element dict."""
    inp.focus_firefox()
    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(0.3)

    input_el = None
    for attempt in range(5):
        input_el = find_input_field()
        if input_el:
            break
        logger.info(f"Input not found, retry {attempt+1}/5...")
        time.sleep(2)

    if not input_el:
        logger.error("Input field not found")
        return None

    inp.click_at(input_el['x'], input_el['y'])
    time.sleep(0.3)
    obj = input_el.get('atspi_obj')
    if obj:
        try:
            comp = obj.get_component_iface()
            if comp:
                comp.grab_focus()
        except Exception:
            pass
    time.sleep(0.3)
    return input_el


def type_prompt(platform: str, message: str) -> bool:
    """Paste message into the input without sending it."""
    del platform
    input_el = _focus_input_field()
    if not input_el:
        return False

    if not inp.clipboard_paste(message):
        logger.error("Clipboard paste failed")
        return False
    time.sleep(0.5)

    logger.info(f"Prompt typed ({len(message)} chars)")
    return True


def submit_prompt(platform: str) -> bool:
    """Send the already-typed prompt."""
    input_el = _focus_input_field()
    if not input_el:
        return False

    if platform == 'chatgpt':
        if _submit_chatgpt_prompt():
            logger.info("Prompt submitted")
            return True
        return False

    # Claude can leave the send button active after attachments/mode changes
    # without submitting on Return. Prefer the explicit button there.
    if platform == 'claude' and _click_send_button(platform):
        logger.info("Prompt submitted")
        return True

    if not inp.press_key('Return', timeout=5):
        logger.error("Return keypress failed during submit")
        return False
    time.sleep(0.8)

    if platform == 'claude' and _find_send_button(platform):
        logger.warning("Claude send button still visible after Return; clicking fallback")
        if not _click_send_button(platform):
            logger.error("Claude send button fallback click failed")
            return False

    logger.info("Prompt submitted")
    return True


def send_prompt(platform: str, message: str) -> bool:
    """Backward-compatible helper: type then send."""
    if not type_prompt(platform, message):
        return False
    if not submit_prompt(platform):
        return False
    logger.info(f"Prompt sent ({len(message)} chars)")
    return True


def _normalize_mode_key(mode: str) -> str:
    """Normalize CLI mode strings to mode_guidance keys."""
    return (mode or '').strip().lower().replace(' ', '_')


def _execute_post_send_action(platform: str, mode: str = None) -> bool:
    """Run a configured post-send action for the selected mode, if any."""
    mode_key = _normalize_mode_key(mode)
    if not mode_key:
        return True

    mode_guidance = get_platform_config(platform).get('mode_guidance', {})
    mode_config = mode_guidance.get(mode_key, {})
    post_send_action = mode_config.get('post_send_action')
    if not isinstance(post_send_action, dict):
        return True

    if post_send_action.get('type') != 'click_button':
        logger.warning("Unsupported post_send_action type for %s/%s: %s",
                       platform, mode_key, post_send_action.get('type'))
        return False

    wait_before = float(post_send_action.get('wait_before', 0) or 0)
    if wait_before > 0:
        logger.info("Waiting %.1fs before post-send action", wait_before)
        time.sleep(wait_before)

    name_contains = post_send_action.get('name_contains')
    if isinstance(name_contains, str):
        patterns = [name_contains]
    else:
        patterns = [str(part) for part in (name_contains or []) if str(part).strip()]
    if not patterns:
        logger.error("post_send_action missing name_contains for %s/%s", platform, mode_key)
        return False

    inp.press_key('ctrl+End')
    time.sleep(1)
    inspect_result = send_to_worker(
        platform,
        {'cmd': 'inspect', 'scroll': 'bottom', 'fresh_session': False},
        timeout=30.0,
    )
    if not inspect_result.get('success'):
        logger.error("Post-send inspect failed for %s/%s: %s",
                     platform, mode_key, inspect_result.get('error'))
        return False

    patterns_lower = [part.lower() for part in patterns]
    controls = inspect_result.get('controls', [])
    button = next(
        (
            control for control in controls
            if 'button' in str(control.get('role', '')).lower()
            and any(part in str(control.get('name', '')).lower() for part in patterns_lower)
        ),
        None,
    )
    if not button:
        logger.error("Post-send button not found for %s/%s: %s", platform, mode_key, patterns)
        return False

    click_result = send_to_worker(
        platform,
        {'cmd': 'click', 'x': int(button['x']), 'y': int(button['y'])},
        timeout=30.0,
    )
    if click_result.get('error'):
        logger.error("Post-send click failed for %s/%s: %s",
                     platform, mode_key, click_result.get('error'))
        return False

    logger.info("Clicked Start research button for Gemini Deep Research")
    return True


def _verify_mode_selection(platform: str, target_mode: str, selection_result: dict = None) -> dict:
    """Verify the selected mode/model is visible in the AT-SPI tree."""
    verified = False
    verify_method = 'none'
    selection_result = selection_result or {}
    mode_key = _normalize_mode_key(target_mode)
    mode_guidance = get_platform_config(platform).get('mode_guidance', {})
    mode_config = mode_guidance.get(mode_key, {})
    verification_config = mode_config.get('verification', {})
    verification_check = verification_config.get('check')

    selected_item = selection_result.get('selected_item')
    if verification_check == 'completed_steps':
        completed_steps = selection_result.get('completed_steps') or []
        expected_steps = verification_config.get('expected_steps')
        if selection_result.get('success') and len(completed_steps) == expected_steps:
            logger.info("Mode verified via completed steps: %s/%s",
                        len(completed_steps), expected_steps)
            verified = True
            verify_method = 'completed_steps'
    elif selection_result.get('success') and selected_item:
        selected_name = selected_item.replace('_', ' ').lower().strip()
        target_lower = target_mode.replace('_', ' ').lower().strip()
        if target_lower in selected_name or selected_name.startswith(target_lower):
            logger.info(f"Mode verified via selection result: '{selected_item}'")
            verified = True
            verify_method = 'selection_result'

    if not verified:
        ff = find_firefox()
        doc = get_doc(force_refresh=True)
        if doc:
            from core.tree import find_elements as _fe
            _elements = _fe(doc)

            for e in _elements:
                ename = (e.get('name') or '').strip()
                if ename.lower().startswith('deselect') and \
                   target_mode.replace('_', ' ').lower() in ename.lower():
                    logger.info(f"Mode verified via deselect button: {ename}")
                    verified = True
                    verify_method = 'deselect_button'
                    break

            if not verified:
                for e in _elements:
                    ename = (e.get('name') or '').strip().lower()
                    if target_mode.replace('_', ' ').lower() in ename and \
                       'checked' in e.get('states', []):
                        logger.info(f"Mode verified via checked state: {e.get('name')}")
                        verified = True
                        verify_method = 'checked_state'
                        break

            if not verified:
                from core.mode_select import _verify_selection
                v = _verify_selection(platform, target_mode, ff, doc)
                if v.get('verified'):
                    logger.info(f"Mode verified via mode_select: {v.get('button_name')}")
                    verified = True
                    verify_method = 'mode_select_verify'

    return {'verified': verified, 'method': verify_method, 'mode': target_mode}


def _run_selection_step(platform: str, *, step_name: str, value: str,
                        result: dict, timeout: int) -> tuple[bool, int]:
    """Run and verify a single model or mode/tools selection step."""
    logger.info("Selecting %s=%s", step_name, value)
    sel_result = _select_mode_via_worker(
        platform,
        mode=value if step_name == 'mode' else None,
        model=value if step_name == 'model' else None,
        display=args.display,
    )

    if not sel_result.get('success'):
        logger.error("%s selection FAILED: %s", step_name.title(), sel_result.get('error'))
        logger.error("Available modes: %s", sel_result.get('available_modes', 'unknown'))
        result['error'] = f"{step_name}_selection_failed: {sel_result.get('error')}"
        result[f'{step_name}_selection'] = sel_result
        return False, timeout

    logger.info(
        "%s selected: %s",
        step_name.title(),
        sel_result.get('selected_mode', sel_result.get('matched', '?')),
    )
    if sel_result.get('timeout'):
        timeout = sel_result['timeout']
        logger.info("Timeout adjusted to %ss for this %s", timeout, step_name)
    result[f'{step_name}_selection'] = sel_result
    time.sleep(1)

    logger.info("Verifying %s in AT-SPI tree", step_name)
    selection_verification = _verify_mode_selection(platform, value, sel_result)
    if not selection_verification.get('verified'):
        logger.error("HARD STOP: %s '%s' NOT verified in AT-SPI tree.", step_name, value)
        result['error'] = f"{step_name}_not_verified: '{value}' not confirmed in AT-SPI tree"
        result['verify_method'] = selection_verification.get('method')
        return False, timeout

    logger.info("%s verification PASSED (%s)",
                step_name.title(), selection_verification.get('method'))
    result[f'{step_name}_verified'] = selection_verification
    return True, timeout


def validate_attachment_visible(platform: str, file_path: str,
                                attempts: int = 10, delay: float = 1.0) -> dict:
    """Confirm the uploaded file chip/indicator is visible in the AT-SPI tree."""
    basename = os.path.basename(file_path).lower()
    for attempt in range(attempts):
        from core.interact import invalidate_cache
        invalidate_cache(platform)
        doc = get_doc(force_refresh=True)
        if doc:
            for element in find_elements(doc):
                name = (element.get('name') or '').strip().lower()
                if basename and basename in name:
                    return {
                        'verified': True,
                        'method': 'file_name',
                        'name': element.get('name'),
                    }
        if _verify_attach_success(platform):
            return {
                'verified': True,
                'method': 'attach_indicator',
                'name': basename,
            }
        if attempt < attempts - 1:
            time.sleep(delay)

    return {'verified': False, 'method': 'none', 'name': basename}


def wait_for_response(platform: str, timeout: int = 3600) -> bool:
    """Wait for response via stop-button polling (same as hmm_bot)."""
    config = get_platform_config(platform)
    stop_patterns = config.get('stop_patterns', ['stop'])

    start = time.time()
    phase = 'waiting_for_start'
    poll_count = 0

    while time.time() - start < timeout:
        elapsed = time.time() - start
        doc = get_doc(force_refresh=True)
        if not doc:
            time.sleep(5)
            continue

        has_stop = _scan_stop_button(doc, stop_patterns)
        poll_count += 1

        if phase == 'waiting_for_start':
            if has_stop:
                logger.info("Stop button appeared -- AI generating")
                phase = 'generating'
            elif elapsed > 30:
                # Check copy button count as fallback
                elements = find_elements(doc)
                copy_btns = find_copy_buttons(elements)
                if len(copy_btns) > 0:
                    logger.info(f"Copy buttons found ({len(copy_btns)}) -- response may be ready")
                    return True
            if poll_count % 12 == 0:
                logger.info(f"Waiting for generation to start ({elapsed:.0f}s)")
            time.sleep(5)

        elif phase == 'generating':
            if not has_stop:
                time.sleep(2)
                doc2 = get_doc(force_refresh=True)
                if doc2 and not _scan_stop_button(doc2, stop_patterns):
                    logger.info(f"Response complete ({elapsed:.0f}s)")
                    return True
                else:
                    logger.info("Stop button reappeared -- still generating")
            if poll_count % 12 == 0:
                logger.info(f"Still generating ({elapsed:.0f}s)")
            time.sleep(5)

    logger.warning(f"Timeout after {timeout}s")
    return False


def _scan_stop_button(doc, stop_patterns: list) -> bool:
    """Scan AT-SPI tree for stop button."""
    def scan(obj, depth=0):
        if depth > 25:
            return False
        try:
            role = obj.get_role_name() or ''
            name = (obj.get_name() or '').strip().lower()
            if role in ('push button', 'button', 'toggle button'):
                if name and len(name) <= 50 and any(p in name for p in stop_patterns):
                    return True
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child and scan(child, depth + 1):
                    return True
        except Exception:
            pass
        return False
    return scan(doc)


def extract_response(platform: str) -> str:
    """Extract response via copy button (same pattern as hmm_bot)."""
    inp.focus_firefox()
    time.sleep(0.3)
    inp.press_key('ctrl+End')
    time.sleep(1)

    doc = get_doc(force_refresh=True)
    if not doc:
        return ''

    elements = find_elements(doc)
    copy_buttons = find_copy_buttons(elements)

    if not copy_buttons:
        for retry in range(3):
            time.sleep(2)
            inp.press_key('ctrl+End')
            time.sleep(1)
            doc = get_doc(force_refresh=True)
            if doc:
                elements = find_elements(doc)
                copy_buttons = find_copy_buttons(elements)
                if copy_buttons:
                    break

    if not copy_buttons:
        logger.error("No copy buttons found")
        return ''

    # Prefer response copy buttons, highest Y = most recent
    response_copy = [b for b in copy_buttons
                     if (b.get('name') or '').strip().lower() in ('copy', 'copy response')]
    candidates = response_copy or copy_buttons
    real_y = [b for b in candidates if b.get('y', 0) > 10]
    target = (real_y or candidates)[-1]

    # Kill stale xsel, clear clipboard, click copy
    subprocess.run(['pkill', '-9', 'xsel'], capture_output=True, timeout=3)
    time.sleep(0.3)

    if target.get('atspi_obj') and atspi_click(target):
        logger.info(f"Copy via AT-SPI at ({target['x']}, {target['y']})")
    else:
        inp.click_at(target['x'], target['y'])
        logger.info(f"Copy via xdotool at ({target['x']}, {target['y']})")

    for _ in range(6):
        time.sleep(0.5)
        content = clipboard.read()
        if content:
            return content

    # Retry with xdotool
    subprocess.run(['pkill', '-9', 'xsel'], capture_output=True, timeout=3)
    time.sleep(0.1)
    inp.click_at(target['x'], target['y'])
    for _ in range(6):
        time.sleep(0.5)
        content = clipboard.read()
        if content:
            return content

    logger.error("Clipboard empty after copy")
    return ''


def save_response(content: str, platform: str, output_path: str = None) -> str:
    """Save response to file."""
    if not output_path:
        downloads = os.path.expanduser('~/Downloads')
        os.makedirs(downloads, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(downloads, f'{platform}_{ts}.md')

    with open(output_path, 'w') as f:
        f.write(content)
    logger.info(f"Response saved to {output_path} ({len(content)} chars)")
    return output_path


def store_in_neo4j(platform: str, url: str, message: str, attachments: list,
                   response: str) -> dict:
    """Store prompt + response in Neo4j."""
    if not neo4j_client:
        return {}
    try:
        session_id = neo4j_client.get_or_create_session(platform, url or f'consultation://{platform}')
        user_msg_id = neo4j_client.add_message(session_id, 'user', message, attachments)
        resp_msg_id = neo4j_client.add_message(session_id, 'assistant', response[:5000])
        # Link response to prompt
        if user_msg_id and resp_msg_id:
            driver = neo4j_client.get_driver()
            if driver:
                with driver.session() as s:
                    s.run("""
                        MATCH (resp:Message {message_id: $rid})
                        MATCH (user:Message {message_id: $uid})
                        MERGE (resp)-[:RESPONDS_TO]->(user)
                    """, rid=resp_msg_id, uid=user_msg_id)
        logger.info(f"Neo4j stored: session={session_id}, user={user_msg_id}, response={resp_msg_id}")
        return {'session_id': session_id, 'user_message_id': user_msg_id,
                'response_message_id': resp_msg_id}
    except Exception as e:
        logger.warning(f"Neo4j storage failed: {e}")
        return {}


def store_in_isma(platform: str, url: str, message: str, response: str,
                  session_id: str = None):
    """Store in ISMA -- corpus file + tile + transcript."""
    # 1. Auto-ingest response (corpus + ISMA tile)
    if auto_ingest:
        try:
            auto_ingest(platform, response, url=url, session_id=session_id,
                        metadata={"source": "consultation", "role": "assistant"})
        except Exception as e:
            logger.warning(f"Response auto-ingest failed: {e}")

    # 2. Auto-ingest prompt
    if auto_ingest:
        try:
            auto_ingest(platform, message, url=url, session_id=session_id,
                        metadata={"source": "consultation", "role": "user"})
        except Exception as e:
            logger.warning(f"Prompt auto-ingest failed: {e}")

    # 3. Full exchange via orchestrator
    if ingest_transcript:
        try:
            ingest_transcript(
                platform=platform,
                response_content=response,
                package_metadata={
                    'batch_id': 'consultation',
                    'tile_hash': session_id or 'unknown',
                    'model': platform,
                },
                prompt_content=message,
            )
        except Exception as e:
            logger.warning(f"Transcript ingest failed: {e}")


# ---- Main flow ----

def main():
    platform = args.platform
    message = args.message
    attachments = args.attach
    timeout = args.timeout

    logger.info(f"Consultation: {platform}")
    logger.info(f"  Message: {message[:100]}{'...' if len(message) > 100 else ''}")
    logger.info(f"  Attachments: {len(attachments)} files")
    logger.info(f"  Display: {os.environ.get('DISPLAY', '(not set)')}")
    if args.session_url:
        logger.info(f"  Follow-up URL: {args.session_url}")
    if args.model:
        logger.info(f"  Model: {args.model}")
    if args.mode:
        logger.info(f"  Mode: {args.mode}")

    is_followup = bool(args.session_url)

    result = {
        'platform': platform, 'success': False,
        'message_length': len(message), 'attachments': attachments,
        'followup': is_followup,
    }
    if is_followup:
        result['session_url'] = args.session_url

    # ── Step 1: Navigation ─────────────────────────────────────────────
    if is_followup:
        logger.info("Step 1: Navigate to existing session (follow-up)")
        logger.info(f"  URL: {args.session_url}")
        if not navigate_to_session_url(platform, args.session_url):
            result['error'] = 'navigation_failed'
            print(json.dumps(result, indent=2))
            sys.exit(1)
    else:
        logger.info("Step 1: Navigate to fresh session")
        if not navigate_fresh_session(platform):
            result['error'] = 'navigation_failed'
            print(json.dumps(result, indent=2))
            sys.exit(1)

    # Step 1b: Clear stale cache and do fresh inspect.
    logger.info("Step 1b: Clear cache + fresh inspect after navigation")
    from core.interact import invalidate_cache
    invalidate_cache(platform)
    from tools.inspect import handle_inspect
    rc = get_redis()
    inspect_result = handle_inspect(platform, rc, scroll='bottom', fresh_session=False)
    if not inspect_result.get('success'):
        logger.warning(f"Post-navigation inspect failed: {inspect_result.get('error')}")
        # Non-fatal — attach will try its own discovery

    # ── Step 1c: Git connector (if --git-repo specified) ───────────────────
    if args.git_repo:
        logger.info(f"Step 1c: Connecting git repo: {args.git_repo}")
        if not connect_git_repo(platform, args.git_repo):
            logger.warning("Git connector failed — continuing without it")
        else:
            result['git_repo'] = args.git_repo
        time.sleep(1)

    pkg_path = None
    if is_followup:
        if attachments:
            logger.info(f"Step 4 prep: Packaging {len(attachments)} follow-up file(s) (no identity)")
            if len(attachments) > 1:
                pkg_path = _consolidate_attachments(attachments, platform)
            else:
                pkg_path = attachments[0]
        else:
            logger.info("Step 4 prep: No attachments for follow-up (skipped)")
    else:
        logger.info("Step 4 prep: Build attachment package")
        all_files = _prepend_identity_files(attachments, platform)
        if len(all_files) > 1:
            pkg_path = _consolidate_attachments(all_files, platform)
        elif len(all_files) == 1:
            pkg_path = all_files[0]
    logger.info("Resolved universal step order for %s: %s",
                platform, " -> ".join(DEFAULT_STEP_ORDER))

    logger.info("Step 2: Model selection")
    if is_followup and not args.model:
        logger.info("Step 2: Model selection skipped (follow-up)")
    elif not args.model:
        logger.info("Step 2: Model selection skipped (not requested)")
    else:
        ok, timeout = _run_selection_step(
            platform,
            step_name='model',
            value=args.model,
            result=result,
            timeout=timeout,
        )
        if not ok:
            print(json.dumps(result, indent=2))
            sys.exit(1)

    logger.info("Step 3: Mode/tools selection")
    if is_followup and not args.mode:
        logger.info("Step 3: Mode/tools selection skipped (follow-up)")
    elif not args.mode:
        logger.info("Step 3: Mode/tools selection skipped (not requested)")
    else:
        ok, timeout = _run_selection_step(
            platform,
            step_name='mode',
            value=args.mode,
            result=result,
            timeout=timeout,
        )
        if not ok:
            print(json.dumps(result, indent=2))
            sys.exit(1)

    if pkg_path and os.path.isfile(pkg_path):
        logger.info("Step 4: Attaching %s", os.path.basename(pkg_path))
        if not attach_file(platform, pkg_path):
            result['error'] = 'attach_failed'
            print(json.dumps(result, indent=2))
            sys.exit(1)
        result['attachment'] = pkg_path

        logger.info("Step 4b: Validating uploaded file chip/indicator")
        attachment_validation = validate_attachment_visible(platform, pkg_path)
        result['attachment_validation'] = attachment_validation
        if not attachment_validation.get('verified'):
            logger.error("HARD STOP: attached file not visible in AT-SPI tree after upload")
            result['error'] = 'attachment_not_verified'
            print(json.dumps(result, indent=2))
            sys.exit(1)

        logger.info("Attachment verification PASSED (%s)",
                    attachment_validation.get('method'))

        if platform == 'perplexity' and args.mode:
            target_mode = args.mode.replace('_', ' ').lower().strip()
            if 'deep research' in target_mode:
                logger.info("Step 4c: Re-check Perplexity Deep Research after attach")
                mode_verification = _verify_mode_selection(
                    platform, args.mode, result.get('mode_selection', {})
                )
                if not mode_verification.get('verified'):
                    logger.warning("Perplexity Deep Research no longer verified after attach; reselecting")
                    ok, timeout = _run_selection_step(
                        platform,
                        step_name='mode',
                        value=args.mode,
                        result=result,
                        timeout=timeout,
                    )
                    if not ok:
                        print(json.dumps(result, indent=2))
                        sys.exit(1)
                    mode_verification = result.get('mode_verified', {})
                    if not mode_verification.get('verified'):
                        result['error'] = f"mode_not_verified: '{args.mode}' not confirmed after attach"
                        result['verify_method'] = mode_verification.get('method')
                        print(json.dumps(result, indent=2))
                        sys.exit(1)
                result['mode_verified_after_attach'] = mode_verification
    else:
        logger.info("Step 4: No attachments to add (skipped)")

    logger.info("Step 5: Type prompt into input")
    if not type_prompt(platform, message):
        result['error'] = 'prompt_type_failed'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    logger.info("Step 6: Send prompt")
    if not submit_prompt(platform):
        result['error'] = 'send_failed'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    logger.info("Step 6a: Post-send action check")
    if not _execute_post_send_action(platform, args.mode):
        result['error'] = 'post_send_action_failed'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Step 6b: Register monitor session + Neo4j storage
    url = args.session_url
    if not url:
        doc = get_doc()
        if doc:
            url = atspi.get_document_url(doc)
    session_id = message_id = None
    if not args.no_neo4j and neo4j_client and url:
        try:
            session_id = neo4j_client.get_or_create_session(platform, url)
            message_id = neo4j_client.add_message(session_id, 'user', message,
                                                   attachments)
        except Exception as e:
            logger.warning(f"Neo4j storage failed: {e}")

    import uuid
    monitor_id = str(uuid.uuid4())[:8]
    rc = get_redis()
    if rc:
        rc.setex(
            node_key(f"pending_prompt:{platform}"), 3600,
            json.dumps({
                'content': message, 'attachments': attachments or [],
                'session_url': url, 'session_id': session_id,
                'message_id': message_id,
            })
        )
        from tools.send import register_monitor_session, _ensure_central_monitor
        display = os.environ.get('DISPLAY', ':0')
        _ensure_central_monitor(display)
        reg = register_monitor_session(
            platform=platform, monitor_id=monitor_id, url=url,
            redis_client=rc, session_id=session_id,
            user_message_id=message_id, timeout=timeout,
        )
        result['monitor'] = {'id': monitor_id, 'registered': reg.get('registered', False)}
        logger.info(f"Monitor session registered: {monitor_id}")

    if getattr(args, 'async_send', False):
        result['success'] = True
        result['mode'] = 'async'
        result['url'] = url
        result['neo4j'] = {'session_id': session_id, 'message_id': message_id}
        result['info'] = (f"Message sent. Monitor {monitor_id} will detect completion. "
                          f"Extract with: taey_quick_extract(platform='{platform}', complete=True)")
        logger.info("Async mode: returning after send. Monitor will detect completion.")
        print(json.dumps(result, indent=2))
        sys.exit(0)

    # Step 7: Wait for response
    logger.info("Step 7: Waiting for response...")
    if not wait_for_response(platform, timeout=timeout):
        result['error'] = 'response_timeout'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    time.sleep(2)

    # Step 8: Extract response
    logger.info("Step 8: Extracting response")
    content = extract_response(platform)
    if not content:
        result['error'] = 'extract_failed'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    logger.info(f"Extracted {len(content)} chars")

    # Step 9: Save response
    output_path = save_response(content, platform, args.output)
    result['output_path'] = output_path
    result['content_length'] = len(content)

    # Step 10: Store in Neo4j
    if not args.no_neo4j:
        logger.info("Step 10: Storing in Neo4j")
        url = None
        doc = get_doc()
        if doc:
            url = atspi.get_document_url(doc)
        neo4j_result = store_in_neo4j(platform, url, message,
                                       attachments, content)
        result['neo4j'] = neo4j_result

    # Step 11: ISMA ingestion
    if not args.no_isma:
        logger.info("Step 11: ISMA ingestion")
        url = None
        doc = get_doc()
        if doc:
            url = atspi.get_document_url(doc)
        store_in_isma(platform, url, message, content,
                      session_id=result.get('neo4j', {}).get('session_id'))

    result['success'] = True
    logger.info(f"Consultation complete: {len(content)} chars extracted")

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
