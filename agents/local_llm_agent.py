#!/usr/bin/env python3
"""
Local LLM Agent — bridges any OpenAI-compatible model to taeys-hands MCP tools.

Runs an agentic tool-calling loop: sends tasks to a local LLM, executes MCP tool
calls from the LLM's responses, feeds results back, and repeats until done.

Configuration via environment variables:
    LLM_API_URL       OpenAI-compatible endpoint (default: http://localhost:8080/v1)
    LLM_MODEL         Model identifier (auto-detected if not set)
    LLM_MAX_TOKENS    Max response tokens (default: 4096)
    LLM_TEMPERATURE   Sampling temperature (default: 0.7)
    TAEY_SERVER_CMD   MCP server command (default: python3 server.py)
    TMUX_SUPERVISOR   tmux session for escalation when stuck (optional)

Usage:
    python3 agents/local_llm_agent.py "Inspect ChatGPT and describe what you see"
    python3 agents/local_llm_agent.py --task-file /tmp/task.md
    python3 agents/local_llm_agent.py --interactive
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("local-llm-agent")

# Resolve paths relative to repo root (parent of agents/)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# System prompt that teaches the LLM how to use taeys-hands MCP tools
SYSTEM_PROMPT = """\
You are an automation agent with access to taeys-hands MCP tools for controlling \
chat platforms (ChatGPT, Claude, Gemini, Grok, Perplexity) and social platforms \
(X/Twitter, LinkedIn) via AT-SPI accessibility APIs on Linux.

WORKFLOW RULES (follow strictly):
1. ALWAYS call taey_inspect(platform) FIRST before any other tool on that platform.
2. taey_inspect returns elements with x,y coordinates. Use those for taey_click.
3. Click the INPUT FIELD via taey_click BEFORE calling taey_send_message.
   send_message pastes into whatever is focused — it does NOT click the input.
4. After taey_attach (file upload), RE-INSPECT — file chips shift element positions.
5. Process ONE platform at a time: inspect → attach → re-inspect → click input → send → move on.
6. After send_message, a daemon monitors for responses. Move to the next platform.
7. Use taey_quick_extract to get responses when notified or when re-inspecting shows completion.
8. NEVER click Submit/Send buttons — Enter is pressed automatically by send_message.

COMPLETION SIGNALS:
- No stop/cancel button + copy buttons visible = response complete → extract.
- Stop button visible = still generating → skip, check later.

When you're done with your task, respond with your final answer as plain text (no tool calls).
"""


# =========================================================================
# MCP Client — manages the MCP server subprocess
# =========================================================================

class MCPClient:
    """JSON-RPC 2.0 client for the taeys-hands MCP server over stdio."""

    def __init__(self, cmd: str = None):
        self.cmd = cmd or os.environ.get("TAEY_SERVER_CMD", "python3 server.py")
        self.proc = None
        self._request_id = 0
        self.tools = []
        self.notifications = []

    def start(self):
        """Fork the MCP server subprocess."""
        logger.info("Starting MCP server: %s (cwd=%s)", self.cmd, REPO_ROOT)
        self.proc = subprocess.Popen(
            self.cmd.split(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=REPO_ROOT,
            text=True,
            bufsize=1,
        )

    def _send(self, method: str, params: dict = None) -> dict:
        """Send a JSON-RPC request and read the response."""
        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._request_id,
        }
        if params:
            msg["params"] = params

        line = json.dumps(msg) + "\n"
        logger.debug("MCP >>> %s", line.strip())
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

        response_line = self.proc.stdout.readline()
        if not response_line:
            raise RuntimeError("MCP server closed stdout unexpectedly")
        logger.debug("MCP <<< %s", response_line.strip()[:500])
        return json.loads(response_line)

    def initialize(self) -> list:
        """Initialize the MCP connection and return tool definitions."""
        self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "local-llm-agent", "version": "1.0.0"},
        })
        # Send initialized notification (no response expected, but server reads it)
        notif = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }) + "\n"
        self.proc.stdin.write(notif)
        self.proc.stdin.flush()

        # Get tool list
        resp = self._send("tools/list")
        self.tools = resp.get("result", {}).get("tools", [])
        logger.info("MCP server ready — %d tools available", len(self.tools))
        return self.tools

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool and return the parsed result."""
        resp = self._send("tools/call", {"name": name, "arguments": arguments})

        result = resp.get("result", {})
        is_error = result.get("isError", False)

        # Extract text content (double-encoded JSON)
        content = result.get("content", [])
        text = content[0].get("text", "{}") if content else "{}"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"raw_text": text}

        # Extract piggybacked notifications
        if "_notifications" in parsed:
            self.notifications.extend(parsed.pop("_notifications"))

        if is_error:
            parsed["_mcp_error"] = True

        return parsed

    def pop_notifications(self) -> list:
        """Return and clear pending notifications."""
        notifs = self.notifications
        self.notifications = []
        return notifs

    def close(self):
        """Kill the MCP server subprocess."""
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            logger.info("MCP server stopped")


