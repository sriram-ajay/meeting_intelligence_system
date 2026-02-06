from abc import ABC, abstractmethod
from typing import List, Any
from llama_index.core import Document
from llama_index.core.node_parser import (
    SentenceSplitter, 
    SemanticSplitterNodeParser,
    TokenTextSplitter
)
from core_intelligence.schemas.models import MeetingTranscript

class ChunkingStrategy(ABC):
    """Abstract base class for chunking strategies."""
    
    @abstractmethod
    def chunk(self, transcript: MeetingTranscript) -> List[Document]:
        """Convert transcript into a list of chunked documents."""
        pass

class SegmentChunker(ChunkingStrategy):
    """Keep transcript segments as individual chunks (Natural speaker boundaries)."""
    
    def chunk(self, transcript: MeetingTranscript) -> List[Document]:
        documents = []
        
        # 1. Add a "Context Header" document for the entire meeting
        participants_list = ", ".join(transcript.metadata.participants)
        header_text = (
            f"Meeting Overview\n"
            f"Title: {transcript.metadata.title}\n"
            f"Date: {transcript.metadata.date.isoformat()}\n"
            f"Who attended: {participants_list}\n"
            f"This document provides the high-level metadata for the meeting."
        )
        header_doc = Document(
            text=header_text,
            metadata={
                "meeting_id": transcript.metadata.meeting_id,
                "title": transcript.metadata.title,
                "date": transcript.metadata.date.isoformat(),
                "chunk_type": "header",
                "speaker": "System",
                "timestamp": "00:00"
            }
        )
        documents.append(header_doc)

        # 2. Add an "Analytics" chunk for aggregate queries like "who spoke most"
        speaker_counts = {}
        for s in transcript.segments:
            speaker_counts[s.speaker] = speaker_counts.get(s.speaker, 0) + 1
        
        sorted_speakers = sorted(speaker_counts.items(), key=lambda x: x[1], reverse=True)
        stats_text = "Meeting Participation Stats:\n" + "\n".join([f"- {s}: {c} segments" for s, c in sorted_speakers])
        stats_text += f"\nTotal segments: {len(transcript.segments)}"
        
        stats_doc = Document(
            text=stats_text,
            metadata={
                "meeting_id": transcript.metadata.meeting_id,
                "title": transcript.metadata.title,
                "date": transcript.metadata.date.isoformat(),
                "chunk_type": "analytics",
                "speaker": "System",
                "timestamp": "00:00"
            }
        )
        documents.append(stats_doc)

        # 3. Individual segments
        for segment in transcript.segments:
            # Prepend speaker for better retrieval context
            text = f"[{segment.timestamp}] {segment.speaker}: {segment.content}"
            doc = Document(
                text=text,
                metadata={
                    "meeting_id": transcript.metadata.meeting_id,
                    "title": transcript.metadata.title,
                    "speaker": segment.speaker,
                    "timestamp": segment.timestamp,
                    "date": transcript.metadata.date.isoformat(),
                    "chunk_type": "segment"
                }
            )
            documents.append(doc)
        return documents

class recursiveCharacterChunker(ChunkingStrategy):
    """Standard recursive character splitting for longer contexts."""
    
    def __init__(self, chunk_size: int = 1024, chunk_overlap: int = 128):
        self.splitter = SentenceSplitter(
            chunk_size=chunk_size, 
            chunk_overlap=chunk_overlap
        )
    
    def chunk(self, transcript: MeetingTranscript) -> List[Document]:
        # Merge all segments into one text block but keep metadata
        full_text = "\n".join([
            f"[{s.timestamp}] {s.speaker}: {s.content}" 
            for s in transcript.segments
        ])
        
        doc = Document(
            text=full_text,
            metadata={
                "meeting_id": transcript.metadata.meeting_id,
                "title": transcript.metadata.title,
                "date": transcript.metadata.date.isoformat(),
                "chunk_type": "recursive",
                "speaker": "Multiple",
                "timestamp": "Mixed"
            }
        )
        return self.splitter.get_nodes_from_documents([doc])

class SemanticChunker(ChunkingStrategy):
    """
    Advanced: Semantic Hybrid Chunking with intelligent context inclusion.
    Uses semantic breakpoints to find natural topic shifts, while preserving 
    speaker attribution and metadata without polluting the vector space.
    """
    
    def __init__(self, embed_model: Any, breakpoint_percentile: int = 85):
        # uses a more balanced percentile (85 instead of 95) for better granularity
        from llama_index.core.node_parser import SemanticSplitterNodeParser
        self.splitter = SemanticSplitterNodeParser(
            buffer_size=1, 
            breakpoint_percentile_threshold=breakpoint_percentile, 
            embed_model=embed_model
        )
    
    def chunk(self, transcript: MeetingTranscript) -> List[Document]:
        # 1. Summary Context: Optimized for retrieval without keyword pollution
        # We strip file extensions from title if present
        clean_title = transcript.metadata.title.split('.')[0].replace('_', ' ').title()
        participants_summary = f"Participants: {', '.join(transcript.metadata.participants)}"
        header_brief = (
            f"Context: {clean_title} ({transcript.metadata.date.date()})\n"
            f"{participants_summary}\n"
        )
        
        # 2. Build segments
        full_text = "\n".join([
            f"{s.speaker}: {s.content}" 
            for s in transcript.segments
        ])
        
        base_doc = Document(
            text=full_text,
            metadata={
                "meeting_id": transcript.metadata.meeting_id,
                "title": transcript.metadata.title,
                "date": transcript.metadata.date.isoformat(),
                "chunk_type": "semantic_core",
                "speaker": "Multiple",
                "timestamp": "System"
            }
        )
        
        # Parse into semantic nodes
        nodes = self.splitter.get_nodes_from_documents([base_doc])
        
        final_documents = []

        # Add Analytics Chunk (Specialized for metadata queries)
        # Keeping it separate avoids polluting regular chunks
        speaker_stats = {}
        for s in transcript.segments:
            speaker_stats[s.speaker] = speaker_stats.get(s.speaker, 0) + 1
        
        stats_text = (
            f"ANALYTICS: {transcript.metadata.title}\n"
            f"Summary: {transcript.metadata.summary or 'No summary'}\n"
            f"Participation: " + ", ".join([f"{s} ({c})" for s, c in speaker_stats.items()])
        )
        
        stats_doc = Document(
            text=stats_text,
            metadata={**base_doc.metadata, "chunk_type": "analytics"}
        )
        final_documents.append(stats_doc)

        # Add Semantic Chunks with "Local Context"
        for node in nodes:
            # We only inject the brief header to reduce vector noise
            # while keeping the chunk semantically grounded.
            doc = Document(
                text=f"{header_brief}\nContent:\n{node.get_content()}",
                metadata={
                    **node.metadata,
                    "chunk_type": "semantic"
                }
            )
            final_documents.append(doc)
            
        return final_documents
