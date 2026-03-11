#!/usr/bin/env python3
"""x_reply_bot.py — Autonomous X/Twitter reply posting via AT-SPI.

Uses AT-SPI to dynamically find the reply field (no fixed coordinates),
xdotool+xsel for mechanical input. No Claude or LLM needed.

Usage:
    # Single reply
    python3 x_reply_bot.py --url URL --text "Reply text"

    # Batch from JSON file
    python3 x_reply_bot.py --batch replies.json

    # replies.json format:
    # [{"url": "https://x.com/...", "text": "Reply", "handle": "@someone", "topic": "AI"}]

Environment:
    DISPLAY       — X11 display (default: :1)
    NOTIFY_TARGET — taey-notify target for failure alerts (default: claw)
"""

import argparse
import json
import os
import subprocess
import sys
import time

# Must set DISPLAY before importing AT-SPI modules
os.environ.setdefault('DISPLAY', ':1')

# Add taeys-hands to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import atspi
from core import input as inp
from core.tree import find_elements, filter_useful_elements, detect_chrome_y

NOTIFY_TARGET = os.environ.get('NOTIFY_TARGET', 'claw')
LOG_FILE = os.path.expanduser(
    '~/.claude/projects/-home-spark-taeys-hands/memory/x_engagement_log.md'
)


def notify(message: str):
    """Send notification via taey-notify."""
    try:
        subprocess.run(
            ['taey-notify', NOTIFY_TARGET, message, '--type', 'notification'],
            capture_output=True, timeout=5,
        )
    except Exception:
        print(f"  [NOTIFY FAILED] {message}")


def scan_page() -> list:
    """Scan AT-SPI tree for X/Twitter page elements. Returns filtered elements."""
    firefox = atspi.find_firefox()
    if not firefox:
        return []

    doc = atspi.get_platform_document(firefox, 'x_twitter')
    if not doc:
        return []

    chrome_y = detect_chrome_y(doc)
    raw = find_elements(doc)
    return filter_useful_elements(raw, chrome_y=chrome_y)


def find_reply_field(elements: list):
    """Find 'Post text' reply entry field. Returns (x, y) or None."""
    for e in elements:
        if (e.get('role') == 'entry'
                and e.get('name') == 'Post text'
                and 'editable' in e.get('states', [])):
            return (e['x'], e['y'])
    return None


def check_already_replied(elements: list) -> bool:
    """Check if @GodEqualsMath already replied to this post."""
    # Look for our handle in reply articles below the main post
    reply_zone = False
    for e in elements:
        if e.get('name') == 'Post text':
            reply_zone = True
            continue
        if reply_zone and 'GodEqualsMath' in (e.get('name') or ''):
            return True
        if reply_zone and 'GodEqualsMath' in (e.get('text') or ''):
            return True
    return False


def is_page_loaded(elements: list) -> bool:
    """Check if a valid post page loaded (not a 404 or still loading)."""
    return len(elements) > 80 and find_reply_field(elements) is not None


def navigate_to_url(url: str):
    """Navigate Firefox X tab to a URL via address bar."""
    inp.switch_to_platform('x_twitter')
    time.sleep(0.3)
    inp.press_key('Escape')  # dismiss any popups
    time.sleep(0.2)
    inp.press_key('ctrl+l')
    time.sleep(0.3)
    inp.clipboard_paste(url)
    time.sleep(0.1)
    inp.press_key('Return')