# =========================================================================
# Local LLM Agent — agentic tool-calling loop
# =========================================================================

class LocalLLMAgent:
    """Agent that uses a local OpenAI-compatible LLM with MCP tools."""

    def __init__(
        self,
        api_url: str = None,
        model: str = None,
        max_tokens: int = None,
        temperature: float = None,
    ):
        self.api_url = (api_url or os.environ.get(
            "LLM_API_URL", "http://localhost:8080/v1"
        )).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "")
        self.max_tokens = max_tokens or int(os.environ.get("LLM_MAX_TOKENS", "4096"))
        self.temperature = temperature or float(os.environ.get("LLM_TEMPERATURE", "0.7"))
        self.supervisor = os.environ.get("TMUX_SUPERVISOR", "")

        if not self.model:
            self.model = self._detect_model()

    def _detect_model(self) -> str:
        """Auto-detect model name from /v1/models endpoint."""
        url = f"{self.api_url}/models"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get("data", [])
                if models:
                    model_id = models[0].get("id", "")
                    logger.info("Auto-detected model: %s", model_id)
                    return model_id
        except Exception as e:
            logger.warning("Could not auto-detect model from %s: %s", url, e)
        return "default"

    def _mcp_tools_to_openai(self, mcp_tools: list) -> list:
        """Convert MCP tool definitions to OpenAI function-calling format."""
        openai_tools = []
        for tool in mcp_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                },
            })
        return openai_tools

    def _chat_completion(self, messages: list, tools: list = None) -> dict:
        """Call the LLM's chat completion endpoint."""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools

        body = json.dumps(payload).encode()
        url = f"{self.api_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            logger.error("LLM API error %d: %s", e.code, error_body[:500])
            raise
        except urllib.error.URLError as e:
            logger.error("LLM API connection error: %s", e.reason)
            raise

    def _escalate(self, message: str):
        """Send escalation message to supervisor Claude via tmux-send."""
        if not self.supervisor:
            logger.warning("No TMUX_SUPERVISOR set — cannot escalate: %s", message)
            return

        msg = f"ESCALATION from local-llm-agent: {message}"
        try:
            # Use tmux-send if available, otherwise raw tmux
            tmux_send = "/usr/local/bin/tmux-send"
            if os.path.exists(tmux_send):
                subprocess.run(
                    [tmux_send, "localhost", self.supervisor, msg],
                    capture_output=True, text=True, timeout=10,
                )
            else:
                # Direct tmux with escape sandwich
                subprocess.run(
                    ["tmux", "send-keys", "-t", self.supervisor, "--", msg],
                    capture_output=True, text=True, timeout=5,
                )
                time.sleep(0.5)
                subprocess.run(
                    ["tmux", "send-keys", "-t", self.supervisor, "Escape"],
                    capture_output=True, text=True, timeout=5,
                )
                time.sleep(0.2)
                subprocess.run(
                    ["tmux", "send-keys", "-t", self.supervisor, "Enter"],
                    capture_output=True, text=True, timeout=5,
                )
                time.sleep(0.1)
                # Kitty protocol Enter (CSI u)
                subprocess.run(
                    ["tmux", "send-keys", "-t", self.supervisor, "-H",
                     "1b", "5b", "31", "33", "75"],
                    capture_output=True, text=True, timeout=5,
                )
            logger.info("Escalation sent to supervisor '%s'", self.supervisor)
        except Exception as e:
            logger.error("Failed to escalate to supervisor: %s", e)

    def run(self, task: str, mcp: MCPClient, max_turns: int = 20) -> str:
        """Run the agentic loop until the LLM responds with text (no tool calls)."""
        openai_tools = self._mcp_tools_to_openai(mcp.tools)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]

        for turn in range(max_turns):
            logger.info("--- Turn %d/%d ---", turn + 1, max_turns)

            # Check for MCP notifications from previous tool calls
            notifs = mcp.pop_notifications()
            if notifs:
                notif_text = "\n".join(
                    f"[NOTIFICATION] {n.get('type', 'unknown')}: {json.dumps(n)}"
                    for n in notifs
                )
                # Use "user" role — some models (Qwen3.5) reject system messages
                # anywhere except position 0 in the conversation.
                messages.append({"role": "user", "content": notif_text})

            # Call LLM
            try:
                response = self._chat_completion(messages, tools=openai_tools)
            except Exception as e:
                logger.error("LLM call failed: %s", e)
                self._escalate(f"LLM API call failed on turn {turn + 1}: {e}")
                return f"[ERROR] LLM API call failed: {e}"

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "")

            # Log usage
            usage = response.get("usage", {})
            if usage:
                logger.info(
                    "Tokens — prompt: %d, completion: %d, total: %d",
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                    usage.get("total_tokens", 0),
                )

            # Case 1: LLM wants to call tools
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                # Add assistant message with tool calls to history
                messages.append(message)

                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "")
                    try:
                        tool_args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        tool_args = {}

                    logger.info("Tool call: %s(%s)", tool_name, json.dumps(tool_args)[:200])

                    # Execute via MCP
                    try:
                        result = mcp.call_tool(tool_name, tool_args)
                    except Exception as e:
                        result = {"error": str(e)}
                        logger.error("MCP tool call failed: %s", e)

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result, indent=2, default=str),
                    })

                    logger.info(
                        "Tool result: %s (%.0f chars)",
                        "error" if result.get("error") or result.get("_mcp_error") else "ok",
                        len(json.dumps(result, default=str)),
                    )

                continue

            # Case 2: LLM responded with text (done)
            content = message.get("content", "")
            if content:
                logger.info("Agent completed — final response (%d chars)", len(content))
                return content

            # Case 3: Empty response or unexpected finish
            logger.warning("Unexpected finish_reason=%s with no content or tools", finish_reason)
            if finish_reason == "length":
                messages.append({"role": "user", "content": "Continue."})
                continue

            return f"[WARNING] Unexpected finish: {finish_reason}"

        # Max turns exceeded
        self._escalate(f"Max turns ({max_turns}) exceeded for task: {task[:200]}")
        return f"[ERROR] Max turns ({max_turns}) exceeded. Task escalated to supervisor."


