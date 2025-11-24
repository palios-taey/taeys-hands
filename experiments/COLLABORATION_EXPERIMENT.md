# Experiment: Optimal AI Family Collaboration Pattern
## Research Question: Parallel vs Sequential vs Hybrid

---

## Hypothesis Space

### Pattern A: Parallel (Fan-Out)
```
                    PROMPT
                      |
    +--------+--------+--------+--------+
    |        |        |        |        |
 Claude  ChatGPT   Grok   Perplexity  Gemini
    |        |        |        |        |
    +--------+--------+--------+--------+
                      |
                 SYNTHESIS
```

**Prediction**: High diversity, low coherence. Each AI works in isolation. May get redundant insights or contradictions.

### Pattern B: Sequential (Chain)
```
PROMPT → Grok (reality) → +Grok → ChatGPT (engineer) → +both → Perplexity (cite) → +all → Claude Chat (synth)
```

**Prediction**: High coherence, compounding insights. But slower. Later AIs may be biased by earlier responses.

### Pattern C: Hub-Spoke (Synthesis Loop)
```
Round 1: PROMPT → All (parallel)
Round 2: PROMPT + All_Responses → All (parallel)
Round 3: Converge
```

**Prediction**: Best of both? But 2x time cost.

### Pattern D: Heavy Context (60% Attachment)
```
PROMPT (40%) + [all_docs.md, code.js, history.md] (60%) → Single AI → Perfect Response
```

**Prediction**: Maximum context = maximum quality? Or context overload?

---

## Experimental Design

### Arm 1: Parallel
1. Same prompt to Claude Chat, ChatGPT, Grok, Perplexity
2. Attachment: ULTRATHINK_SYNTHESIS.md only
3. Collect all 4 responses
4. Measure: Time, token count, unique insights, contradictions

### Arm 2: Sequential
1. Grok first (reality check)
2. ChatGPT second (+Grok's response)
3. Perplexity third (+Grok+ChatGPT)
4. Claude Chat fourth (+all three)
5. Measure: Time, compounding effect, bias detection

### Arm 3: Hybrid (if time permits)
1. Parallel round 1
2. Synthesize
3. Send synthesis back to all
4. Compare round 2 responses to round 1

---

## Metrics

| Metric | Definition | How to Measure |
|--------|------------|----------------|
| **Novel Insights** | Ideas not in input prompt | Manual count |
| **Redundancy** | Same point made by multiple AIs | Semantic similarity |
| **Contradiction** | Conflicting claims | Manual identification |
| **Build-On Effect** | Later AI references earlier | Explicit citations |
| **Time Cost** | Wall clock time | Timestamp delta |
| **Token Efficiency** | Insight per token | Novel insights / response length |

---

## Control Variables

- Same base prompt for all arms
- Same attachment (ULTRATHINK_SYNTHESIS.md)
- Same time of day (API load)
- Same detection timeout (5 min)

---

## The Prompt (Shared)

```
I'm running an experiment on AI collaboration patterns.

Context: Taey's Hands browser automation is working. I can now coordinate
AI family members (Claude, ChatGPT, Gemini, Grok, Perplexity) through
their chat interfaces. The question: What's the optimal collaboration pattern?

Your task: Review the attached synthesis and answer:

1. What's ONE thing in this architecture that will definitely break in production?
2. What's ONE insight the synthesis missed that you uniquely see?
3. If you could ask ONE question to another AI family member, what would it be and to whom?

Be specific. Be concise. This is for research comparison.
```

---

## Execution Plan

### Phase 1: Parallel Arm
```javascript
// pseudo-code
const responses = await Promise.all([
  sendToClaudeChat(prompt, attachment),
  sendToChatGPT(prompt, attachment),
  sendToGrok(prompt, attachment),
  sendToPerplexity(prompt, attachment)
]);
```

### Phase 2: Sequential Arm
```javascript
const grok = await sendToGrok(prompt, attachment);
const chatgpt = await sendToChatGPT(prompt + grok.response, attachment);
const perplexity = await sendToPerplexity(prompt + grok.response + chatgpt.response, attachment);
const claude = await sendToClaudeChat(prompt + all_previous, attachment);
```

### Phase 3: Analysis
- Compare response quality
- Identify pattern-specific advantages
- Determine optimal use cases for each pattern

---

## Expected Outcome

**My prediction**:
- Parallel wins for divergent exploration (brainstorming, finding blindspots)
- Sequential wins for convergent synthesis (building a coherent answer)
- Hybrid wins for complex multi-step problems
- Heavy context wins for deep technical analysis of specific code

**The real question**: Can we detect WHICH pattern to use based on the task type?

---

## Files Created

- `experiments/parallel_arm.mjs` - Parallel execution script
- `experiments/sequential_arm.mjs` - Sequential execution script
- `experiments/results/` - Response storage
- `experiments/analysis.md` - Final comparison

---

*This is how we figure out the optimal collaboration pattern.*
*Not by guessing. By measuring.*

claude@taey.ai
