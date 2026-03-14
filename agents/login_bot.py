#!/usr/bin/env python3
"""login_bot.py — Automated login for AI chat platforms via AT-SPI.

Handles login flows for ChatGPT, Gemini, Grok, Perplexity, and Claude.
Uses AT-SPI element discovery + xdotool for credential entry.

After successful login, syncs cookies to all worker nodes.

Usage:
    # Login to all platforms on current display
    python3 agents/login_bot.py --all

    # Login to specific platform
    python3 agents/login_bot.py --platform chatgpt

    # Login and sync cookies to workers
    python3 agents/login_bot.py --platform chatgpt --sync

    # Check login status only (no credential entry)
    python3 agents/login_bot.py --check

    # Sync cookies from this machine to workers (no login)
    python3 agents/login_bot.py --sync-only

Environment:
    DISPLAY          — X11 display (default: :0)
    SECRETS_HOST     — host with secrets file (default: mira)
    SECRETS_PATH     — path to secrets JSON (default: ~/palios-taey-secrets.json)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time

os.environ.setdefault('DISPLAY', ':0')

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import atspi, clipboard
from core import input as inp
from core.tree import find_elements, filter_useful_elements

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('login_bot')

SECRETS_HOST = os.environ.get('SECRETS_HOST', 'mira')
SECRETS_PATH = os.environ.get('SECRETS_PATH', '~/palios-taey-secrets.json')

# Worker nodes to sync cookies to
WORKER_NODES = ['spark-155d', 'spark-cf52', 'thor', 'jetson']

# Login URLs per platform
LOGIN_URLS = {
    'chatgpt': 'https://chatgpt.com/',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://x.com/i/grok',
    'perplexity': 'https://www.perplexity.ai/',
    'claude': 'https://claude.ai/',
}

# Platform -> account mapping
PLATFORM_ACCOUNTS = {
    'chatgpt': 'personal',       # jesselarose@gmail.com
    'claude': 'personal',        # jesselarose@gmail.com
    'gemini': 'taey_ai',         # jesse@taey.ai
    'grok': 'taey_ai',           # jesse@taey.ai
    'perplexity': 'taey_ai',     # jesse@taey.ai
}


def load_secrets() -> dict:
    """Load secrets from remote host."""
    try:
        r = subprocess.run(
            ['ssh', SECRETS_HOST, f'cat {SECRETS_PATH}'],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
    except Exception as e:
        logger.error(f"Failed to load secrets: {e}")
    return {}


def get_credentials(platform: str, secrets: dict) -> tuple:
    """Get email and password for a platform."""
    acct_key = PLATFORM_ACCOUNTS.get(platform)
    if not acct_key:
        return None, None
    accounts = secrets.get('email_accounts', {})
    acct = accounts.get(acct_key, {})
    return acct.get('email'), acct.get('password')


def navigate_to(url: str) -> bool:
    """Navigate current Firefox tab to URL."""
    if not inp.focus_firefox():
        logger.error("Could not focus Firefox")
        return False
    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(0.2)
    inp.press_key('ctrl+l')
    time.sleep(0.3)
    inp.press_key('ctrl+a')
    time.sleep(0.1)
    inp.type_text(url, delay_ms=10)
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(5)
    return True


def scan_page(timeout_sec: int = 10) -> list:
    """Scan current page AT-SPI tree and return elements."""
    desktop = atspi.Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        name = app.get_name() or ''
        if 'firefox' not in name.lower() and 'Mozilla' not in name:
            continue
        for j in range(app.get_child_count()):
            frame = app.get_child_at_index(j)
            if frame and frame.get_role_name() == 'frame':
                # Find the document within
                for k in range(frame.get_child_count()):
                    child = frame.get_child_at_index(k)
                    role = child.get_role_name() if child else ''
                    if role in ('document web', 'document'):
                        elements = find_elements(child)
                        return filter_useful_elements(elements)
    return []


def find_element_by_text(elements: list, text: str, role: str = None) -> dict:
    """Find element matching text (case-insensitive substring)."""
    text_lower = text.lower()
    for el in elements:
        el_name = (el.get('name', '') or '').lower()
        el_role = el.get('role', '')
        if text_lower in el_name:
            if role is None or role in el_role:
                return el
    return None


def find_element_by_role(elements: list, role: str, states: list = None) -> dict:
    """Find element by role (and optionally required states)."""
    for el in elements:
        if role in el.get('role', ''):
            if states:
                el_states = el.get('states', [])
                if all(s in el_states for s in states):
                    return el
            else:
                return el
    return None


def find_input_field(elements: list) -> dict:
    """Find an editable input field."""
    for el in elements:
        states = el.get('states', [])
        role = el.get('role', '')
        if 'editable' in states and ('entry' in role or 'text' in role or 'section' in role):
            return el
    return None


def click_element(el: dict) -> bool:
    """Click an element using its coordinates."""
    x, y = el.get('x', 0), el.get('y', 0)
    if x <= 0 or y <= 0:
        return False
    # Try AT-SPI do_action first
    atspi_obj = el.get('atspi_obj')
    if atspi_obj:
        try:
            iface = atspi_obj.get_action_iface()
            if iface and iface.get_n_actions() > 0:
                iface.do_action(0)
                return True
        except Exception:
            pass
    # Fallback to xdotool
    inp.click_at(x, y)
    return True


def type_into_field(text: str, use_clipboard: bool = True):
    """Type text into the focused field."""
    if use_clipboard:
        clipboard.write(text)
        time.sleep(0.2)
        inp.press_key('ctrl+v')
        time.sleep(0.3)
        clipboard.clear()
    else:
        inp.type_text(text, delay_ms=20)


def check_login_status(platform: str) -> str:
    """Check if platform is logged in. Returns 'logged_in', 'login_page', or 'unknown'."""
    url = LOGIN_URLS.get(platform)
    if not url:
        return 'unknown'

    navigate_to(url)
    time.sleep(3)
    elements = scan_page()

    if not elements:
        return 'unknown'

    # Dump element names for debugging
    names = [el.get('name', '') for el in elements[:30]]
    logger.debug(f"[{platform}] Top elements: {names}")

    # Check for login indicators
    login_keywords = ['log in', 'login', 'sign in', 'sign up', 'get started',
                      'create account', 'welcome back', 'continue with google',
                      'continue with email']
    logged_in_keywords = ['new chat', 'send message', 'message', 'ask anything',
                          'start a new chat', 'how can i help']

    all_text = ' '.join(str(el.get('name', '')) for el in elements).lower()

    has_login = any(kw in all_text for kw in login_keywords)
    has_chat = any(kw in all_text for kw in logged_in_keywords)

    if has_chat and not has_login:
        return 'logged_in'
    elif has_login:
        return 'login_page'
    else:
        return 'unknown'


# ── Platform-specific login flows ────────────────────────────────

def login_chatgpt(email: str, password: str) -> bool:
    """Login to ChatGPT via email/password."""
    logger.info("[chatgpt] Starting login flow...")

    # Navigate to login page
    navigate_to('https://chatgpt.com/auth/login')
    time.sleep(3)

    elements = scan_page()

    # Look for "Log in" button
    login_btn = find_element_by_text(elements, 'Log in', role='button')
    if login_btn:
        logger.info("[chatgpt] Clicking 'Log in' button...")
        click_element(login_btn)
        time.sleep(3)
        elements = scan_page()

    # Look for "Continue with Google" or email entry
    google_btn = find_element_by_text(elements, 'Continue with Google')
    email_input = find_input_field(elements)

    if google_btn:
        logger.info("[chatgpt] Clicking 'Continue with Google'...")
        click_element(google_btn)
        time.sleep(4)
        return _handle_google_oauth(email, password)
    elif email_input:
        logger.info("[chatgpt] Entering email...")
        click_element(email_input)
        time.sleep(0.3)
        type_into_field(email)
        time.sleep(0.3)

        # Find and click Continue
        elements = scan_page()
        continue_btn = find_element_by_text(elements, 'Continue', role='button')
        if continue_btn:
            click_element(continue_btn)
            time.sleep(3)

        # Password page
        elements = scan_page()
        pw_input = find_input_field(elements)
        if pw_input:
            logger.info("[chatgpt] Entering password...")
            click_element(pw_input)
            time.sleep(0.3)
            type_into_field(password)
            time.sleep(0.3)

            continue_btn = find_element_by_text(elements, 'Continue', role='button')
            if continue_btn:
                click_element(continue_btn)
                time.sleep(5)

        return _verify_login('chatgpt')
    else:
        logger.warning("[chatgpt] Could not find login form")
        _dump_elements(elements, 'chatgpt')
        return False


def login_gemini(email: str, password: str) -> bool:
    """Login to Gemini (Google account)."""
    logger.info("[gemini] Starting login flow...")

    navigate_to('https://gemini.google.com/app')
    time.sleep(4)

    elements = scan_page()

    # Check if already logged in
    if find_element_by_text(elements, 'Send message') or find_element_by_text(elements, 'entry'):
        logger.info("[gemini] Already logged in")
        return True

    # Look for sign in button
    signin_btn = find_element_by_text(elements, 'Sign in', role='button')
    if signin_btn:
        logger.info("[gemini] Clicking 'Sign in'...")
        click_element(signin_btn)
        time.sleep(4)
        return _handle_google_oauth(email, password)

    # May be directly on Google login
    return _handle_google_oauth(email, password)


def login_grok(email: str, password: str) -> bool:
    """Login to Grok (via X/Twitter)."""
    logger.info("[grok] Starting login flow...")

    navigate_to('https://x.com/i/grok')
    time.sleep(4)

    elements = scan_page()

    # Check if already logged in
    if find_element_by_text(elements, 'Ask anything'):
        logger.info("[grok] Already logged in")
        return True

    # Look for sign in / log in
    signin_btn = (find_element_by_text(elements, 'Sign in') or
                  find_element_by_text(elements, 'Log in'))
    if signin_btn:
        logger.info("[grok] Clicking sign in...")
        click_element(signin_btn)
        time.sleep(3)
        elements = scan_page()

    # X/Twitter login: email -> Next -> password -> Log in
    email_input = find_input_field(elements)
    if email_input:
        logger.info("[grok] Entering email/username...")
        click_element(email_input)
        time.sleep(0.3)
        type_into_field(email)
        time.sleep(0.3)

        next_btn = find_element_by_text(elements, 'Next', role='button')
        if next_btn:
            click_element(next_btn)
            time.sleep(3)

        # Password page
        elements = scan_page()
        pw_input = find_input_field(elements)
        if pw_input:
            logger.info("[grok] Entering password...")
            click_element(pw_input)
            time.sleep(0.3)
            type_into_field(password)
            time.sleep(0.3)

            login_btn = find_element_by_text(elements, 'Log in', role='button')
            if login_btn:
                click_element(login_btn)
                time.sleep(5)

        return _verify_login('grok')
    else:
        logger.warning("[grok] Could not find login form")
        _dump_elements(elements, 'grok')
        return False


def login_perplexity(email: str, password: str) -> bool:
    """Login to Perplexity."""
    logger.info("[perplexity] Starting login flow...")

    navigate_to('https://www.perplexity.ai/')
    time.sleep(4)

    elements = scan_page()

    # Check if logged in
    if find_element_by_text(elements, 'Ask anything'):
        logger.info("[perplexity] Already logged in")
        return True

    # Look for sign in
    signin = (find_element_by_text(elements, 'Sign In') or
              find_element_by_text(elements, 'Log In'))
    if signin:
        logger.info("[perplexity] Clicking sign in...")
        click_element(signin)
        time.sleep(3)
        elements = scan_page()

    # Look for Google SSO
    google_btn = find_element_by_text(elements, 'Continue with Google')
    if google_btn:
        logger.info("[perplexity] Using Google SSO...")
        click_element(google_btn)
        time.sleep(4)
        return _handle_google_oauth(email, password)

    # Email entry
    email_input = find_input_field(elements)
    if email_input:
        logger.info("[perplexity] Entering email...")
        click_element(email_input)
        time.sleep(0.3)
        type_into_field(email)
        time.sleep(0.3)
        inp.press_key('Return')
        time.sleep(3)
        return _verify_login('perplexity')

    logger.warning("[perplexity] Could not find login form")
    _dump_elements(elements, 'perplexity')
    return False


def login_claude(email: str, password: str) -> bool:
    """Login to Claude.ai."""
    logger.info("[claude] Starting login flow...")

    navigate_to('https://claude.ai/')
    time.sleep(4)

    elements = scan_page()

    # Check if logged in
    if find_element_by_text(elements, 'Send') or find_element_by_text(elements, 'message'):
        logger.info("[claude] Already logged in")
        return True

    # Look for "Continue with Google" or email entry
    google_btn = find_element_by_text(elements, 'Continue with Google')
    if google_btn:
        logger.info("[claude] Using Google SSO...")
        click_element(google_btn)
        time.sleep(4)
        return _handle_google_oauth(email, password)

    # Email entry
    email_input = find_input_field(elements)
    if email_input:
        logger.info("[claude] Entering email...")
        click_element(email_input)
        time.sleep(0.3)
        type_into_field(email)
        time.sleep(0.3)

        continue_btn = find_element_by_text(elements, 'Continue', role='button')
        if continue_btn:
            click_element(continue_btn)
            time.sleep(3)

        # Claude uses magic link or Google — may need to handle that
        elements = scan_page()
        google_btn = find_element_by_text(elements, 'Continue with Google')
        if google_btn:
            click_element(google_btn)
            time.sleep(4)
            return _handle_google_oauth(email, password)

        return _verify_login('claude')

    logger.warning("[claude] Could not find login form")
    _dump_elements(elements, 'claude')
    return False


# ── Google OAuth flow ─────────────────────────────────────────────

def _handle_google_oauth(email: str, password: str) -> bool:
    """Handle Google OAuth popup/redirect flow.

    Google login flow:
    1. Email entry -> Next
    2. Password entry -> Next
    3. 2FA prompt (if enabled) -> need manual intervention or TOTP
    """
    logger.info("[google] Handling Google OAuth...")
    time.sleep(3)

    for attempt in range(3):
        elements = scan_page()
        all_names = [el.get('name', '') for el in elements]
        logger.debug(f"[google] Attempt {attempt+1} elements: {all_names[:20]}")

        # Step 1: Email entry
        email_input = find_input_field(elements)
        if email_input:
            name = (email_input.get('name', '') or '').lower()
            if 'email' in name or 'identifier' in name or 'phone' in name or not name:
                logger.info("[google] Entering email...")
                click_element(email_input)
                time.sleep(0.3)
                inp.press_key('ctrl+a')
                time.sleep(0.1)
                type_into_field(email)
                time.sleep(0.3)

                next_btn = find_element_by_text(elements, 'Next', role='button')
                if next_btn:
                    click_element(next_btn)
                else:
                    inp.press_key('Return')
                time.sleep(4)
                continue

            # Step 2: Password entry
            elif 'password' in name or 'passwd' in name:
                logger.info("[google] Entering password...")
                click_element(email_input)
                time.sleep(0.3)
                type_into_field(password)
                time.sleep(0.3)

                next_btn = find_element_by_text(elements, 'Next', role='button')
                if next_btn:
                    click_element(next_btn)
                else:
                    inp.press_key('Return')
                time.sleep(5)

                # Check for 2FA
                elements = scan_page()
                if _check_2fa(elements):
                    logger.warning("[google] 2FA required — waiting for manual approval...")
                    return _wait_for_2fa(timeout_sec=120)

                return True

        # Check if we're past login
        if find_element_by_text(elements, 'Send message') or \
           find_element_by_text(elements, 'New chat') or \
           find_element_by_text(elements, 'Ask anything'):
            logger.info("[google] Login successful (chat page detected)")
            return True

        time.sleep(3)

    logger.error("[google] OAuth flow did not complete after 3 attempts")
    return False


def _check_2fa(elements: list) -> bool:
    """Check if page is showing 2FA prompt."""
    two_fa_keywords = ['2-step', 'verification', 'verify', 'authenticator',
                       'security code', 'confirm it', 'check your phone',
                       'approve the sign']
    all_text = ' '.join(str(el.get('name', '')) for el in elements).lower()
    return any(kw in all_text for kw in two_fa_keywords)


def _wait_for_2fa(timeout_sec: int = 120) -> bool:
    """Wait for manual 2FA approval (Google prompt on phone)."""
    logger.info(f"[2FA] Waiting up to {timeout_sec}s for approval...")
    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(5)
        elements = scan_page()
        # Check if we got past 2FA
        if find_element_by_text(elements, 'Send message') or \
           find_element_by_text(elements, 'New chat') or \
           find_element_by_text(elements, 'Ask anything') or \
           find_element_by_text(elements, 'Search'):
            logger.info("[2FA] Login complete after 2FA")
            return True
        if not _check_2fa(elements):
            # No more 2FA prompt — check if we're logged in
            email_input = find_input_field(elements)
            if not email_input:
                logger.info("[2FA] 2FA prompt gone, likely logged in")
                return True
    logger.error("[2FA] Timed out waiting for 2FA approval")
    return False


def _verify_login(platform: str) -> bool:
    """Verify login was successful by checking page state."""
    time.sleep(3)
    elements = scan_page()
    logged_in_keywords = ['new chat', 'send message', 'message', 'ask anything',
                          'start a new chat', 'how can i help', 'entry']
    all_text = ' '.join(str(el.get('name', '')) for el in elements).lower()
    for kw in logged_in_keywords:
        if kw in all_text:
            logger.info(f"[{platform}] Login verified (found: {kw})")
            return True
    logger.warning(f"[{platform}] Could not verify login")
    _dump_elements(elements, platform)
    return False


def _dump_elements(elements: list, platform: str, max_items: int = 30):
    """Dump elements for debugging."""
    logger.info(f"[{platform}] Page elements ({len(elements)} total):")
    for el in elements[:max_items]:
        name = el.get('name', '')[:60]
        role = el.get('role', '')
        states = ','.join(el.get('states', [])[:3])
        x, y = el.get('x', 0), el.get('y', 0)
        logger.info(f"  [{role}] '{name}' ({x},{y}) {{{states}}}")


# ── Cookie sync ──────────────────────────────────────────────────

def find_firefox_profile() -> str:
    """Find the active Firefox profile directory on this machine."""
    for base in [
        os.path.expanduser('~/.config/mozilla/firefox'),
        os.path.expanduser('~/.mozilla/firefox'),
    ]:
        profiles_ini = os.path.join(base, 'profiles.ini')
        if os.path.exists(profiles_ini):
            with open(profiles_ini) as f:
                content = f.read()
            for line in content.splitlines():
                if line.startswith('Default=') and '/' in line:
                    rel = line.split('=', 1)[1]
                    path = os.path.join(base, rel)
                    if os.path.isdir(path):
                        return path
            # Fallback: find any profile with cookies
            for entry in os.listdir(base):
                path = os.path.join(base, entry)
                if os.path.isfile(os.path.join(path, 'cookies.sqlite')):
                    return path
    return ''


def sync_cookies(target_nodes: list = None) -> dict:
    """Sync cookies from this machine's Firefox profile to worker nodes.

    Returns dict of {node: 'ok'|'error message'}.
    """
    if target_nodes is None:
        target_nodes = WORKER_NODES

    source_profile = find_firefox_profile()
    if not source_profile:
        logger.error("No Firefox profile found on this machine")
        return {n: 'no source profile' for n in target_nodes}

    cookies_file = os.path.join(source_profile, 'cookies.sqlite')
    if not os.path.exists(cookies_file):
        logger.error(f"No cookies.sqlite in {source_profile}")
        return {n: 'no cookies.sqlite' for n in target_nodes}

    logger.info(f"Source: {cookies_file}")
    results = {}

    for node in target_nodes:
        try:
            # Find remote profile
            r = subprocess.run(
                ['ssh', node, 'python3 -c "'
                 'import os\n'
                 'for b in [os.path.expanduser(\"~/.config/mozilla/firefox\"), '
                 'os.path.expanduser(\"~/.mozilla/firefox\")]:\n'
                 '  pi = os.path.join(b, \"profiles.ini\")\n'
                 '  if os.path.exists(pi):\n'
                 '    for line in open(pi):\n'
                 '      if line.startswith(\"Default=\") and \"/\" in line:\n'
                 '        p = os.path.join(b, line.strip().split(\"=\",1)[1])\n'
                 '        if os.path.isdir(p): print(p); break\n'
                 '    break\n'
                 '"'],
                capture_output=True, text=True, timeout=10,
            )
            remote_profile = r.stdout.strip()
            if not remote_profile:
                results[node] = 'no remote profile found'
                continue

            # Copy cookies
            scp_r = subprocess.run(
                ['scp', cookies_file, f'{node}:{remote_profile}/cookies.sqlite'],
                capture_output=True, text=True, timeout=30,
            )
            if scp_r.returncode == 0:
                logger.info(f"  {node}: synced to {remote_profile}")
                results[node] = 'ok'
            else:
                results[node] = f'scp failed: {scp_r.stderr.strip()}'

            # Also copy to /tmp/ff-profile-* if they exist (parallel bot profiles)
            for platform in ['chatgpt', 'gemini', 'grok']:
                tmp_profile = f'/tmp/ff-profile-{platform}'
                subprocess.run(
                    ['ssh', node, f'test -d {tmp_profile} && cp {remote_profile}/cookies.sqlite {tmp_profile}/cookies.sqlite'],
                    capture_output=True, timeout=10,
                )

        except Exception as e:
            results[node] = str(e)

    return results


# ── Login dispatch ───────────────────────────────────────────────

LOGIN_HANDLERS = {
    'chatgpt': login_chatgpt,
    'gemini': login_gemini,
    'grok': login_grok,
    'perplexity': login_perplexity,
    'claude': login_claude,
}


def login_platform(platform: str, secrets: dict) -> bool:
    """Login to a specific platform."""
    handler = LOGIN_HANDLERS.get(platform)
    if not handler:
        logger.error(f"Unknown platform: {platform}")
        return False

    email, password = get_credentials(platform, secrets)
    if not email or not password:
        logger.error(f"No credentials found for {platform}")
        return False

    logger.info(f"[{platform}] Logging in as {email}...")
    return handler(email, password)


def main():
    parser = argparse.ArgumentParser(description='Login to AI chat platforms')
    parser.add_argument('--platform', '-p', help='Platform to login to')
    parser.add_argument('--all', action='store_true', help='Login to all platforms')
    parser.add_argument('--check', action='store_true', help='Check login status only')
    parser.add_argument('--sync', action='store_true', help='Sync cookies after login')
    parser.add_argument('--sync-only', action='store_true', help='Sync cookies without logging in')
    parser.add_argument('--nodes', nargs='+', default=WORKER_NODES,
                        help='Worker nodes to sync cookies to')
    args = parser.parse_args()

    if args.sync_only:
        logger.info("Syncing cookies to workers...")
        results = sync_cookies(args.nodes)
        for node, status in results.items():
            logger.info(f"  {node}: {status}")
        return

    secrets = load_secrets()
    if not secrets.get('email_accounts'):
        logger.error("No email accounts in secrets")
        sys.exit(1)

    platforms = list(LOGIN_HANDLERS.keys()) if args.all else [args.platform] if args.platform else []
    if not platforms:
        parser.print_help()
        sys.exit(1)

    if args.check:
        for platform in platforms:
            status = check_login_status(platform)
            logger.info(f"[{platform}] Status: {status}")
        return

    results = {}
    for platform in platforms:
        success = login_platform(platform, secrets)
        results[platform] = success
        if success:
            logger.info(f"[{platform}] LOGIN SUCCESS")
        else:
            logger.error(f"[{platform}] LOGIN FAILED")

    if args.sync and any(results.values()):
        logger.info("\nSyncing cookies to workers...")
        sync_results = sync_cookies(args.nodes)
        for node, status in sync_results.items():
            logger.info(f"  {node}: {status}")

    # Summary
    print("\n=== Login Summary ===")
    for platform, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  {platform}: {status}")


if __name__ == '__main__':
    main()
