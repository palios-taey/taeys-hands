# Fleet Tools — Full Access

You are a CLI agent in the PALIOS-TAEY fleet on Mira (10.0.0.163).

## CRITICAL RULE: If a tool does not work, STOP and report

If you run a command and it fails, errors, or you cannot execute shell commands at all:
1. **DO NOT hallucinate or fabricate output.** Ever.
2. **DO NOT continue working** as if the tool succeeded.
3. **STOP** and report the failure back via `taey-notify conductor "TOOL FAILURE: {what failed and why}"`.
4. If you cannot run taey-notify either, output the failure clearly in your response.

## Process: How Work Gets Done

### Creating tasks (for Conductor)
```bash
taey-task create "description of what you need" --priority 70 --from your-session-name
```
This creates a persistent OrchTask in Neo4j and notifies the Conductor. Use this instead of freeform taey-notify for work requests.

### DMAIC flow (Conductor manages this)
1. **DEFINE**: Conductor writes defect statement on OrchTask
2. **MEASURE**: Gemini CLI runs git/gitnexus/isma, produces report
3. **ANALYZE**: Conductor identifies root cause from report
4. **IMPROVE**: Codex creates branch + PR with full context
5. **CONTROL**: YOU (the requestor) review PR, test, and close: `taey-task update {task_id} completed`

### After your PR is merged
```bash
taey-task update {task_id} completed
```

### If something fails
```bash
taey-task update {task_id} failed
taey-notify conductor "CONTROL REJECT [{task_id}]: {what went wrong}"
```

## Git
```bash
git log --oneline -20 -- {file}
git blame {file}
git log --grep="{keyword}" --oneline
git diff {commit1}..{commit2} -- {file}
git show {commit}
```

## GitNexus (code intelligence — CLI commands)
```bash
gitnexus impact {symbol} --direction upstream --repo taeys-hands
gitnexus context {symbol} --repo taeys-hands
gitnexus query "concept" --repo taeys-hands
gitnexus cypher "MATCH ..." --repo taeys-hands
```
NOTE: Only these 4 commands exist in CLI. detect-changes and rename are NOT available.

## ISMA (1M+ tile knowledge graph)
```bash
isma search "query" --top-k 10        # semantic search
isma motif MOTIF_NAME --limit 10      # by HMM motif
isma adaptive "question" --top-k 5    # auto-classified search
isma tile {content_hash}              # full tile by hash
isma traverse {hash} --edge-type RELATES_TO --depth 2
isma stats                            # system stats
isma cypher "MATCH (t:HMMTile) RETURN count(t)"
```

## Notifications (inter-instance messaging)
```bash
taey-notify conductor "message"       # report to conductor
taey-notify weaver "question"         # ask weaver about ISMA
taey-notify tutor "status update"     # update tutor
# Targets: conductor, taeys-hands, weaver, tutor, infra, taey
```

## Redis
```bash
redis-cli GET {key}                   # read state
redis-cli SET {key} {value}           # write state
redis-cli LLEN taey:{node}:inbox      # check inbox depth
```

## SSH (fleet machines)
| Machine | Command | Role |
|---------|---------|------|
| Spark 1 | `ssh spark@10.0.0.68` | Orchestrator, Redis, dashboard |
| Spark 2 | `ssh spark@10.0.0.80` | Embedding server |
| Spark 4 | `ssh spark@10.0.0.19` | Available |
| Thor | `ssh thor@10.0.0.197` | HMM worker |
| Jetson | `ssh jetson@10.0.0.8` | Taey inference |

## Network Services
| Service | Endpoint |
|---------|----------|
| ISMA Query API | http://127.0.0.1:8095 |
| Dashboard | http://10.0.0.68:5001 |
| Neo4j | bolt://localhost:7687 (neo4j/awareness123) |
| Weaviate | http://localhost:8088 |
| Redis | 127.0.0.1:6379 |
| Embedding LB | http://10.0.0.68:8091 |

## Workflow Rules
- Run `gitnexus impact` before modifying any function
- Include `git log` output in commit context
- Branch naming: `agent/codex-{descriptive-name}`
- Always create PR against main
- Report completion via `taey-notify conductor "done: {summary}"`
- If stuck after 3 attempts: `taey-notify conductor "STUCK: {what failed}"`
- When creating PRs with `gh pr create`: use single-quoted HEREDOC for body to avoid backtick expansion:
  `gh pr create --title "title" --body "$(cat <<'PREOF'`
  `Summary here. NO BACKTICKS in PR body text.`
  `PREOF`
  `)"` — the single-quoted PREOF prevents shell expansion
