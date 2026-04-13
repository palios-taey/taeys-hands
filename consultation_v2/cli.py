from __future__ import annotations

import argparse
import json
from pathlib import Path

from consultation_v2.orchestrator import run_consultation
from consultation_v2.types import ConsultationRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run the isolated Consultation V2 workflow.')
    parser.add_argument('--platform', required=True, choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'])
    parser.add_argument('--message', required=True)
    parser.add_argument('--attach', action='append', default=[])
    parser.add_argument('--model', default=None)
    parser.add_argument('--mode', default=None)
    parser.add_argument('--tool', action='append', default=[])
    parser.add_argument('--connector', action='append', default=[],
                        help='Connector name to enable, e.g. github, web (repeatable)')
    parser.add_argument('--session-url', default=None)
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', default=None)
    parser.add_argument('--no-neo4j', action='store_true')
    parser.add_argument('--session-type', default=None)
    parser.add_argument('--purpose', default=None)
    parser.add_argument('--requester', default=None,
                        help='Node ID of the requester (for notifications)')
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    request = ConsultationRequest(
        platform=args.platform,
        message=args.message,
        attachments=list(args.attach or []),
        model=args.model,
        mode=args.mode,
        tools=list(args.tool or []),
        connectors=list(args.connector or []),
        session_url=args.session_url,
        timeout=args.timeout,
        output_path=args.output,
        no_neo4j=args.no_neo4j,
        session_type=args.session_type,
        purpose=args.purpose,
        requester=args.requester,
    )
    result = run_consultation(request)
    payload = result.serializable()
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
