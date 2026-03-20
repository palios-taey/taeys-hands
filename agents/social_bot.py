#!/usr/bin/env python3
"""social_bot.py — Extensible social platform automation bot.

Extends the x_reply_bot pattern to support LinkedIn, Reddit, Upwork
(architecture-ready, platform configs added as needed).

Current support:
  - X/Twitter: Reply posting, like, follow (from x_reply_bot.py)
  - LinkedIn: Architecture ready (platforms/linkedin.yaml exists)
  - Reddit: Architecture ready (needs platforms/reddit.yaml)
  - Upwork: Architecture ready (needs platforms/upwork.yaml)

The pattern:
  1. Load platform YAML config
  2. Navigate to target URL
  3. Scan AT-SPI tree for elements
  4. Find compose/reply field
  5. Enter content
  6. Submit

All coordinate-free via AT-SPI element discovery.

Usage:
    # X/Twitter reply
    python3 agents/social_bot.py --platform x_twitter --action reply \\
        --url "https://x.com/..." --text "Reply text"

    # Batch from JSON
    python3 agents/social_bot.py --platform x_twitter --batch tasks.json

    # LinkedIn post (when platform config ready)
    python3 agents/social_bot.py --platform linkedin --action post --text "Post text"

Environment:
    DISPLAY       — X11 display (default: :1)
    NOTIFY_TARGET — Notification target (default: weaver)
"""

import argparse
import json
import logging
import os
import sys
import time

os.environ.setdefault('DISPLAY', ':1')

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import yaml

from core import atspi, input as inp
from core.tree import find_elements, filter_useful_elements, detect_chrome_y
from core.halt import halt_platform, check_halt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('social_bot')

PLATFORMS_DIR = os.path.join(_ROOT, 'platforms')


def load_social_config(platform: str) -> dict:
    """Load platform YAML config."""
    path = os.path.join(PLATFORMS_DIR, f'{platform}.yaml')
    if not os.path.exists(path):
        raise FileNotFoundError(f"No YAML config for platform: {platform}")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def scan_page(platform: str) -> list:
    """Scan AT-SPI tree for page elements. Returns filtered elements."""
    firefox = atspi.find_firefox(platform)
    if not firefox:
        return []
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return []
    chrome_y = detect_chrome_y(doc)
    raw = find_elements(doc)
    return filter_useful_elements(raw, chrome_y=chrome_y)


def navigate_to(platform: str, url: str):
    """Navigate Firefox to URL via address bar."""
    inp.switch_to_platform(platform)
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


def find_compose_field(elements: list, config: dict) -> dict:
    """Find compose/reply input field using element_hints from YAML."""
    hints = config.get('element_hints', {})
    input_role = hints.get('input_role', 'entry')
    input_name = hints.get('input_name_pattern', '')

    for e in elements:
        role = e.get('role', '').lower()
        name = (e.get('name') or '').lower()
        states = e.get('states', [])

        if role == input_role and 'editable' in states:
            if input_name and input_name.lower() not in name:
                continue
            return e

    # Fallback: any editable entry
    for e in elements:
        if 'editable' in e.get('states', []):
            return e

    return None


def find_submit_button(elements: list, config: dict) -> dict:
    """Find submit/post button using element_hints from YAML."""
    hints = config.get('element_hints', {})
    send_role = hints.get('send_role', 'push button')
    send_name = hints.get('send_name_pattern', 'post')

    for e in elements:
        role = e.get('role', '').lower()
        name = (e.get('name') or '').lower()

        if role == send_role and send_name.lower() in name:
            return e

    return None


def post_content(platform: str, url: str = None, text: str = '',
                 action: str = 'reply') -> dict:
    """Post content to a social platform.

    Args:
        platform: Platform name
        url: Target URL (for replies/comments)
        text: Content to post
        action: 'reply', 'post', 'comment'

    Returns:
        Result dict with 'success' and details.
    """
    result = {'platform': platform, 'action': action, 'success': False}
    config = load_social_config(platform)

    # Navigate
    if url:
        logger.info(f"[{platform}] Navigating to {url[:80]}")
        navigate_to(platform, url)
        time.sleep(5)

    # Scan
    elements = scan_page(platform)
    if not elements:
        time.sleep(5)
        elements = scan_page(platform)
    if not elements:
        result['error'] = 'No elements found on page'
        return result

    logger.info(f"[{platform}] Found {len(elements)} elements")

    # Find input field
    field = find_compose_field(elements, config)
    if not field:
        result['error'] = 'Compose field not found'
        return result

    # Click input
    inp.click_at(int(field['x']), int(field['y']))
    time.sleep(0.5)

    # Type/paste content
    if len(text) > 100:
        inp.clipboard_paste(text)
    else:
        inp.type_text(text, delay_ms=20)
    time.sleep(0.3)

    # Find and click submit
    # Re-scan after typing (button may appear)
    elements = scan_page(platform)
    submit = find_submit_button(elements, config)

    if submit:
        inp.click_at(int(submit['x']), int(submit['y']))
        time.sleep(2)
        result['success'] = True
        result['submitted_via'] = 'button_click'
    else:
        # Try Ctrl+Enter (common for X, some others)
        inp.press_key('ctrl+Return')
        time.sleep(2)
        result['success'] = True
        result['submitted_via'] = 'ctrl_enter'

    logger.info(f"[{platform}] Content posted: {result['submitted_via']}")
    return result


def run_batch(platform: str, tasks: list):
    """Process batch of social tasks."""
    total = len(tasks)
    successes = 0
    failures = []

    logger.info(f"\n  Social Bot — {total} tasks for {platform}\n")

    for i, task in enumerate(tasks):
        url = task.get('url', '')
        text = task.get('text', '')
        action = task.get('action', 'reply')

        if not text:
            logger.info(f"  [{i+1}/{total}] SKIP — no text")
            continue

        result = post_content(platform, url=url, text=text, action=action)

        if result['success']:
            successes += 1
        else:
            failures.append(result)

        # Delay between posts to avoid rate limits
        if i < total - 1:
            time.sleep(5)

    logger.info(f"\n  COMPLETE: {successes}/{total} posted, {len(failures)} failed\n")
    return successes, failures


def main():
    parser = argparse.ArgumentParser(description='Social platform bot')
    parser.add_argument('--platform', required=True,
                        help='Platform: x_twitter, linkedin, reddit, upwork')
    parser.add_argument('--action', default='reply',
                        help='Action: reply, post, comment')
    parser.add_argument('--url', help='Target URL')
    parser.add_argument('--text', help='Content text')
    parser.add_argument('--batch', help='JSON file with task array')
    args = parser.parse_args()

    if args.batch:
        with open(args.batch) as f:
            tasks = json.load(f)
        run_batch(args.platform, tasks)
    elif args.text:
        result = post_content(args.platform, url=args.url,
                              text=args.text, action=args.action)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
