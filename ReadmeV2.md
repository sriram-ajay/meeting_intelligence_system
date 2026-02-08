# Meeting Intelligence System — V2 Architecture & Migration Plan

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Tech Stack Overview](#2-tech-stack-overview)
3. [V1 Architecture (Baseline)](#3-v1-architecture-baseline)
4. [V2 Architecture (Target)](#4-v2-architecture-target)
5. [Reused vs Replaced Components](#5-reused-vs-replaced-components)
6. [Networking & VPC Endpoints](#6-networking--vpc-endpoints)
7. [DynamoDB Schema](#7-dynamodb-schema)
8. [API Contract](#8-api-contract)
9. [Ingestion Worker](#9-ingestion-worker)
10. [Query Path & Citations](#10-query-path--citations)
11. [Guardrails](#11-guardrails)
12. [Evaluation & Monitoring](#12-evaluation--monitoring)
13. [Configuration](#13-configuration)
14. [Project Structure (Post-Migration)](#14-project-structure-post-migration)
15. [Migration Slices](#15-migration-slices)
16. [IaC Summary](#16-iac-summary)
17. [CI/CD Changes](#17-cicd-changes)
18. [Quality Gates](#18-quality-gates)

---

## 1. Executive Summary

V2 refactors the Meeting Intelligence System from a monolithic LlamaIndex/LanceDB
architecture into a clean-architecture, AWS-native system using S3, DynamoDB,
S3 Vectors, and ECS Fargate (including an asynchronous ECS RunTask ingestion worker).

**Principles:**
- Reuse existing code wherever possible (providers, parser, guardrails, logging, validation).
- Clean architecture: domain → ports → adapters → services → orchestration.
- Production-grade: no pseudo-code, no shortcuts, no duplicated code.
- Repo must stay runnable after every slice.

---

## 2. Tech Stack Overview

| Layer | V1 | V2 |
|-------|----|----|
| Compute (UI) | ECS Fargate | ECS Fargate (private subnets) |
| Compute (API) | ECS Fargate | ECS Fargate (private subnets) |
| Compute (Ingestion) | Synchronous in API | ECS RunTask (async worker, private subnets) |
| Vector Store | LanceDB (local/S3 via LlamaIndex) | Amazon S3 Vectors |
| Metadata Store | LanceDB metadata columns | Amazon DynamoDB |
| Artifact Storage | Local filesystem | Amazon S3 (raw + derived prefixes) |
| LLM | Bedrock / OpenAI via LlamaIndex | Bedrock (default) / OpenAI (fallback) via existing providers |
| Embeddings | Bedrock / OpenAI via LlamaIndex | Bedrock (default) / OpenAI (fallback) via existing providers |
| Networking | Public subnets, public IPs | Private subnets, no public IPs, no NAT, VPC endpoints |
| Evaluation | RAGAS (local file) | RAGAS (S3 derived prefix) |
| Caching | None | In-process TTL/LRU in FastAPI only |

---

## 3. V1 Architecture (Baseline)

### Data Flow

```
UI (Streamlit) ──HTTP──▶ API (FastAPI) ──▶ TranscriptParser
                                             │
                                             ▼
                                          RAGEngine
                                           ├─ ChunkingStrategy (Semantic/Segment)
                                           ├─ LanceDB (local/S3 via LlamaIndex)
                                           ├─ RetrievalStrategy (Hybrid/RagFusion)
                                           ├─ GuardrailEngine (input + grounding)
                                           └─ EvaluationEngine (RAGAS → local JSON)
```

### Key V1 characteristics
- **Synchronous:** Upload, parse, chunk, embed, index — all in the API request lifecycle.
- **LlamaIndex-coupled:** RAGEngine, chunking, retrieval, embedding strategies all depend on LlamaIndex abstractions.
- **LanceDB:** Single vector store; metadata embedded in vector rows.
- **No DynamoDB:** No meeting-level metadata store.
- **No S3 artifacts:** No raw/derived transcript storage.
- **Public networking:** ECS tasks in public subnets with public IPs.

---

## 4. V2 Architecture (Target)

### Data Flow

```
UI (Streamlit) ──HTTP──▶ ALB ──▶ API (FastAPI, private subnet)
                                    │
                    ┌───────────────┼───────────────────┐
                    ▼               ▼                   ▼
              POST /upload    POST /query         GET /meetings
                    │               │                   │
                    ▼               ▼                   ▼
              S3 (raw)        QueryService        DynamoDB scan
              DynamoDB         │                       │
              (PENDING)        ├─ DynamoDB lookup      │
              ECS RunTask      ├─ S3 Vectors search    │
                    │          ├─ LLM (Bedrock)        │
                    ▼          ├─ Guardrails            │
              Worker (private) └─ Citations             │
                    │                                   │
                    ├─ Parse (TranscriptParser)          
                    ├─ Chunk (speaker-turn aware)        
                    ├─ Embed (Bedrock)                   
                    ├─ S3 Vectors (store)                
                    ├─ S3 (derived artifacts)            
                    └─ DynamoDB (READY/FAILED)           
```

### Architecture Boundaries (Non-Negotiable)

```
domain/          Pure models and logic. NO boto3, NO AWS imports.
ports/           Protocol/ABC interfaces: VectorStorePort, MetadataStorePort,
                 ArtifactStorePort, LLMProviderPort.
adapters/        AWS implementations: S3ArtifactStoreAdapter,
                 DynamoMetadataStoreAdapter, S3VectorsVectorStoreAdapter.
services/        IngestionService, QueryService.
orchestration/   LangGraph workflows (bounded, deterministic).
```

---

## 5. Reused vs Replaced Components

### Reused Unchanged (or near-unchanged)

| Module | Path | Notes |
|--------|------|-------|
| Pydantic settings base | `shared_utils/config_loader.py` | Extend with new fields; core pattern stays |
| Structured logging | `shared_utils/logging_utils.py` | Reuse as-is; add new scopes |
| Validation utilities | `shared_utils/validation.py` | Reuse `InputValidator` as-is |
| Error hierarchy | `shared_utils/error_handler.py` | Reuse all exception classes; add `IngestionError` |
| Constants framework | `shared_utils/constants.py` | Extend enums; keep structure |
| Provider ABCs | `core_intelligence/providers/__init__.py` | Reuse `EmbeddingProviderBase`, `LLMProviderBase` |
| Bedrock providers | `bedrock_embedding.py`, `bedrock_llm.py` | Reuse unchanged |
| OpenAI providers | `openai_embedding.py`, `openai_llm.py` | Reuse unchanged |
| Provider factory | `core_intelligence/providers/factory.py` | Reuse unchanged |
| Transcript parser | `core_intelligence/parser/cleaner.py` | Reuse `TranscriptParser`; wrap in v2 ingestion |
| Guardrails engine | `core_intelligence/engine/guardrails.py` | Reuse; enhance with citation gate |
| CI/CD pipeline | `.github/workflows/ci_cd_pipeline.yml` | Update for worker image + env vars |
| Dockerfiles | `api_service/Dockerfile`, `ui_service/Dockerfile` | Update deps; structure stays |

### Refactored (significant changes)

| Module | Current Path | Change |
|--------|-------------|--------|
| Settings model | `shared_utils/config_loader.py` | Add S3, DynamoDB, S3 Vectors, eval fields; env validator accepts `dev\|stage\|prod` |
| DI container | `shared_utils/di_container.py` | Extend to provide port implementations (adapters) |
| Pydantic models | `core_intelligence/schemas/models.py` | Add `MeetingRecord`, `ChunkMapEntry`, `IngestionReport`, `CitedAnswer` |
| API main | `api_service/src/main.py` | Rewrite for v2 endpoints; remove LanceDB-direct code |
| UI app | `ui_service/src/app.py` | Update for new API; add evaluation tab with RAGAS charts |
| Evaluation engine | `core_intelligence/engine/evaluation.py` | Store results in S3 derived prefix |

### New Modules

| Module | Path | Purpose |
|--------|------|---------|
| Domain models | `domain/models.py` | Pure domain (no AWS) |
| Ports | `ports/vector_store.py`, `metadata_store.py`, `artifact_store.py`, `llm_provider.py` | Interfaces |
| S3 Artifact Adapter | `adapters/s3_artifact_store.py` | boto3 S3 for raw + derived |
| DynamoDB Metadata Adapter | `adapters/dynamo_metadata_store.py` | boto3 DynamoDB |
| S3 Vectors Adapter | `adapters/s3vectors_vector_store.py` | boto3 S3 Vectors |
| IngestionService | `services/ingestion_service.py` | Parse → chunk → embed → store |
| QueryService | `services/query_service.py` | Metadata-first retrieval → LLM → citations |
| Worker entrypoint | `worker/entrypoint.py` | ECS RunTask for async ingestion |
| Worker Dockerfile | `worker/Dockerfile` | Container image |
| LangGraph workflows | `orchestration/workflows.py` | Bounded orchestration |

### Deleted (dead code)

| File | Reason |
|------|--------|
| `shared_utils/logging_config.py` | Marked DEPRECATED; replaced by `logging_utils.py` |
| `core_intelligence/database/manager.py` | LanceDB SchemaManager; replaced by DynamoDB + S3 Vectors |
| `core_intelligence/engine/rag.py` | Monolith RAGEngine; replaced by services |
| `core_intelligence/engine/strategies/retrieval.py` | LlamaIndex-specific; v2 uses S3 Vectors |
| `core_intelligence/engine/strategies/chunking.py` | LlamaIndex-specific; v2 chunking in IngestionService |
| `core_intelligence/engine/strategies/embedding.py` | Thin LlamaIndex wrapper; v2 calls providers directly |
| `core_intelligence/engine/strategies/query_expansion.py` | Folded into QueryService |
| `scripts/resync_db.py` | LanceDB-specific |

---

## 6. Networking & VPC Endpoints

### Network Topology

```
┌─────────────────────────────────────────────────────────────┐
│  VPC 10.0.0.0/16                                            │
│                                                             │
│  PUBLIC SUBNETS (ALB only)                                  │
│  ┌─────────────────┐   ┌─────────────────┐                 │
│  │ 10.0.1.0/24     │   │ 10.0.2.0/24     │                 │
│  │ AZ-a            │   │ AZ-b            │                 │
│  └────────┬────────┘   └────────┬────────┘                 │
│           │    ┌────────────┐   │                           │
│           └────┤    ALB     ├───┘   ◄── Internet Gateway    │
│                └─────┬──────┘                               │
│                      │ SG: allow from ALB                   │
│  PRIVATE SUBNETS (ECS tasks)                                │
│  ┌─────────────────┐ │ ┌─────────────────┐                 │
│  │ 10.0.3.0/24     │◄┘ │ 10.0.4.0/24     │                 │
│  │ AZ-a            │   │ AZ-b            │                 │
│  │ No public IPs   │   │ No public IPs   │                 │
│  │ No NAT          │   │ No NAT          │                 │
│  └─────────────────┘   └─────────────────┘                 │
│                                                             │
│  VPC ENDPOINTS                                              │
│  ├─ S3 Gateway ──────────── (public + private route tables) │
│  ├─ DynamoDB Gateway ────── (private route table)           │
│  ├─ ECR API Interface ───── (private subnet AZ-a)           │
│  ├─ ECR DKR Interface ───── (private subnet AZ-a)           │
│  ├─ CloudWatch Logs ──────── (private subnet AZ-a)          │
│  ├─ Bedrock Runtime ──────── (private subnet AZ-a)          │
│  ├─ Secrets Manager ──────── (private subnet AZ-a)          │
│  └─ ECS Interface ────────── (private subnet AZ-a)          │
└─────────────────────────────────────────────────────────────┘
```

### Endpoint Inventory

#### Gateway Endpoints (FREE)

| # | Service | Endpoint Name | Purpose |
|---|---------|---------------|---------|
| 1 | S3 | `com.amazonaws.{region}.s3` | Raw/derived buckets, S3 Vectors, ECR image layers |
| 2 | DynamoDB | `com.amazonaws.{region}.dynamodb` | Meeting metadata table |

#### Interface Endpoints (~$7.20/mo each in 1 AZ for Phase 1)

| # | Service | Endpoint Name | Purpose |
|---|---------|---------------|---------|
| 3 | ECR API | `com.amazonaws.{region}.ecr.api` | Container image manifest lookups |
| 4 | ECR Docker | `com.amazonaws.{region}.ecr.dkr` | Docker registry image layer pulls |
| 5 | CloudWatch Logs | `com.amazonaws.{region}.logs` | awslogs driver ships stdout/stderr |
| 6 | Bedrock Runtime | `com.amazonaws.{region}.bedrock-runtime` | LLM + embedding invocations |
| 7 | Secrets Manager | `com.amazonaws.{region}.secretsmanager` | Task definition secrets resolution |
| 8 | ECS | `com.amazonaws.{region}.ecs` | API calls RunTask for ingestion worker |

All interface endpoints: `private_dns_enabled = true`, placed in **AZ-a only** for Phase 1.

#### Phase 2 Expansion
Add AZ-b subnet to each interface endpoint's `subnet_ids` list. No code changes required.

#### Estimated Phase 1 Cost
6 interface endpoints × ~$7.20/mo = **~$43/month** + data processing (~$0.01/GB).

#### Not Needed

| Service | Reason |
|---------|--------|
| STS | Fargate uses metadata endpoint (169.254.170.2) for task roles |
| SSM | No SSM Parameter Store usage |
| ECS Agent/Telemetry | Fargate platform 1.4.0+ handles via AWS-managed ENI |
| KMS | S3 SSE uses AES256; no custom KMS keys in Phase 1 |

---

## 7. DynamoDB Schema

**Table:** `MeetingsMetadata`

| Attribute | Type | Key | Description |
|-----------|------|-----|-------------|
| `meeting_id` | String | PK | UUID, primary key |
| `title_normalized` | String | — | Lowercased, trimmed title |
| `meeting_date` | String | — | ISO 8601 date string |
| `participants` | String Set | — | Set of participant names |
| `s3_uri_raw` | String | — | `s3://bucket/raw/prefix/filename` |
| `s3_uri_derived_prefix` | String | — | `s3://bucket/derived/meeting_id/` |
| `doc_hash` | String | — | SHA-256 of raw transcript |
| `version` | Number | — | Schema version (starts at 1) |
| `ingestion_status` | String | — | `PENDING` / `READY` / `FAILED` |
| `ingested_at` | String | — | ISO 8601 timestamp |
| `error_message` | String | — | Optional; populated on FAILED |

---

## 8. API Contract

### POST /api/upload
Upload raw transcript → S3 → DynamoDB PENDING → ECS RunTask.

**Request:** `multipart/form-data` with `file` field (.txt)

**Response:**
```json
{
  "meeting_id": "uuid",
  "status": "PENDING"
}
```

### GET /api/status/{meeting_id}
**Response:**
```json
{
  "meeting_id": "uuid",
  "ingestion_status": "READY",
  "error_message": null
}
```

### GET /api/meetings?date=...&title=...&participant=...
Query DynamoDB with optional filters.

**Response:**
```json
{
  "meetings": [
    {
      "meeting_id": "uuid",
      "title_normalized": "quarterly review",
      "meeting_date": "2026-01-15",
      "participants": ["Alice", "Bob"],
      "ingestion_status": "READY"
    }
  ]
}
```

### POST /api/query
**Request:**
```json
{
  "query": "What were the action items?",
  "filters": {
    "meeting_id": "uuid",
    "date": "2026-01-15",
    "title": "quarterly",
    "participant": "Alice"
  }
}
```

**Response:**
```json
{
  "answer": "The action items discussed were...",
  "citations": [
    {
      "chunk_id": "chunk-001",
      "meeting_id": "uuid",
      "speaker": "Alice",
      "timestamp_start": "00:05:30",
      "timestamp_end": "00:06:15",
      "snippet": "We need to finalize the budget by Friday..."
    }
  ],
  "retrieved_context": ["..."]
}
```

---

## 9. Ingestion Worker

### Entry Point
`worker/entrypoint.py` — receives `meeting_id` and `s3_key` via environment variables or command args.

### Pipeline
1. Download raw transcript from S3.
2. Parse with `TranscriptParser` (reused from v1).
3. Apply fallback heuristics if structured parsing fails.
4. Extract metadata (title, date, participants).
5. Chunk with speaker-turn awareness (preserves timestamp ranges per chunk).
6. Generate embeddings via Bedrock (or OpenAI fallback).
7. Store embeddings in S3 Vectors with metadata.
8. Store derived artifacts in S3:
   - `normalized_transcript.json`
   - `chunk_map.json`
   - `ingestion_report.json`
9. Update DynamoDB: `ingestion_status = READY` (or `FAILED` with `error_message`).

### Failure Handling
- On any error: set `ingestion_status = FAILED` with actionable `error_message`.
- Only fail if parsing is truly impossible (not on minor formatting issues).

---

## 10. Query Path & Citations

### Flow
1. **Metadata-first retrieval:** Query DynamoDB by filters (date, title, participant, meeting_id).
2. **Scoped vector search:** Search S3 Vectors limited to matching `meeting_id`(s).
3. **LLM synthesis:** Bedrock generates answer grounded in retrieved chunks.
4. **Guardrails:** Verify grounding; enforce citation requirement.
5. **Citation assembly:** Map chunk_ids back to `chunk_map.json` for speaker/timestamp/snippet.

### chunk_map.json (stored in S3 derived)
```json
{
  "chunk-001": {
    "meeting_id": "uuid",
    "timestamp_start": "00:05:30",
    "timestamp_end": "00:06:15",
    "speaker": "Alice",
    "snippet": "We need to finalize the budget...",
    "raw_s3_uri": "s3://bucket/raw/..."
  }
}
```

All answers MUST include citations referencing this map.

---

## 11. Guardrails

1. **Input safety:** Reject jailbreak attempts, prompt injection, toxic queries.
2. **Transcript-as-data:** Ignore instructions embedded inside transcripts; treat transcript content strictly as data.
3. **Grounding verification:** LLM output is verified against retrieved chunks.
4. **Insufficient evidence:** If evidence is lacking, respond exactly:
   > "I don't have enough information to answer that from my knowledge base."
5. **Citation requirement:** Answers without supporting citations are rejected.

---

## 12. Evaluation & Monitoring

### Framework
RAGAS with metrics: faithfulness, answer relevancy, context precision.

### Data Sources
- Small curated test query set, AND/OR
- Last N user queries (configurable via `eval_last_n`).

### Storage
Evaluation results stored in S3 derived prefix (`s3://{bucket}/derived/evaluations/`).

### UI
"Evaluation" tab in Streamlit showing:
- Metric trends over time (line charts).
- Per-query score breakdown (table).
- Last evaluation timestamp and aggregate scores.

---

## 13. Configuration

### pydantic-settings (extends v1)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `environment` | str | `dev` | `dev` / `stage` / `prod` (required) |
| `aws_region` | str | `eu-west-2` | AWS region |
| `s3_raw_bucket` | str | — | Bucket for raw transcripts |
| `s3_raw_prefix` | str | `raw/` | Prefix within raw bucket |
| `s3_derived_bucket` | str | — | Bucket for derived artifacts |
| `s3_derived_prefix` | str | `derived/` | Prefix within derived bucket |
| `dynamodb_table_name` | str | `MeetingsMetadata` | DynamoDB table |
| `s3_vectors_index_name` | str | — | S3 Vectors index name |
| `llm_provider` | str | `bedrock` | `bedrock` / `openai` |
| `embed_provider` | str | `bedrock` | `bedrock` / `openai` |
| `bedrock_region` | str | `eu-west-2` | Bedrock region |
| `bedrock_llm_model_id` | str | — | Bedrock LLM model ID |
| `bedrock_embed_model_id` | str | — | Bedrock embedding model ID |
| `openai_api_key` | str | — | OpenAI API key (optional) |
| `openai_secret_name` | str | — | AWS Secrets Manager name |
| `enable_eval` | bool | `false` | Enable RAGAS evaluation |
| `eval_last_n` | int | `10` | Number of recent queries to evaluate |
| `eval_s3_prefix` | str | `derived/evaluations/` | S3 prefix for eval results |
| `ecs_cluster_name` | str | — | ECS cluster for RunTask |
| `ecs_worker_task_def` | str | — | Worker task definition family |
| `ecs_worker_subnets` | str | — | Comma-separated subnet IDs |
| `ecs_worker_security_group` | str | — | Worker security group ID |

No hardcoded resource names, ARNs, or regions anywhere in code.

---

## 14. Project Structure (Post-Migration)

```
meeting_intelligence_system/
├── domain/                        # NEW — pure models, no AWS
│   ├── __init__.py
│   └── models.py
├── ports/                         # NEW — Protocol interfaces
│   ├── __init__.py
│   ├── vector_store.py            #   VectorStorePort
│   ├── metadata_store.py          #   MetadataStorePort
│   ├── artifact_store.py          #   ArtifactStorePort
│   └── llm_provider.py            #   LLMProviderPort
├── adapters/                      # NEW — AWS implementations
│   ├── __init__.py
│   ├── s3_artifact_store.py       #   S3ArtifactStoreAdapter
│   ├── dynamo_metadata_store.py   #   DynamoMetadataStoreAdapter
│   └── s3vectors_vector_store.py  #   S3VectorsVectorStoreAdapter
├── services/                      # NEW — business orchestration
│   ├── __init__.py
│   ├── ingestion_service.py       #   IngestionService
│   └── query_service.py           #   QueryService
├── orchestration/                 # NEW — LangGraph workflows
│   ├── __init__.py
│   └── workflows.py
├── worker/                        # NEW — ECS RunTask entrypoint
│   ├── __init__.py
│   ├── entrypoint.py
│   └── Dockerfile
├── api_service/                   # REFACTORED
│   ├── Dockerfile
│   └── src/main.py
├── ui_service/                    # REFACTORED
│   ├── Dockerfile
│   └── src/app.py
├── core_intelligence/             # SLIMMED (reused parts only)
│   ├── __init__.py
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── guardrails.py          # KEPT + enhanced
│   │   └── evaluation.py          # REFACTORED (S3 storage)
│   ├── parser/
│   │   ├── __init__.py
│   │   └── cleaner.py             # KEPT (TranscriptParser)
│   ├── providers/                 # KEPT entirely
│   │   ├── __init__.py
│   │   ├── factory.py
│   │   ├── bedrock_embedding.py
│   │   ├── bedrock_llm.py
│   │   ├── openai_embedding.py
│   │   └── openai_llm.py
│   └── schemas/
│       ├── __init__.py
│       └── models.py              # EXTENDED
├── shared_utils/                  # EXTENDED
│   ├── __init__.py
│   ├── config_loader.py           # EXTENDED
│   ├── constants.py               # EXTENDED
│   ├── di_container.py            # REFACTORED
│   ├── error_handler.py           # EXTENDED
│   ├── logging_utils.py           # KEPT
│   └── validation.py              # KEPT
├── meet_intelli_system_iac/       # REWORKED
│   ├── provider.tf
│   ├── variables.tf
│   ├── network.tf                 # Private subnets + VPC endpoints
│   ├── ecs.tf                     # Worker task def + private networking
│   ├── ecr.tf                     # + worker repo
│   ├── iam.tf                     # + DynamoDB, RunTask, Logs perms
│   ├── s3.tf
│   ├── dynamodb.tf                # NEW
│   ├── application.tf
│   ├── outputs.tf
│   ├── terraform_backend.tf
│   ├── terraform.tfvars
│   └── github_oidc.tf
├── tests/
│   ├── conftest.py
│   ├── domain/
│   │   └── test_models.py
│   ├── adapters/
│   │   └── test_adapters.py
│   ├── services/
│   │   ├── test_ingestion_service.py
│   │   └── test_query_service.py
│   ├── core_intelligence/
│   │   └── engine/
│   │       └── test_guardrails.py
│   ├── api_service/
│   │   └── test_endpoints.py
│   └── shared_utils/
│       ├── test_config_loader.py
│       └── test_validation.py
├── .github/
│   ├── copilot-instructions.md
│   └── workflows/
│       └── ci_cd_pipeline.yml
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── ReadmeV2.md
└── README.md
```

---

## 15. Migration Slices

### Slice 1 — Foundation: Domain, Ports, Config, Adapters

**Goal:** Clean architecture skeleton. System compiles. No runtime behaviour change.

| Action | Files |
|--------|-------|
| Create | `domain/__init__.py`, `domain/models.py` |
| Create | `ports/__init__.py`, `ports/vector_store.py`, `ports/metadata_store.py`, `ports/artifact_store.py`, `ports/llm_provider.py` |
| Create | `adapters/__init__.py`, `adapters/s3_artifact_store.py`, `adapters/dynamo_metadata_store.py`, `adapters/s3vectors_vector_store.py` |
| Modify | `shared_utils/config_loader.py` — add v2 settings with backward-compatible defaults |
| Modify | `shared_utils/constants.py` — add new log scopes, error codes |
| Modify | `shared_utils/error_handler.py` — add `IngestionError` |
| Delete | `shared_utils/logging_config.py` (deprecated) |
| Modify | `pyproject.toml` — add `langgraph`, pin versions |
| Create | `tests/domain/test_models.py`, `tests/adapters/test_adapters.py` |

### Slice 2 — Ingestion Pipeline: IngestionService + Worker

**Goal:** Upload → S3 raw → DynamoDB PENDING → worker → derived artifacts → DynamoDB READY/FAILED.

| Action | Files |
|--------|-------|
| Create | `services/__init__.py`, `services/ingestion_service.py` |
| Create | `worker/__init__.py`, `worker/entrypoint.py`, `worker/Dockerfile` |
| Modify | `api_service/src/main.py` — add `POST /upload`, `GET /status/{meeting_id}` |
| Modify | `shared_utils/di_container.py` — register adapters |
| Modify | `core_intelligence/schemas/models.py` — add new models |
| Modify | `docker-compose.yml` — add worker service |
| Modify | `.env.example` — add new vars |
| Create | `tests/services/test_ingestion_service.py` |

### Slice 3 — Query Path: QueryService + Citations

**Goal:** POST /query → DynamoDB → S3 Vectors → LLM → citations. GET /meetings.

| Action | Files |
|--------|-------|
| Create | `services/query_service.py` |
| Modify | `api_service/src/main.py` — add `POST /query` (v2), `GET /meetings` |
| Modify | `core_intelligence/engine/guardrails.py` — add citation gate |
| Create | `orchestration/__init__.py`, `orchestration/workflows.py` |
| Create | `tests/services/test_query_service.py` |
| Delete | `core_intelligence/engine/rag.py` |
| Delete | `core_intelligence/engine/strategies/` (all files) |
| Delete | `core_intelligence/database/manager.py` |
| Delete | `scripts/resync_db.py` |

### Slice 4 — Guardrails + Grounding Gate

**Goal:** Transcript-as-data defence. Exact insufficient-info response. Citation validation.

| Action | Files |
|--------|-------|
| Modify | `core_intelligence/engine/guardrails.py` — prompt injection defence, exact insufficient-info text |
| Modify | `services/query_service.py` — integrate grounding gate |
| Create | `tests/core_intelligence/engine/test_guardrails.py` |
| Update | API tests for grounding validation |

### Slice 5 — Evaluation, IaC, CI/CD, Tests, README

**Goal:** RAGAS evaluation tab, full IaC rework, CI green, comprehensive tests.

| Action | Files |
|--------|-------|
| Modify | `core_intelligence/engine/evaluation.py` — S3 storage |
| Modify | `ui_service/src/app.py` — full v2 UI with evaluation tab |
| Modify | `api_service/src/main.py` — `POST /evaluate`, `GET /metrics` |
| Rework | All `meet_intelli_system_iac/` files (see IaC summary below) |
| Modify | `.github/workflows/ci_cd_pipeline.yml` — worker image, env vars |
| Update | All test files |
| Update | `README.md` |
| Delete | `data/lancedb/`, `data/metrics/` (v1 artifacts) |

---

## 16. IaC Summary

### New/Changed Terraform Resources

| Resource | File | Details |
|----------|------|---------|
| Private subnets (×2) | `network.tf` | `10.0.3.0/24`, `10.0.4.0/24`, no public IPs |
| Private route table | `network.tf` | No internet route; gateway endpoints attached |
| VPC Endpoint SG | `network.tf` | Allow 443 inbound from ECS SG |
| S3 Gateway | `network.tf` | `route_table_ids = [public, private]` |
| DynamoDB Gateway | `network.tf` | `route_table_ids = [private]` |
| ECR API Interface | `network.tf` | Private subnet AZ-a, `private_dns_enabled = true` |
| ECR DKR Interface | `network.tf` | Same |
| CloudWatch Logs Interface | `network.tf` | Same |
| Bedrock Runtime Interface | `network.tf` | Same |
| Secrets Manager Interface | `network.tf` | Same |
| ECS Interface | `network.tf` | Same |
| ECS tasks → private subnets | `ecs.tf` | `assign_public_ip = false` |
| Worker task definition | `ecs.tf` | New Fargate task for ingestion |
| Worker ECR repo | `ecr.tf` | `meeting-intel-worker` |
| DynamoDB table | `dynamodb.tf` | `MeetingsMetadata`, `meeting_id` PK |
| IAM task role | `iam.tf` | Add DynamoDB, RunTask, Logs permissions |
| Worker CI job | `ci_cd_pipeline.yml` | Build + push worker image |

### IaC Requirements
- Terraform must be idempotent: `apply` and `destroy` fully create/tear down the stack cleanly.
- No unnecessary services. Prefer modules and clear variables.
- `deploy_app` toggle preserved for foundation-only deploys.

---

## 17. CI/CD Changes

| Change | Details |
|--------|---------|
| New env vars | `S3_RAW_BUCKET`, `S3_DERIVED_BUCKET`, `DYNAMODB_TABLE_NAME`, `S3_VECTORS_INDEX_NAME` (test stubs) |
| Worker image | Add build + push step for `worker/Dockerfile` |
| Worker deploy | Add RunTask integration (optional; worker is triggered by API) |
| Test step | Update pytest markers; ensure new tests run |
| Lint/format | `ruff`, `black`, `mypy` targets include new directories |

---

## 18. Quality Gates

- [ ] No duplicated code across modules
- [ ] All tests pass: parser, chunking, metadata extraction, grounding validation
- [ ] CI green: `ruff` + `black` + `mypy` + `pytest`
- [ ] Chunking preserves speaker turns and timestamp ranges
- [ ] Grounding test: answer without supporting citations → FAIL
- [ ] Insufficient evidence test: returns exact text
- [ ] Transcript-as-data: instructions inside transcript are ignored
- [ ] IaC: `terraform plan` clean; `terraform destroy` clean
- [ ] No hardcoded ARNs, regions, or resource names
- [ ] structlog JSON logs include: `request_id`, `meeting_id`, `workflow_name`, `ingestion_status`, `chunk_ids`, `latency_ms`, `aws_region`
