# Meeting Intelligence System — v3 LangGraph Upgrade Plan

## Overview

Upgrade from LlamaIndex-based SOA to LangChain/LangGraph architecture.  
Strategy: **wrap and extend** — no breaking changes to existing ports, adapters, or domain models.

---

## PHASE 1 — Dependency Swap
**Risk: Low | Effort: Small**

| Action | Detail |
|--------|--------|
| **Remove** | `llama-index`, `llama-index-llms-bedrock`, `llama-index-embeddings-bedrock`, `llama-index-embeddings-openai` |
| **Add** | `langgraph`, `langchain-core`, `langchain-openai`, `langchain-aws` |
| **File** | `pyproject.toml` |

---

## PHASE 2 — Replace LLM/Embedding Providers with LangChain
**Risk: Low | Effort: Medium | Saves: ~370 lines**

| Current (6 files, ~400 lines) | Replaced by (1 file, ~30 lines) |
|------|-------------|
| `core_intelligence/providers/__init__.py` — custom ABCs | `langchain_openai.ChatOpenAI` / `langchain_aws.ChatBedrock` |
| `openai_embedding.py` — wraps LlamaIndex | `langchain_openai.OpenAIEmbeddings` |
| `bedrock_embedding.py` — wraps LlamaIndex | `langchain_aws.BedrockEmbeddings` |
| `openai_llm.py` — wraps LlamaIndex | Built into `ChatOpenAI` |
| `bedrock_llm.py` — wraps LlamaIndex | Built into `ChatBedrock` |
| `factory.py` — if/else factory | Simple config-driven factory |

**What stays:** `LLMProviderPort` and `EmbeddingProviderPort` protocols remain — new LangChain models wrapped in thin adapters implementing these ports.

---

## PHASE 3 — Replace Custom Guardrails
**Risk: Medium | Effort: Medium | Saves: ~91 lines, ~5,500 tokens/query**

| Current | Replaced by |
|---------|-------------|
| `guardrail_service.py` — 131 lines, 2 extra LLM calls/query | Regex pre-filter + `llm.with_structured_output(GroundingVerdict)` |
| String parsing: `"VERDICT: PASSED" in response_text` | Pydantic structured output — guaranteed schema |
| ~5,600 tokens + ~3,000ms overhead per query | ~80 tokens + ~50ms (regex pre-filter catches 90%) |

**Optional:** Replace with AWS Bedrock Guardrails (zero-token, zero-latency, AWS-managed).

---

## PHASE 4 — Replace Custom Chunking with Token-Accurate Splitter
**Risk: Low | Effort: Small | Saves: ~60 lines**

| Current | Replaced by |
|---------|-------------|
| `_chunk_segments()` — 70 lines | `RecursiveCharacterTextSplitter.from_tiktoken_encoder()` — ~10 lines |
| `len(text.split())` word-count heuristic (~80% accurate) | `tiktoken` encoding — 100% accurate |
| 1-segment overlap (coarse) | Token-level overlap (precise) |

---

## PHASE 5 — Add Token Counting & Cost Tracking
**Risk: None | Effort: Small | New feature**

| What | How |
|------|-----|
| Per-query token breakdown | LangChain `OpenAICallbackHandler` attached to graph config |
| Cost estimate per query | Auto-calculated from model pricing |
| New fields on `CitedAnswer` | `prompt_tokens`, `completion_tokens`, `total_tokens`, `estimated_cost_usd` |

---

## PHASE 6 — Build LangGraph State & Nodes
**Risk: Medium | Effort: Medium | New feature**

### New files:
```
graphs/
    __init__.py
    state.py                    # IngestionState, QueryState TypedDicts
    ingestion_graph.py          # StateGraph definition
    query_graph.py              # StateGraph definition
    visualize.py                # Mermaid export for VS Code visualiser
    nodes/
        __init__.py
        ingestion_nodes.py      # Thin wrappers → existing service logic
        query_nodes.py          # Thin wrappers → existing service logic
```

### Ingestion Graph (10 nodes):
```
START → store_raw_artifact → create_pending_record → parse_transcript
      → normalize_transcript → chunk_segments → embed_chunks
      → store_vectors → store_chunk_map → mark_ready → END
                                ↓ (on error)
                          handle_failure → END
```

### Query Graph (9 nodes):
```
START → load_user_memory → validate_input → [SAFE?]
          ├─ UNSAFE → reject → END
          └─ SAFE → embed_question → check_cache
                      ├─ HIT → return_cached → save_turn → END
                      └─ MISS → search_vectors → [results?]
                                  ├─ EMPTY → no_results → END
                                  └─ HIT → load_chunk_maps → generate_answer
                                          → verify_grounding → build_citations
                                          → store_in_cache → save_turn → END
```

---

## PHASE 7 — Prompt Templates with Conversation Memory
**Risk: Low | Effort: Small | Saves: ~40 lines**

