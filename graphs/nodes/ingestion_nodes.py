"""
Ingestion graph node functions.

Each function takes the full IngestionState, performs one pipeline step
by delegating to existing services / adapters, and returns a partial
state dict with the new keys.  LangGraph merges the returned keys into
the running state automatically.

All heavy lifting stays in IngestionService / adapters — these nodes
are thin orchestration wrappers.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict

from core_intelligence.parser.cleaner import TranscriptParser
from domain.models import (
    ChunkMapEntry,
    IngestionReport,
    IngestionStatus,
    MeetingRecord,
    NormalizedSegment,
    NormalizedTranscript,
    VectorRecord,
)
from graphs.state import IngestionState
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope

logger = get_scoped_logger(LogScope.INGESTION)


# ---------------------------------------------------------------------------
# Helper (reused from ingestion_service — pure function)
# ---------------------------------------------------------------------------

def _compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def store_raw_artifact(state: IngestionState, *, artifact_store) -> Dict[str, Any]:
    """Upload raw transcript to artifact store."""
    raw_uri = artifact_store.upload_raw(
        state["meeting_id"], state["filename"], state["raw_content"]
    )
    derived_prefix = artifact_store.get_derived_prefix(state["meeting_id"])
    logger.info("raw_artifact_stored", meeting_id=state["meeting_id"])
    return {"raw_uri": raw_uri, "derived_prefix": derived_prefix}


def create_pending_record(state: IngestionState, *, metadata_store) -> Dict[str, Any]:
    """Create PENDING metadata record."""
    doc_hash = _compute_hash(state["raw_content"])
    record = MeetingRecord(
        meeting_id=state["meeting_id"],
        title_normalized=state["filename"].rsplit(".", 1)[0].lower().replace("_", " "),
        meeting_date="",
        s3_uri_raw=state["raw_uri"],
        s3_uri_derived_prefix=state["derived_prefix"],
        doc_hash=doc_hash,
        ingestion_status=IngestionStatus.PENDING,
    )
    metadata_store.put_meeting(record)
    logger.info("pending_record_created", meeting_id=state["meeting_id"])
    return {"doc_hash": doc_hash, "record": record}


def parse_transcript(state: IngestionState) -> Dict[str, Any]:
    """Parse raw bytes into MeetingTranscript using existing parser."""
    text = state["raw_content"].decode("utf-8")
    transcript = TranscriptParser.parse_text(text, title=state["filename"])
    logger.info(
        "transcript_parsed",
        meeting_id=state["meeting_id"],
        segments=len(transcript.segments),
    )
    return {"transcript": transcript}


def normalize_transcript(state: IngestionState, *, metadata_store) -> Dict[str, Any]:
    """Convert MeetingTranscript → NormalizedTranscript."""
    transcript = state["transcript"]
    segments = [
        NormalizedSegment(
            timestamp=seg.timestamp,
            speaker=seg.speaker,
            text=seg.content,
        )
        for seg in transcript.segments
    ]
    normalized = NormalizedTranscript(
        meeting_id=state["meeting_id"],
        title=transcript.metadata.title,
        date=transcript.metadata.date.isoformat()[:10],
        participants=transcript.metadata.participants,
        segments=segments,
        raw_text_hash=state.get("doc_hash", ""),
    )

    # Update metadata with parsed participants / date
    record = state["record"]
    record.participants = normalized.participants
    record.meeting_date = normalized.date
    metadata_store.put_meeting(record)

    logger.info("transcript_normalized", meeting_id=state["meeting_id"])
    return {"normalized": normalized, "record": record}


def chunk_segments(
    state: IngestionState,
    *,
    chunk_size: int = 512,
    chunk_overlap_tokens: int = 50,
) -> Dict[str, Any]:
    """Chunk normalised segments using LangChain's token-accurate splitter.

    Uses ``RecursiveCharacterTextSplitter.from_tiktoken_encoder()`` with
    cl100k_base encoding for precise token budgeting.  Splits prefer
    newline boundaries (= segment boundaries) so structured metadata
    (speaker, timestamp) is preserved per line.
    """
    import re
    import uuid

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    segments = state["normalized"].segments
    if not segments:
        return {"chunks": []}

    # Reconstruct full text with segment markers
    full_text = "\n".join(
        f"[{s.timestamp}] {s.speaker}: {s.text}" for s in segments
    )

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap_tokens,
        separators=["\n"],  # Prefer splitting on segment boundaries
    )

    split_texts = splitter.split_text(full_text)

    _LINE_RE = re.compile(r"\[([^\]]+)\]\s+([^:]+):")

    chunks = []
    for text in split_texts:
        lines = text.strip().split("\n")
        speakers: set[str] = set()
        timestamps: list[str] = []
        for line in lines:
            m = _LINE_RE.match(line)
            if m:
                timestamps.append(m.group(1))
                speakers.add(m.group(2).strip())

        sorted_speakers = sorted(speakers)
        chunks.append(
            {
                "chunk_id": str(uuid.uuid4()),
                "text": text,
                "timestamp_start": timestamps[0] if timestamps else "",
                "timestamp_end": timestamps[-1] if timestamps else "",
                "speaker": (
                    sorted_speakers[0]
                    if len(sorted_speakers) == 1
                    else ", ".join(sorted_speakers)
                ),
                "speakers": sorted_speakers,
            }
        )

    logger.info(
        "chunking_complete",
        meeting_id=state["meeting_id"],
        chunks=len(chunks),
    )
    return {"chunks": chunks}


def embed_chunks(state: IngestionState, *, embedding_provider) -> Dict[str, Any]:
    """Embed all chunk texts via EmbeddingProviderPort."""
    texts = [c["text"] for c in state["chunks"]]
    embeddings = embedding_provider.embed_texts(texts)
    logger.info("embeddings_generated", meeting_id=state["meeting_id"], count=len(embeddings))
    return {"embeddings": embeddings}


def store_vectors(state: IngestionState, *, vector_store) -> Dict[str, Any]:
    """Store embedding vectors in vector store."""
    vectors = [
        VectorRecord(
            chunk_id=c["chunk_id"],
            meeting_id=state["meeting_id"],
            embedding=emb,
            text=c["text"],
            metadata={"speaker": c["speaker"]},
        )
        for c, emb in zip(state["chunks"], state["embeddings"])
    ]
    vector_store.store_vectors(vectors)
    logger.info("vectors_stored", meeting_id=state["meeting_id"], count=len(vectors))
    return {"vectors": vectors}


def store_chunk_map(state: IngestionState, *, artifact_store) -> Dict[str, Any]:
    """Build and store chunk_map.json for citation lookup."""
    chunk_map = [
        ChunkMapEntry(
            chunk_id=c["chunk_id"],
            meeting_id=state["meeting_id"],
            timestamp_start=c["timestamp_start"],
            timestamp_end=c["timestamp_end"],
            speaker=c["speaker"],
            snippet=c["text"][:200],
            raw_s3_uri=state["raw_uri"],
        ).model_dump()
        for c in state["chunks"]
    ]
    chunk_map_bytes = json.dumps(chunk_map, default=str).encode()
    chunk_map_uri = artifact_store.upload_derived(
        state["meeting_id"], "chunk_map.json", chunk_map_bytes
    )
    logger.info("chunk_map_stored", meeting_id=state["meeting_id"])
    return {"chunk_map_uri": chunk_map_uri}


def mark_ready(state: IngestionState, *, metadata_store) -> Dict[str, Any]:
    """Update metadata status to READY and return IngestionReport."""
    metadata_store.update_status(state["meeting_id"], IngestionStatus.READY)
    report = IngestionReport(
        meeting_id=state["meeting_id"],
        status=IngestionStatus.READY,
        chunks_created=len(state["chunks"]),
        embeddings_stored=len(state["vectors"]),
        derived_artifacts=[state.get("chunk_map_uri", "")],
    )
    logger.info(
        "ingestion_completed",
        meeting_id=state["meeting_id"],
        chunks=report.chunks_created,
    )
    return {"report": report}


def handle_failure(state: IngestionState, *, metadata_store) -> Dict[str, Any]:
    """Mark meeting as FAILED and return error report."""
    error_msg = state.get("error", "Unknown error")
    try:
        metadata_store.update_status(
            state["meeting_id"],
            IngestionStatus.FAILED,
            error_message=error_msg,
        )
    except Exception:
        logger.error("failed_to_update_status_after_error", meeting_id=state["meeting_id"])

    report = IngestionReport(
        meeting_id=state["meeting_id"],
        status=IngestionStatus.FAILED,
        error_message=error_msg,
    )
    logger.error("ingestion_failed", meeting_id=state["meeting_id"], error=error_msg)
    return {"report": report}
