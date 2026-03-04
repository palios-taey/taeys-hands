# Local LLM Agent

Bridges any OpenAI-compatible local model to taeys-hands MCP tools for autonomous chat platform automation.

## Quick Start

```bash
# Basic usage (model auto-detected from API)
python3 agents/local_llm_agent.py "Inspect ChatGPT and describe what you see"

# Task from file
python3 agents/local_llm_agent.py --task-file /tmp/task.md

# Interactive mode
python3 agents/local_llm_agent.py --interactive
```

## Configuration

All settings via environment variables with localhost defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_URL` | `http://localhost:8080/v1` | OpenAI-compatible API endpoint |
| `LLM_MODEL` | (auto-detected) | Model identifier |
| `LLM_MAX_TOKENS` | `4096` | Max response tokens |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature |
| `TAEY_SERVER_CMD` | `python3 server.py` | MCP server launch command |
| `TMUX_SUPERVISOR` | (none) | tmux session for escalation |

The MCP server inherits `DISPLAY`, `REDIS_HOST`, `NEO4J_URI` from the agent's environment.

## How It Works

1. Forks the taeys-hands MCP server as a subprocess (JSON-RPC 2.0 over stdio)
2. Sends the task to the local LLM with MCP tool definitions as OpenAI functions
3. When the LLM requests tool calls, executes them via MCP and feeds results back
4. Repeats until the LLM responds with text (no more tool calls)
5. If stuck after max turns, escalates to a supervisor Claude Code session via tmux

## Requirements

- Local model with OpenAI-compatible API (llama.cpp, vLLM, Ollama, etc.)
- Model must support function/tool calling
- taeys-hands MCP server dependencies (see project README)
