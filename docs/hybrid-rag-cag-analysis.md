# Hybrid RAG + CAG Analysis for MilVet Navigator

## What Are RAG and CAG?

| Approach | How It Works | When Context Is Loaded |
|---|---|---|
| **RAG** (Retrieval-Augmented Generation) | Searches an external index (Azure AI Search) at query time, retrieves top-K relevant chunks, injects them into the prompt | Every request — dynamic retrieval |
| **CAG** (Cache-Augmented Generation) | Pre-loads the full knowledge base (or a curated subset) directly into the model's context window as part of the system prompt | Once at session/prompt build time — static context |
| **Hybrid RAG+CAG** | Core knowledge lives in the prompt (CAG); edge-case or deep-dive queries fall through to a search index (RAG) | Core = static; deep = dynamic |

---

## Current Architecture (Pure RAG)

```
User Query
    │
    ▼
┌──────────────────┐     ┌────────────────────┐
│  Azure OpenAI    │◄────│  Azure AI Search   │  ← $250/month (Standard)
│  (gpt-35-turbo)  │     │  top_k=5 chunks    │
│                  │     │  256 tokens/chunk   │
│  System Prompt   │     │  Embeddings: ada-002│
│  (~450 tokens)   │     └────────────────────┘
│                  │
│  Full History    │     ┌────────────────────┐
│  (no trimming)   │◄────│  CosmosDB Cache    │  ← SequenceMatcher 90%
│                  │     │  40 recent entries  │
│  Max Output:1000 │     └────────────────────┘
└──────────────────┘
```

### Current Per-Request Token Budget (Estimated)

| Component | Tokens | % of Input |
|---|---|---|
| System prompt (Milly persona) | ~450 | 15% |
| Conversation history (avg 5 turns) | ~1,500 | 50% |
| RAG context (5 chunks × 256 tok) | ~1,280 | 35% |
| **Total input per request** | **~3,230** | 100% |
| Output (response) | ~400 | — |

### Current Monthly Costs (RAG-Only, Estimated)

| Component | 300 Users | 5,000 Users | 20,000 Users |
|---|---|---|---|
| Azure AI Search (Standard) | $250 | $250 | $250-500 |
| Azure OpenAI API (GPT-3.5-Turbo) | $6 | $106 | $425 |
| Embedding API (ada-002) | $0.08 | $1.25 | $5 |
| CosmosDB | $5-10 | $24 | $60-200 |
| App Service | $13 | $70-80 | $110-330 |
| **Total** | **~$274** | **~$451** | **~$850-1,460** |

> Azure AI Search is **54-91%** of total cost at low-to-mid user counts. This is the main optimization target.

---

## Proposed Hybrid Architecture (RAG + CAG)

```
User Query
    │
    ▼
┌─────────────────────────────────────────────┐
│  Azure OpenAI (GPT-4o or GPT-4o-mini)       │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  SYSTEM PROMPT (CAG Layer)          │    │
│  │  ┌───────────────────────────────┐  │    │
│  │  │  Milly Persona (~450 tok)     │  │    │
│  │  │  ───────────────────────────  │  │    │
│  │  │  Core Knowledge Base          │  │    │   ← Pre-loaded, prompt-cached
│  │  │  • FAQs & service overview    │  │    │
│  │  │  • Benefit summaries          │  │    │
│  │  │  • Eligibility criteria       │  │    │
│  │  │  • Pricing tiers              │  │    │
│  │  │  • Contact/process info       │  │    │
│  │  │  (~4,000-12,000 tokens)       │  │    │
│  │  └───────────────────────────────┘  │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Conversation History                       │
│  (trimmed to last N turns)                  │
│                                             │
│  IF query needs deep/specific data:         │
│  ┌─────────────────────┐                    │
│  │  RAG Fallback        │◄── Azure AI Search │   ← Only for edge cases
│  │  (top_k=3, on demand)│    (can downgrade  │
│  └─────────────────────┘     to Basic/Free)  │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│  CosmosDB Cache     │  ← Existing cache still active
│  (enhanced)         │
└─────────────────────┘
```

---

## How Hybrid Works — Decision Flow

```
1. User sends question
       │
       ▼
2. Check CosmosDB cache (existing)
       │
   ┌───┴───┐
   │Cache  │──YES──► Return cached answer (no API call)
   │Hit?   │
   └───┬───┘
       │NO
       ▼
3. Build prompt with CAG context (core knowledge in system prompt)
       │
       ▼
4. Ask model: "Can you answer this fully from the provided knowledge?"
       │
   ┌───┴──────┐
   │Confident │──YES──► Return CAG-only answer (no search call)
   │Answer?   │
   └───┬──────┘
       │NO / LOW CONFIDENCE
       ▼
5. RAG fallback: Query Azure AI Search for specific documents
       │
       ▼
6. Augment prompt with retrieved chunks + answer
```

### Implementation Approach — Query Router

