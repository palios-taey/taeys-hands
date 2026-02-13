"""
Platform definitions: URL patterns, tab shortcuts, capabilities.

Central registry for all supported platforms (chat AI and social).

FROZEN once working - do not modify without approval.
"""

# Tab shortcuts (Alt+N) configured in Firefox
TAB_SHORTCUTS = {
    'chatgpt': 'alt+1',
    'claude': 'alt+2',
    'gemini': 'alt+3',
    'grok': 'alt+4',
    'perplexity': 'alt+5',
    # Social platforms - assign as tabs are set up
    # 'x_twitter': 'alt+6',
    # 'linkedin': 'alt+7',
}

# URL patterns for platform detection via AT-SPI DocURL
URL_PATTERNS = {
    'chatgpt': 'chatgpt.com',
    'claude': 'claude.ai',
    'gemini': 'gemini.google.com',
    'grok': 'grok.com',
    'perplexity': 'perplexity.ai',
    'x_twitter': 'x.com',
    'linkedin': 'linkedin.com',
}

# Base URLs for new sessions
BASE_URLS = {
    'chatgpt': 'https://chatgpt.com/',
    'claude': 'https://claude.ai/new',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://grok.com/',
    'perplexity': 'https://perplexity.ai/',
    'x_twitter': 'https://x.com/home',
    'linkedin': 'https://www.linkedin.com/feed/',
}

# Chat AI platforms (have copy buttons, response detection)
CHAT_PLATFORMS = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}

# Social platforms (posting, replying, searching)
SOCIAL_PLATFORMS = {'x_twitter', 'linkedin'}

# All platforms
ALL_PLATFORMS = CHAT_PLATFORMS | SOCIAL_PLATFORMS

# Screen bounds (visible area - half-screen 1720x1440)
SCREEN_WIDTH = 1720
SCREEN_HEIGHT = 1440
