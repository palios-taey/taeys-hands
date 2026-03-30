from __future__ import annotations
"""Existing attachment detection — scan AT-SPI tree for file chips."""

import logging
from typing import Any, Dict, List

from core.tree import find_elements, filter_useful_elements, detect_chrome_y

logger = logging.getLogger(__name__)

_FILE_EXTENSIONS = ('.md', '.py', '.txt', '.pdf', '.png', '.jpg',
                    '.jpeg', '.csv', '.json', '.xml', '.html', '.zip', '.docx')


def detect_existing_attachments(doc) -> List[Dict]:
    """Scan AT-SPI tree for existing file attachment chips.

    Returns list of dicts with file name and Remove button coordinates.
    This prevents accidentally adding multiple files.
    """
    if not doc:
        return []

    chrome_y = detect_chrome_y(doc)
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)

    remove_buttons = []
    file_names = []
    for e in elements:
        name = (e.get('name') or '').strip()
        role = e.get('role', '')
        if 'button' in role and name.lower().startswith('remove'):
            remove_buttons.append({'x': e.get('x'), 'y': e.get('y'), 'name': name})
        if name and any(name.lower().endswith(ext) for ext in _FILE_EXTENSIONS):
            if role in ('heading', 'push button', 'toggle button'):
                file_names.append(name)

    # Require remove buttons to confirm real attachments.
    # Sidebar history items match file extensions but never have Remove buttons.
    if remove_buttons:
        return [{'file': fn, 'remove_buttons': remove_buttons} for fn in file_names] or \
               [{'file': '(unknown)', 'remove_buttons': remove_buttons}]

    # Detect unnamed file chips (Grok/Perplexity pattern):
    # Unnamed push buttons clustered just above the input entry field.
    entry_y = None
    for e in all_elements:
        if e.get('role') == 'entry' and 'editable' in (e.get('states') or []):
            entry_y = e.get('y', 0)
            break

    if entry_y:
        unnamed_chips = [
            e for e in all_elements
            if (e.get('role') == 'push button'
                and not (e.get('name') or '').strip()
                and entry_y - 100 < e.get('y', 0) < entry_y - 10)
        ]
        if unnamed_chips:
            return [{'file': '(unknown)', 'remove_buttons': [
                {'x': b.get('x'), 'y': b.get('y'), 'name': ''} for b in unnamed_chips
            ]}]

    return []