```python
# In app.py — add after cache check, before OpenAI call

async def should_use_rag(question: str, cag_knowledge_topics: list[str]) -> bool:
    """
    Determine if a question needs RAG retrieval or can be answered from CAG context.
    Simple keyword/intent check — no API call needed.
    """
    question_lower = question.lower()

    # Questions about specific policies, regulations, or detailed program data
    rag_indicators = [
        "specific", "exact", "policy number", "regulation",
        "chapter 33", "chapter 35", "gi bill calculation",
        "my specific", "my eligibility", "how much will I get",
        "compare programs", "detailed breakdown",
    ]

    # If question matches core MVN topics, CAG is sufficient
    cag_indicators = [
        "what is mvn", "what does mvn", "how to get started",
        "services", "help", "demo", "pricing", "contact",
        "tuition calculator", "benefits overview", "who are you",
        "hello", "hi", "thanks", "schedule",
    ]

    if any(indicator in question_lower for indicator in cag_indicators):
        return False  # CAG is enough

    if any(indicator in question_lower for indicator in rag_indicators):
        return True  # Need RAG

    # Default: try CAG first (cheaper)
    return False
```

---

## Cost Comparison: RAG-Only vs. Hybrid RAG+CAG

### Assumptions for Hybrid

| Parameter | RAG-Only (Current) | Hybrid RAG+CAG |
|---|---|---|
| System prompt | ~450 tokens | ~6,000 tokens (persona + core knowledge) |
| RAG retrieval | Every request | ~20-30% of requests (edge cases only) |
| Azure AI Search tier | Standard ($250/mo) | Basic ($75/mo) or Free |
| Cache hit rate | ~15-20% | ~25-35% (better answers = more cache reuse) |
| Model | GPT-3.5-Turbo-16K | GPT-4o-mini (better + cheap enough for CAG) |
| Prompt caching | Not available | Azure OpenAI prompt caching (50% discount on cached prefix) |

### Token Budget Per Request (Hybrid)

| Component | First Request | Subsequent (Prompt Cached) |
|---|---|---|
| System prompt + CAG knowledge | ~6,000 tokens (full price) | ~6,000 tokens (**50% off** via prompt cache) |
| Conversation history (trimmed to 6 turns) | ~1,200 | ~1,200 |
| RAG context (only 20-30% of requests) | ~768 (3 chunks × 256) | ~768 |
| **Total input** | **~7,200-7,968** | **~7,200-7,968** (but 6K cached) |
| **Effective billed input** | ~7,968 | **~4,968** (3K saved from cache) |

### Monthly Cost — Hybrid with GPT-4o-mini

GPT-4o-mini pricing: Input $0.15/1M tokens, Output $0.60/1M tokens
Prompt cache discount: 50% on cached prefix (first 6,000 tokens)

**Per-request cost calculation (after prompt cache warm-up):**
- Cached input: 6,000 × $0.075/1M = $0.00045
- Uncached input: 1,968 × $0.15/1M = $0.000295
- Output: 400 × $0.60/1M = $0.00024
- **Per request: ~$0.00099** (vs. current GPT-3.5 at ~$0.00085)

Slightly more per request, BUT Azure AI Search drops from $250 → $75 (Basic) or $0 (Free).

| Component | 300 Users | 5,000 Users | 20,000 Users |
|---|---|---|---|
| **Azure AI Search** | **$0-75** (Free/Basic) | **$75** | **$75** |
| Azure OpenAI API (GPT-4o-mini) | $5 | $82 | $330 |
| Prompt cache savings | -$1.70 | -$28 | -$113 |
| CosmosDB | $5-10 | $24 | $60-200 |
| App Service | $13 | $70-80 | $110-330 |
| **Hybrid Total** | **~$21-102** | **~$223** | **~$462-822** |
| **RAG-Only Total (current)** | **~$274** | **~$451** | **~$850-1,460** |
| **Monthly Savings** | **$172-253** | **$228** | **$388-638** |
| **% Savings** | **63-92%** | **51%** | **44-46%** |

### Annual Savings

| Scale | Annual Savings (Hybrid vs. RAG-Only) |
|---|---|
| 300 users | **$2,064 – $3,036** |
| 5,000 users | **$2,736** |
| 20,000 users | **$4,656 – $7,656** |

---

## Hybrid with GPT-4o (Higher Quality)

If quality matters more than absolute minimum cost, GPT-4o is also viable in hybrid mode:

| Component | 300 Users | 5,000 Users | 20,000 Users |
|---|---|---|---|
| Azure AI Search | $0-75 | $75 | $75 |
| Azure OpenAI API (GPT-4o) | $38 | $630 | $2,520 |
| Prompt cache savings (50%) | -$8 | -$140 | -$563 |
| Infrastructure | $18-23 | $94-104 | $170-530 |
| **Hybrid GPT-4o Total** | **~$48-128** | **~$659** | **~$2,202-2,562** |

GPT-4o hybrid is still cheaper than RAG-only GPT-3.5 at 300-5,000 users because eliminating Azure AI Search Standard ($250/mo) offsets the higher API cost.

---

