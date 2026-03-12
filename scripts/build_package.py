#!/usr/bin/env python3
"""build_package.py — Consolidate multiple files into a single .md attachment.

Merges source files into one Markdown document with file headers and fenced
code blocks, suitable for attaching to a chat platform as a single package.

Usage:
    python3 build_package.py -o /tmp/package.md file1.py file2.yaml dir/
    python3 build_package.py --manifest manifest.txt -o /tmp/package.md
    python3 build_package.py --glob "src/**/*.py" -o /tmp/package.md

Options:
    -o, --output    Output path (default: /tmp/build_package_output.md)
    --manifest      Read file paths from a text file (one per line)
    --glob          Glob pattern to match files
    --max-tokens    Approximate token budget (default: 50000, ~4 chars/token)
    --title         Package title (default: "Package")
"""

import argparse
import glob as globmod
import os
import sys


def _ext_to_lang(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.md': 'markdown',
        '.sh': 'bash', '.bash': 'bash', '.rs': 'rust', '.go': 'go',
        '.html': 'html', '.css': 'css', '.sql': 'sql', '.toml': 'toml',
    }.get(ext, '')


def collect_files(args) -> list[str]:
    paths = []
    if args.files:
        for f in args.files:
            if os.path.isdir(f):
                for root, _, names in os.walk(f):
                    paths.extend(os.path.join(root, n) for n in sorted(names))
            elif os.path.isfile(f):
                paths.append(f)
    if args.manifest:
        with open(args.manifest) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith('#') and os.path.isfile(line):
                    paths.append(line)
    if args.glob:
        paths.extend(sorted(globmod.glob(args.glob, recursive=True)))
    return [os.path.abspath(p) for p in paths if os.path.isfile(p)]


def build_package(files: list[str], title: str, max_chars: int) -> str:
    sections = [f"# {title}\n\n**Files**: {len(files)}\n"]
    total = len(sections[0])

    for path in files:
        try:
            content = open(path).read()
        except Exception as e:
            content = f"[Error reading file: {e}]"

        lang = _ext_to_lang(path)
        header = f"\n---\n\n## {os.path.basename(path)}\n\n`{path}`\n\n```{lang}\n"
        footer = "\n```\n"
        section_len = len(header) + len(content) + len(footer)

        if total + section_len > max_chars:
            remaining = max_chars - total - len(header) - len(footer) - 50
            if remaining > 200:
                content = content[:remaining] + "\n\n... [truncated]"
            else:
                sections.append(f"\n---\n\n## {os.path.basename(path)}\n\n[Skipped — budget exceeded]\n")
                break

        sections.append(header + content + footer)
        total += len(header) + len(content) + len(footer)

    return ''.join(sections)


def main():
    p = argparse.ArgumentParser(description="Consolidate files into a single .md package")
    p.add_argument('files', nargs='*', help="Files or directories to include")
    p.add_argument('-o', '--output', default='/tmp/build_package_output.md')
    p.add_argument('--manifest', help="File listing paths (one per line)")
    p.add_argument('--glob', help="Glob pattern")
    p.add_argument('--max-tokens', type=int, default=50000)
    p.add_argument('--title', default='Package')
    args = p.parse_args()

    files = collect_files(args)
    if not files:
        print("No files found.", file=sys.stderr)
        sys.exit(1)

    max_chars = args.max_tokens * 4
    result = build_package(files, args.title, max_chars)

    with open(args.output, 'w') as f:
        f.write(result)

    print(f"Built {args.output}: {len(files)} files, {len(result)} chars")


if __name__ == '__main__':
    main()
