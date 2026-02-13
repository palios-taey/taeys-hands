"""Tests for core/platforms.py - platform registry."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.platforms import (
    TAB_SHORTCUTS, URL_PATTERNS, BASE_URLS,
    CHAT_PLATFORMS, SOCIAL_PLATFORMS,
)


def test_all_chat_platforms_have_shortcuts():
    for platform in CHAT_PLATFORMS:
        assert platform in TAB_SHORTCUTS, f"{platform} missing tab shortcut"


def test_all_platforms_have_url_patterns():
    all_platforms = CHAT_PLATFORMS | SOCIAL_PLATFORMS
    for platform in all_platforms:
        assert platform in URL_PATTERNS, f"{platform} missing URL pattern"


def test_all_platforms_have_base_urls():
    all_platforms = CHAT_PLATFORMS | SOCIAL_PLATFORMS
    for platform in all_platforms:
        assert platform in BASE_URLS, f"{platform} missing base URL"


def test_chat_platforms_are_known():
    expected = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}
    assert CHAT_PLATFORMS == expected


def test_social_platforms_are_known():
    expected = {'x_twitter', 'linkedin'}
    assert SOCIAL_PLATFORMS == expected


def test_url_patterns_are_strings():
    for platform, pattern in URL_PATTERNS.items():
        assert isinstance(pattern, str)
        assert '.' in pattern, f"{platform} URL pattern should contain a dot"