def post_reply(url: str, text: str, handle: str = '', topic: str = '') -> dict:
    """Post a reply to a specific X post. Returns result dict."""
    result = {'url': url, 'handle': handle, 'topic': topic, 'success': False, 'error': None}
    label = handle or url.split('/')[-1][:20]

    print(f"\n{'='*60}")
    print(f"  Target: {label}")
    print(f"  URL: {url}")
    print(f"{'='*60}")

    # Step 1: Navigate
    print("  [1/6] Navigating...")
    navigate_to_url(url)
    time.sleep(5)

    # Step 2: Scan for reply field
    print("  [2/6] Scanning page...")
    elements = scan_page()

    if not is_page_loaded(elements):
        # Retry once
        print("  [2/6] Page not ready, retrying in 5s...")
        time.sleep(5)
        elements = scan_page()
        if not is_page_loaded(elements):
            result['error'] = f"Page not loaded ({len(elements)} elements, no reply field)"
            print(f"  [SKIP] {result['error']}")
            return result

    print(f"  [2/6] Page loaded: {len(elements)} elements")

    # Step 3: Check for existing reply
    if check_already_replied(elements):
        result['error'] = "Already replied to this post"
        print(f"  [SKIP] {result['error']}")
        return result

    # Step 4: Like the post
    print("  [3/6] Liking post...")
    inp.press_key('l')
    time.sleep(0.3)

    # Step 5: Click reply field
    coords = find_reply_field(elements)
    x, y = coords
    print(f"  [4/6] Clicking reply field at ({x}, {y})...")
    inp.click_at(x, y)
    time.sleep(0.5)

    # Step 6: Paste reply text
    print(f"  [5/6] Pasting reply ({len(text)} chars)...")
    inp.clipboard_paste(text)
    time.sleep(0.3)

    # Step 7: Submit with Ctrl+Enter
    print("  [6/6] Submitting (Ctrl+Enter)...")
    inp.press_key('ctrl+Return')
    time.sleep(2)

    # Clear clipboard to avoid accidental re-paste
    try:
        subprocess.run(['xsel', '--clipboard', '--clear'],
                       env=os.environ, capture_output=True, timeout=3)
    except Exception:
        pass

    result['success'] = True
    print(f"  [OK] Reply posted to {label}")
    return result


def log_engagement(handle: str, status_id: str, topic: str):
    """Append to engagement log."""
    from datetime import date
    today = date.today().isoformat()
    line = f"{today} | {handle} | {status_id} | {topic}\n"
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line)
        print(f"  [LOG] {line.strip()}")
    except Exception as e:
        print(f"  [LOG FAILED] {e}")


def extract_status_id(url: str) -> str:
    """Extract status ID from X URL."""
    parts = url.rstrip('/').split('/')
    for i, p in enumerate(parts):
        if p == 'status' and i + 1 < len(parts):
            return parts[i + 1]
    return url


def run_batch(replies: list):
    """Process a batch of replies."""
    total = len(replies)
    successes = 0
    failures = []

    print(f"\n  X Reply Bot — {total} replies queued\n")

    for i, r in enumerate(replies):
        url = r.get('url', '')
        text = r.get('text', '')
        handle = r.get('handle', '')
        topic = r.get('topic', '')

        if not url or not text:
            print(f"  [{i+1}/{total}] SKIP — missing url or text")
            continue

        result = post_reply(url, text, handle, topic)

        if result['success']:
            successes += 1
            status_id = extract_status_id(url)
            log_engagement(handle, status_id, topic)
        elif result['error'] and 'Already replied' not in result['error']:
            failures.append(result)

    # Summary
    print(f"\n{'='*60}")
    print(f"  COMPLETE: {successes}/{total} posted, {len(failures)} failed")
    print(f"{'='*60}\n")

    # Notify on failures
    if failures:
        fail_summary = '; '.join(
            f"{f['handle'] or 'unknown'}: {f['error']}" for f in failures
        )
        notify(f"X Reply Bot: {len(failures)}/{total} failed — {fail_summary}")

    return successes, failures


def main():
    parser = argparse.ArgumentParser(description='X/Twitter reply bot')
    parser.add_argument('--url', help='Single post URL to reply to')
    parser.add_argument('--text', help='Reply text')
    parser.add_argument('--handle', default='', help='Target handle (for logging)')
    parser.add_argument('--topic', default='', help='Topic summary (for logging)')
    parser.add_argument('--batch', help='JSON file with array of {url, text, handle, topic}')
    args = parser.parse_args()

    if args.batch:
        with open(args.batch) as f:
            replies = json.load(f)
        run_batch(replies)
    elif args.url and args.text:
        replies = [{'url': args.url, 'text': args.text,
                    'handle': args.handle, 'topic': args.topic}]
        run_batch(replies)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
