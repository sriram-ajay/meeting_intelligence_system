"""
Ingestion service — orchestrates the full ingest pipeline.

Flow:  raw bytes → parse → normalise → chunk → embed → store vectors + metadata.

Depends only on ports (protocol interfaces) — never on concrete adapters.
Reuses the existing TranscriptParser from core_intelligence.parser.cleaner.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Dict, List, Optional

from core_intelligence.parser.cleaner import TranscriptParser
from domain.models import (
    MeetingTranscript,
    TranscriptSegment,
    ChunkMapEntry,
    IngestionReport,
    IngestionStatus,
    MeetingRecord,
    NormalizedSegment,
    NormalizedTranscript,
    VectorRecord,
)
from ports.artifact_store import ArtifactStorePort
from ports.llm_provider import EmbeddingProviderPort
from ports.metadata_store import MetadataStorePort
from ports.vector_store import VectorStorePort
from shared_utils.constants import LogScope
from shared_utils.error_handler import IngestionError
from shared_utils.logging_utils import get_scoped_logger

logger = get_scoped_logger(LogScope.INGESTION)


# ---------------------------------------------------------------------------
# Chunking helpers (pure functions — no external deps)
# ---------------------------------------------------------------------------

def _compute_hash(content: bytes) -> str:
    """SHA-256 hex digest of raw content."""
    return hashlib.sha256(content).hexdigest()


def _chunk_segments(
    segments: List[NormalizedSegment],
    max_tokens: int = 512,
    overlap: int = 1,
) -> List[Dict]:
    """Sliding-window chunking over normalised segments.

    Each chunk collects consecutive segments up to *max_tokens*
    (estimated as ``len(text.split())``).  Adjacent chunks share
    *overlap* trailing segments for context continuity.

    Returns a list of dicts with keys:
        chunk_id, text, timestamp_start, timestamp_end, speaker, speakers.
    """
    if not segments:
        return []

    chunks: List[Dict] = []
    i = 0

    while i < len(segments):
        token_count = 0
        batch: List[NormalizedSegment] = []

        j = i
        while j < len(segments):
            seg_tokens = len(segments[j].text.split())
            if token_count + seg_tokens > max_tokens and batch:
                break
            batch.append(segments[j])
            token_count += seg_tokens
            j += 1

        if not batch:
            break

        text = "\n".join(
            f"[{s.timestamp}] {s.speaker}: {s.text}" for s in batch
        )
        speakers = sorted({s.speaker for s in batch})
        chunks.append(
            {
                "chunk_id": str(uuid.uuid4()),
                "text": text,
                "timestamp_start": batch[0].timestamp,
                "timestamp_end": batch[-1].timestamp,
                "speaker": speakers[0] if len(speakers) == 1 else ", ".join(speakers),
                "speakers": speakers,
            }
        )
        # Advance by (batch size - overlap), but always at least 1
        advance = max(len(batch) - overlap, 1)
        i += advance

    return chunks


# ---------------------------------------------------------------------------
# IngestionService
# ---------------------------------------------------------------------------

class IngestionService:
    """Orchestrates the full meeting ingestion pipeline.

    All storage interactions go through port interfaces — no direct boto3.
    """

    def __init__(
        self,
        artifact_store: ArtifactStorePort,
        metadata_store: MetadataStorePort,
        vector_store: VectorStorePort,
        embedding_provider: EmbeddingProviderPort,
        max_chunk_tokens: int = 512,
        chunk_overlap: int = 1,
    ) -> None:
        self._artifacts = artifact_store
        self._metadata = metadata_store
        self._vectors = vector_store
        self._embedder = embedding_provider
        self._max_chunk_tokens = max_chunk_tokens
        self._chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(
        self,
        meeting_id: str,
        filename: str,
        raw_content: bytes,
    ) -> IngestionReport:
        """Run the complete ingestion pipeline for a single meeting.

        Steps:
            1. Upload raw file to artifact store.
            2. Create PENDING metadata record.
            3. Parse transcript (reuses v1 TranscriptParser).
            4. Normalise into domain models.
            5. Chunk segments with sliding window.
            6. Embed chunks via embedding provider.
            7. Store vectors in vector store.
            8. Store chunk_map.json in derived artifacts.
            9. Update metadata to READY.
           10. Return IngestionReport.

        On failure at any step the metadata is set to FAILED.
        """
        started = time.time()
        logger.info(
            "ingestion_started",
            meeting_id=meeting_id,
            filename=filename,
            size_bytes=len(raw_content),
        )

        try:
            # 1. Store raw artifact
            raw_uri = self._artifacts.upload_raw(meeting_id, filename, raw_content)
            derived_prefix = self._artifacts.get_derived_prefix(meeting_id)

            # 2. Metadata — PENDING
            doc_hash = _compute_hash(raw_content)
            record = MeetingRecord(
                meeting_id=meeting_id,
                title_normalized=filename.rsplit(".", 1)[0].lower().replace("_", " "),
                meeting_date="",  # enriched below after parse
                s3_uri_raw=raw_uri,
                s3_uri_derived_prefix=derived_prefix,
                doc_hash=doc_hash,
                ingestion_status=IngestionStatus.PENDING,
            )
            self._metadata.put_meeting(record)

            # 3. Parse (reuse v1 parser)
            text = raw_content.decode("utf-8")
            transcript: MeetingTranscript = TranscriptParser.parse_text(
                text, title=filename
            )

            # 4. Normalise
            normalised = self._normalise(transcript, meeting_id)

            # Update metadata with parsed participants / date
            record.participants = normalised.participants
            record.meeting_date = normalised.date
            self._metadata.put_meeting(record)

            # 5. Chunk
            chunks = _chunk_segments(
                normalised.segments,
                max_tokens=self._max_chunk_tokens,
                overlap=self._chunk_overlap,
            )
            logger.info(
                "chunking_complete",
                meeting_id=meeting_id,
                chunk_count=len(chunks),
            )

            # 6. Embed
            texts = [c["text"] for c in chunks]
            embeddings = self._embedder.embed_texts(texts)

            # 7. Store vectors
            vectors = [
                VectorRecord(
                    chunk_id=c["chunk_id"],
                    meeting_id=meeting_id,
                    embedding=emb,
                    text=c["text"],
                    metadata={"speaker": c["speaker"]},
                )
                for c, emb in zip(chunks, embeddings)
            ]
            self._vectors.store_vectors(vectors)

            # 8. Chunk map (citation lookup artifact)
            chunk_map = [
                ChunkMapEntry(
                    chunk_id=c["chunk_id"],
                    meeting_id=meeting_id,
                    timestamp_start=c["timestamp_start"],
                    timestamp_end=c["timestamp_end"],
                    speaker=c["speaker"],
                    snippet=c["text"][:200],
                    raw_s3_uri=raw_uri,
                ).model_dump()
                for c in chunks
            ]
            chunk_map_bytes = json.dumps(chunk_map, default=str).encode()
            chunk_map_uri = self._artifacts.upload_derived(
                meeting_id, "chunk_map.json", chunk_map_bytes
            )

            # 9. Mark READY
            self._metadata.update_status(meeting_id, IngestionStatus.READY)

            duration_ms = (time.time() - started) * 1000
            report = IngestionReport(
                meeting_id=meeting_id,
                status=IngestionStatus.READY,
                chunks_created=len(chunks),
                embeddings_stored=len(vectors),
                derived_artifacts=[chunk_map_uri],
                duration_ms=duration_ms,
            )
            logger.info(
                "ingestion_completed",
                meeting_id=meeting_id,
                chunks=len(chunks),
                embeddings=len(vectors),
                duration_ms=round(duration_ms, 1),
            )
            return report

        except Exception as exc:
            duration_ms = (time.time() - started) * 1000
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "ingestion_failed",
                meeting_id=meeting_id,
                error=error_msg,
            )
            # Best-effort status update
            try:
                self._metadata.update_status(
                    meeting_id,
                    IngestionStatus.FAILED,
                    error_message=error_msg,
                )
            except Exception:
                logger.error("failed_to_update_status_after_error", meeting_id=meeting_id)

            raise IngestionError(
                message=f"Ingestion failed for {meeting_id}: {error_msg}",
                meeting_id=meeting_id,
            ) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(
        transcript: MeetingTranscript, meeting_id: str
    ) -> NormalizedTranscript:
        """Convert v1 MeetingTranscript to v2 NormalizedTranscript."""
        segments = [
            NormalizedSegment(
                timestamp=seg.timestamp,
                speaker=seg.speaker,
                text=seg.content,
            )
            for seg in transcript.segments
        ]
        return NormalizedTranscript(
            meeting_id=meeting_id,
            title=transcript.metadata.title,
            date=transcript.metadata.date.isoformat()[:10],
            participants=transcript.metadata.participants,
            segments=segments,
            raw_text_hash="",  # filled in caller
        )
