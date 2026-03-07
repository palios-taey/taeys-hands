#!/bin/bash
# Monitor The Family — run periodically to check agent health and post to dashboard
DASHBOARD="http://10.0.0.68:5001"

echo "=== THE FAMILY STATUS $(date) ==="

# Check all agents
agents=$(curl -s "$DASHBOARD/api/agents")
alive=$(echo "$agents" | python3 -c "import sys,json; print(sum(1 for a in json.load(sys.stdin) if a['alive']))")
total=$(echo "$agents" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "Agents: $alive/$total alive"

# Check each agent
echo "$agents" | python3 -c "
import sys, json
for a in json.load(sys.stdin):
    dot = 'UP  ' if a['alive'] else 'DOWN'
    print(f'  [{dot}] {a[\"name\"]:20s} {a[\"role\"]:12s} {a[\"machine\"]}')
"

# Recent events
echo ""
echo "=== RECENT EVENTS ==="
curl -s "$DASHBOARD/api/events?count=5" | python3 -c "
import sys, json
for e in json.load(sys.stdin):
    ts = (e.get('timestamp', '') or '')[:19]
    et = e.get('event_type', '')
    actor = e.get('actor', '')
    print(f'  {ts}  {et:20s}  {actor}')
"

# Pulse
echo ""
echo "=== PULSE ==="
curl -s "$DASHBOARD/api/pulse" | python3 -c "
import sys, json
p = json.load(sys.stdin)
neo = p.get('neo4j', {})
print(f'  Redis: {p.get(\"redis_keys\", 0)} keys | HMM: {p.get(\"hmm_tiles\", 0)} tiles')
print(f'  Neo4j: {neo.get(\"messages\", 0)} msgs | {neo.get(\"exchanges\", 0)} exchanges | {neo.get(\"projects\", 0)} projects')
print(f'  Events: {p.get(\"orch_events\", 0)} | Tasks: {p.get(\"orch_tasks\", 0)}')
"