# =========================================================================
# CLI entry point
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Local LLM agent for taeys-hands MCP tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("task", nargs="?", help="Task to execute")
    parser.add_argument("--task-file", help="Read task from file")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode (loop)")
    parser.add_argument("--max-turns", type=int, default=20, help="Max agentic turns per task")
    parser.add_argument("--api-url", help="Override LLM_API_URL")
    parser.add_argument("--model", help="Override LLM_MODEL")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine task
    if args.task_file:
        with open(args.task_file) as f:
            task = f.read().strip()
    elif args.task:
        task = args.task
    elif not args.interactive:
        parser.error("Provide a task, --task-file, or --interactive")
        return

    # Initialize MCP client
    mcp = MCPClient()
    mcp.start()
    try:
        mcp.initialize()
    except Exception as e:
        logger.error("MCP initialization failed: %s", e)
        mcp.close()
        sys.exit(1)

    # Initialize LLM agent
    agent = LocalLLMAgent(api_url=args.api_url, model=args.model)
    logger.info("Agent ready — model=%s, api=%s", agent.model, agent.api_url)

    try:
        if args.interactive:
            print("Local LLM Agent (interactive). Type 'quit' to exit.")
            while True:
                try:
                    task = input("\n> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not task or task.lower() in ("quit", "exit", "q"):
                    break
                result = agent.run(task, mcp, max_turns=args.max_turns)
                print(f"\n{result}")
        else:
            result = agent.run(task, mcp, max_turns=args.max_turns)
            print(result)
    finally:
        mcp.close()


if __name__ == "__main__":
    main()