## What Goes Into the CAG Knowledge Layer

The CAG layer should contain **curated, stable knowledge** that covers 70-80% of user queries:

### Recommended CAG Content (~4,000-12,000 tokens)

```markdown
## MilVet Navigator — Core Knowledge Base

### 1. About MVN (200 tokens)
- Mission, founding story, value proposition
- Key differentiators vs. other veteran services

### 2. Services Overview (500 tokens)
- Education benefit navigation
- Career transition support
- Tuition benefits calculator explanation
- Personalized guidance process

### 3. Eligibility & Benefits Summary (1,500 tokens)
- GI Bill overview (Ch. 33, Ch. 35, Ch. 31)
- Tuition assistance programs
- State-specific benefits (top 10 states)
- Dependent/spouse benefits

### 4. Getting Started Guide (400 tokens)
- Step-by-step onboarding process
- What to expect from a demo
- Required documents/information

### 5. FAQ — Top 20 Questions (2,000 tokens)
- Pre-written Q&A pairs for most common questions
- Covers pricing, timelines, eligibility, process

### 6. Contact & Resources (200 tokens)
- All contact channels, hours, response times
- Links to calculator, demo, website sections

### 7. Competitive Positioning (500 tokens)
- Why MVN vs. DIY / other services
- Success stories / metrics (if available)
```

### What Stays in RAG (Retrieved On-Demand)

- Detailed policy documents (too long for context)
- Specific regulatory text (Ch. 33 calculations, VA rules)
- Dynamic content (blog posts, news, event schedules)
- User-specific eligibility calculations
- Detailed program comparisons with full data tables

---

## Implementation Plan

### Phase 1: CAG Layer (1-2 days)

1. **Curate core knowledge** — Extract top FAQ answers, service descriptions, and eligibility summaries from existing search index into a structured markdown document
2. **Embed in system prompt** — Append the knowledge block to the Milly persona prompt
3. **Enable prompt caching** — Azure OpenAI automatically caches repeated prompt prefixes (no code change needed, just ensure the system prompt + knowledge block is identical across requests)
4. **Add history trimming** — Limit conversation history to last 6 turns to stay within token budget

### Phase 2: Query Router (1 day)

5. **Add simple intent classifier** — Keyword-based router (shown above) that decides CAG-only vs. RAG-augmented
6. **Reduce top_k** — Drop from 5 to 3 chunks for RAG requests (still effective, fewer tokens)
7. **Downgrade Azure AI Search** — Move from Standard ($250/mo) to Basic ($75/mo) since RAG volume drops 70-80%

### Phase 3: Enhanced Caching (1 day)

8. **Lower cache threshold** — Drop from 0.9 to 0.85 (safe since CAG answers are more consistent)
9. **Increase cache scan window** — From 40 to 100 entries for better hit rates
10. **Add embedding-based cache matching** — Replace SequenceMatcher with cosine similarity on cached question embeddings (more accurate)

---

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| CAG knowledge becomes stale | Medium | Version the knowledge doc; update on content changes; add `last_updated` timestamp |
| Context window overflow with long conversations | Medium | Trim history to 6 turns; add token counting before API call |
| Query router misclassifies (sends to CAG when RAG needed) | Low | Default to CAG; let the model self-assess confidence; add "I'm not 100% sure" → RAG fallback |
| Prompt caching not effective (low cache hit rate) | Low | Keep system prompt + knowledge block IDENTICAL across all requests; don't include dynamic data in the cached prefix |
| Loss of document-level access control | Low | MVN's content appears to be public-facing; if private docs exist, keep those in RAG only |

---

## Recommendation

**YES — a hybrid RAG+CAG approach is strongly recommended for MilVet Navigator.**

### Why It's a Good Fit

1. **Bounded domain**: MVN's knowledge base (veteran education benefits, services, FAQs) is well-defined and stable — ideal for CAG
2. **Azure AI Search is your biggest cost**: At $250/month, it dominates infrastructure spend for < 5,000 users. Hybrid lets you downgrade or eliminate it
3. **Repetitive queries**: Veteran-facing chatbots see high query repetition (eligibility, "how do I start", pricing). CAG + cache handles 80%+ of these without any search call
4. **Prompt caching is free money**: Azure OpenAI's automatic prompt caching gives a 50% discount on the knowledge-heavy prefix — no code change required
5. **Better answer quality**: The model having ALL core knowledge in context produces more coherent, complete answers than retrieving 5 random chunks

### Recommended Configuration

| Setting | Value |
|---|---|
| **Model** | GPT-4o-mini (best cost/quality for this use case) |
| **CAG knowledge size** | 6,000-10,000 tokens |
| **RAG fallback** | Azure AI Search Basic ($75/mo), top_k=3 |
| **History trimming** | Last 6 turns max |
| **Cache threshold** | 0.85 (lowered from 0.9) |
| **Cache scan window** | 100 entries (up from 40) |
| **Expected RAG call rate** | 20-30% of requests |
| **Expected savings** | 44-92% depending on scale |
