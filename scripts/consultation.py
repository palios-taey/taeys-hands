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
    return parser.parse_args()


args = parse_args()
setup_env(display=args.display, platform=args.platform)

# NOW import project modules
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Load .env
_env_path = os.path.join(_ROOT, '.env')
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

# Clear _PLATFORM_DISPLAYS (populated at import time from .env)
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core.platforms import _PLATFORM_DISPLAYS
_PLATFORM_DISPLAYS.clear()

from core import atspi, input as inp, clipboard
from core.config import get_platform_config, get_attach_method
from core.tree import find_elements, find_copy_buttons, find_menu_items
from core.interact import atspi_click
from tools.attach import handle_attach, _close_stale_file_dialogs
from tools.plan import _prepend_identity_files, _consolidate_attachments
from storage.redis_pool import get_client as get_redis, node_key

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

# Logging
logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format='%(asctime)s [consultation] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('consultation')


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


def navigate_fresh_session(platform: str) -> bool:
    """Navigate to fresh session URL."""
    from core.platforms import BASE_URLS
    url = BASE_URLS.get(platform)
    if not url:
        logger.error(f"No base URL for {platform}")
        return False

    _close_stale_file_dialogs()
    inp.focus_firefox()
    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(0.2)
    inp.press_key('ctrl+l')
    time.sleep(0.3)
    inp.press_key('ctrl+a')
    time.sleep(0.1)
    inp.type_text(url, delay_ms=5)
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(8)

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


def send_prompt(platform: str, message: str) -> bool:
    """Send message via clipboard paste + Enter."""
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

    inp.clipboard_paste(message)
    time.sleep(0.5)
    inp.press_key('Return')
    time.sleep(1.0)

    logger.info(f"Prompt sent ({len(message)} chars)")
    return True


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
                if name and len(name) <= 50 and name in stop_patterns:
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
    if args.model:
        logger.info(f"  Model: {args.model}")
    if args.mode:
        logger.info(f"  Mode: {args.mode}")

    result = {
        'platform': platform, 'success': False,
        'message_length': len(message), 'attachments': attachments,
    }

    # Step 1: Navigate to fresh session
    logger.info("Step 1: Navigate to fresh session")
    if not navigate_fresh_session(platform):
        result['error'] = 'navigation_failed'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Step 1b: Clear stale cache and do fresh inspect.
    # Navigation rebuilds the page — cached atspi_obj references from
    # before navigation are stale (point to destroyed DOM nodes).
    # The element cache may have BOTH old and new entries after inspect.
    # Clear it first so only fresh entries exist.
    logger.info("Step 1b: Clear cache + fresh inspect after navigation")
    from core.interact import invalidate_cache
    invalidate_cache(platform)
    from tools.inspect import handle_inspect
    rc = get_redis()
    inspect_result = handle_inspect(platform, rc, scroll='bottom', fresh_session=False)
    if not inspect_result.get('success'):
        logger.warning(f"Post-navigation inspect failed: {inspect_result.get('error')}")
        # Non-fatal — attach will try its own discovery

    # Step 2: Build and attach package (identity + user files)
    if attachments or True:  # Always build package (identity files)
        logger.info("Step 2: Build attachment package")
        all_files = _prepend_identity_files(attachments, platform)
        if len(all_files) > 1:
            pkg_path = _consolidate_attachments(all_files, platform)
        elif len(all_files) == 1:
            pkg_path = all_files[0]
        else:
            pkg_path = None

        if pkg_path and os.path.isfile(pkg_path):
            logger.info(f"Step 2b: Attaching {os.path.basename(pkg_path)}")
            if not attach_file(platform, pkg_path):
                result['error'] = 'attach_failed'
                print(json.dumps(result, indent=2))
                sys.exit(1)
            time.sleep(3)  # Wait for upload processing
            result['attachment'] = pkg_path

    # Step 3: Model/mode selection (if requested)
    if args.model or args.mode:
        logger.info(f"Step 3: Selecting model={args.model} mode={args.mode}")
        from core.mode_select import select_mode_model
        ff = find_firefox()
        doc = get_doc(force_refresh=True)
        sel_result = select_mode_model(
            platform, mode=args.mode, model=args.model,
            doc=doc, firefox=ff,
        )
        if sel_result.get('success'):
            logger.info(f"Mode/model selected: {sel_result.get('selected_mode', sel_result.get('matched', '?'))}")
            if sel_result.get('timeout'):
                timeout = sel_result['timeout']
                logger.info(f"Timeout adjusted to {timeout}s for this mode")
            result['mode_selection'] = sel_result
        else:
            logger.warning(f"Mode/model selection failed: {sel_result.get('error')}")
            logger.warning(f"Available modes: {sel_result.get('available_modes', 'unknown')}")
            result['mode_selection'] = sel_result
            # Don't fail -- proceed with default mode
        time.sleep(1)

    # Step 4: Send prompt
    logger.info("Step 4: Send prompt")
    if not send_prompt(platform, message):
        result['error'] = 'send_failed'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Step 5: Wait for response
    logger.info("Step 5: Waiting for response...")
    if not wait_for_response(platform, timeout=timeout):
        result['error'] = 'response_timeout'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    time.sleep(2)  # Let response fully render

    # Step 6: Extract response
    logger.info("Step 6: Extracting response")
    content = extract_response(platform)
    if not content:
        result['error'] = 'extract_failed'
        print(json.dumps(result, indent=2))
        sys.exit(1)

    logger.info(f"Extracted {len(content)} chars")

    # Step 7: Save response
    output_path = save_response(content, platform, args.output)
    result['output_path'] = output_path
    result['content_length'] = len(content)

    # Step 8: Store in Neo4j
    if not args.no_neo4j:
        logger.info("Step 8: Storing in Neo4j")
        url = None
        doc = get_doc()
        if doc:
            url = atspi.get_document_url(doc)
        neo4j_result = store_in_neo4j(platform, url, message,
                                       attachments, content)
        result['neo4j'] = neo4j_result

    # Step 9: ISMA ingestion
    if not args.no_isma:
        logger.info("Step 9: ISMA ingestion")
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
