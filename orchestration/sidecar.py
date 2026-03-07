#!/usr/bin/env python3
"""Minimal orchestration sidecar daemon.

Consumes tasks from Redis Stream ``orch:inbox:{agent_id}`` via XREADGROUP,
injects task text into a tmux session, ACKs successful deliveries, and emits
``task.delivered`` / ``task.delivery_failed`` events.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime
from typing import Dict, Optional

import redis


ORCH_REDIS_HOST = os.environ.get("ORCH_REDIS_HOST", "localhost")
ORCH_REDIS_PORT = int(os.environ.get("ORCH_REDIS_PORT", "6379"))
EVENT_STREAM = "orch:streams:events"
DEFAULT_GROUP = "sidecar-delivery"


class CLIAdapter:
    """Inject text into a tmux session using load-buffer + paste-buffer."""

    def __init__(self, tmux_session: str):
        self.tmux_session = tmux_session

    def send_task(self, task_description: str) -> bool:
        return self._inject_message(task_description)

    def _inject_message(self, message: str) -> bool:
        tmp_file = f"/tmp/orch_msg_{self.tmux_session}.txt"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(message)

            result = subprocess.run(
                ["tmux", "load-buffer", tmp_file],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                return False

            result = subprocess.run(
                ["tmux", "paste-buffer", "-t", self.tmux_session],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                return False

            time.sleep(0.5)
            result = subprocess.run(
                ["tmux", "send-keys", "-t", self.tmux_session, "Enter"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False


class SidecarDaemon:
    def __init__(
        self,
        agent_id: str,
        tmux_session: str,
        consumer_group: str = DEFAULT_GROUP,
        block_ms: int = 5000,
    ):
        self.agent_id = agent_id
        self.tmux_session = tmux_session
        self.consumer_group = consumer_group
        self.block_ms = block_ms
        self.inbox_stream = f"orch:inbox:{agent_id}"
        self.consumer_name = f"{tmux_session}-sidecar"

        self.redis = redis.Redis(
            host=ORCH_REDIS_HOST,
            port=ORCH_REDIS_PORT,
            decode_responses=True,
        )
        self.cli = CLIAdapter(tmux_session)

    def ensure_consumer_group(self) -> None:
        try:
            self.redis.xgroup_create(
                name=self.inbox_stream,
                groupname=self.consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

    def emit_event(
        self,
        event_type: str,
        payload: Dict[str, object],
        *,
        caused_by: Optional[str] = None,
    ) -> None:
        timestamp = datetime.utcnow().isoformat()
        actor = f"sidecar:{self.agent_id}"
        content = json.dumps(
            {
                "event_type": event_type,
                "payload": payload,
                "actor": actor,
                "timestamp": timestamp,
                "caused_by": caused_by,
            },
            sort_keys=True,
        )
        event_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        self.redis.xadd(
            EVENT_STREAM,
            {
                "event_type": event_type,
                "payload": json.dumps(payload),
                "actor": actor,
                "timestamp": timestamp,
                "caused_by": caused_by or "",
                "event_hash": event_hash,
            },
            maxlen=100_000,
            approximate=True,
        )

    @staticmethod
    def _extract_message(fields: Dict[str, str]) -> str:
        for key in (
            "message",
            "task_description",
            "description",
            "prompt",
            "text",
            "content",
        ):
            value = fields.get(key)
            if value:
                return value

        if len(fields) == 1:
            return next(iter(fields.values()))

        return json.dumps(fields, ensure_ascii=True)

    def _process_message(self, msg_id: str, fields: Dict[str, str]) -> None:
        message = self._extract_message(fields)
        delivered = self.cli.send_task(message)

        event_payload = {
            "agent_id": self.agent_id,
            "session": self.tmux_session,
            "stream": self.inbox_stream,
            "message_id": msg_id,
            "fields": fields,
        }

        if delivered:
            self.redis.xack(self.inbox_stream, self.consumer_group, msg_id)
            self.emit_event("task.delivered", event_payload)
            return

        self.emit_event(
            "task.delivery_failed",
            {**event_payload, "error": "tmux injection failed"},
        )

    def run(self) -> None:
        self.ensure_consumer_group()
        print(
            f"[sidecar] listening stream={self.inbox_stream} "
            f"group={self.consumer_group} consumer={self.consumer_name} "
            f"session={self.tmux_session}",
            flush=True,
        )

        while True:
            try:
                messages = self.redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.inbox_stream: ">"},
                    count=1,
                    block=self.block_ms,
                )
                if not messages:
                    continue

                for _, stream_messages in messages:
                    for msg_id, fields in stream_messages:
                        self._process_message(msg_id, fields)
            except KeyboardInterrupt:
                print("[sidecar] stopped", flush=True)
                return
            except Exception as e:
                self.emit_event(
                    "task.delivery_failed",
                    {
                        "agent_id": self.agent_id,
                        "session": self.tmux_session,
                        "stream": self.inbox_stream,
                        "error": str(e),
                    },
                )
                time.sleep(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orchestration sidecar daemon")
    parser.add_argument("--agent-id", required=True, help="Agent identifier")
    parser.add_argument("--session", required=True, help="tmux session name")
    parser.add_argument(
        "--group",
        default=DEFAULT_GROUP,
        help=f"Redis consumer group (default: {DEFAULT_GROUP})",
    )
    parser.add_argument(
        "--block-ms",
        type=int,
        default=5000,
        help="XREADGROUP block timeout in milliseconds",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    daemon = SidecarDaemon(
        agent_id=args.agent_id,
        tmux_session=args.session,
        consumer_group=args.group,
        block_ms=args.block_ms,
    )
    daemon.run()


if __name__ == "__main__":
    main()