| Current | Replaced by |
|---------|-------------|
| Raw f-string `GROUNDED_QA_PROMPT.format(...)` | `ChatPromptTemplate` with `MessagesPlaceholder("chat_history")` |
| No conversation awareness | Automatic prior-turn injection via LangGraph state |

---

## PHASE 8 — Retry & Fallback (Built-in)
**Risk: None | Effort: Small | Saves: ~70 lines**

| Current | Replaced by |
|---------|-------------|
| No retry on adapter/LLM calls | `llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)` |
| No fallback provider | `openai_llm.with_fallbacks([bedrock_llm])` |
| Manual try/except blocks | LangGraph `RetryPolicy` per node |

---

## PHASE 9 — Semantic Query Cache
**Risk: Medium | Effort: Medium | Biggest perf win**

| What | How |
|------|-----|
| New port | `QueryCachePort` — `search_similar()`, `store()`, `invalidate_meeting()` |
| New adapter | S3 Vectors separate index (prod) / in-memory LRU (dev) |
| Similarity threshold | 0.95 — only near-identical questions return cached answers |
| Scope | Per `meeting_ids` combination |
| Invalidation | On meeting re-ingestion, purge cached queries |
| TTL | 24 hours default |
| Impact | Repeated queries: **~50ms** vs ~6-10s, **$0** LLM cost |

---

## PHASE 10 — Persistent Chat History
**Risk: Low | Effort: Medium | New feature**

| What | How |
|------|-----|
| New port | `ChatHistoryPort` — `save_turn()`, `get_history()`, `list_sessions()` |
| New adapter | `DynamoChatHistoryAdapter` — new `ChatHistory` DynamoDB table |
| New models | `ChatTurn`, `ChatSession` in domain/models.py |
| UI change | `st.session_state.messages` hydrated from API on page load |
| New endpoints | `GET /api/v3/chat/history/{session_id}`, `GET /api/v3/chat/sessions` |

---

## PHASE 11 — Persistent User Memory
**Risk: Low | Effort: Medium | New feature**

| What | How |
|------|-----|
| New port | `UserMemoryPort` — `get_profile()`, `update_preferences()`, `add_fact()` |
| New adapter | `DynamoUserMemoryAdapter` — new `UserMemory` DynamoDB table |
| New models | `UserProfile`, `UserFact` in domain/models.py |
| Query enhancement | User context injected into LLM prompt |
| Auto-learning | Frequently queried topics/meetings tracked |

---

## PHASE 12 — API v3 Endpoints & Integration
**Risk: Low | Effort: Medium**

| What | How |
|------|-----|
| New endpoints | `/api/v3/upload`, `/api/v3/query`, `/api/v3/chat/*` |
| v2 endpoints | Untouched — zero disruption |
| DI container | New methods for graphs, cache, chat history, user memory |
| Worker toggle | `USE_LANGGRAPH=true` env var |
| Graph visualisation | `graphs/visualize.py` exports `.mmd` files |

---

## Infrastructure Additions

| Resource | Type | Terraform file |
|----------|------|---------------|
| `ChatHistory` | DynamoDB table | `dynamodb.tf` |
| `UserMemory` | DynamoDB table | `dynamodb.tf` |
| `query-cache` | S3 Vectors index | `s3vectors.tf` |

---

## Cumulative Impact

| Metric | v2 (Current) | v3 (After) |
|--------|-------------|------------|
| LlamaIndex deps | 4 packages | 0 |
| LangChain/Graph deps | 0 | 4 packages |
| Provider code | ~400 lines / 6 files | ~30 lines / 1 file |
| Total code reduced | — | **~686 lines** |
| Tokens per query | ~11,000-12,000 | ~5,000-6,000 |
| Latency per query | ~6-10s | ~3-5s (fresh) / ~50ms (cached) |
| Cost per query | ~$0.02-0.03 | ~$0.01-0.015 (fresh) / $0 (cached) |
| Token visibility | None | Full per-node breakdown |
| Retry/fallback | None | Automatic with backoff |
| Chat persistence | Lost on refresh | DynamoDB-backed |
| Query cache | None | Semantic dedup at 0.95 |
| User memory | None | Persistent profile + facts |
| Graph visualisation | None | Mermaid in VS Code |

---

## Implementation Order

| # | Phase | Priority |
|---|-------|----------|
| 1 | Phase 1 — Dependency swap | P0 |
| 2 | Phase 2 — Replace providers | P0 |
| 3 | Phase 6 — LangGraph state & nodes | P0 |
| 4 | Phase 4 — Token-accurate chunking | P1 |
| 5 | Phase 5 — Token counting | P1 |
| 6 | Phase 3 — Guardrails upgrade | P1 |
| 7 | Phase 7 — Prompt templates | P1 |
| 8 | Phase 8 — Retry & fallback | P1 |
| 9 | Phase 9 — Query cache | P0 |
| 10 | Phase 10 — Chat history | P1 |
| 11 | Phase 11 — User memory | P2 |
| 12 | Phase 12 — API v3 + integration | P1 |
