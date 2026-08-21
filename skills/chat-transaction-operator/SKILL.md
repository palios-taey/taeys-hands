---
name: chat-transaction-operator
description: Run a frozen Family Chat send or monitor-authorized extraction through the pinned public launcher. Use when Taey or a fleet CLI must attach two frozen bundles, paste a frozen prompt, send once, or extract a completed response on a mapped Chat display.
---

# Chat Transaction Operator

Use `scripts/run_manual_chat_worker.py`. It is the only worker-request launcher for the manual Chat lane.

For a send, invoke its `send` subcommand once with the supplied platform, display, unique seat ID, new artifact root, Bundle A, Bundle B, and prompt-file paths. Do not write request JSON, compose worker instructions, call the worker proxy directly, or retry.

For extraction, execute the completion monitor's exact `run_command`. That command invokes this same launcher's `extract` subcommand. Do not reconstruct it, send a message asking another agent to extract, or drive the display yourself.

On any `STOP:` or nonzero exit, stop the transaction and report the first error with the artifact paths. Do not recover in the same turn.

The platform YAML and fresh accessibility tree remain the worker's UI authority. This skill adds no alternate action sequence, fallback, or receipt contract.
