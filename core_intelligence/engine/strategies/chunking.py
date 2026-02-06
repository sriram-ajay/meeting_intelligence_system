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
                "chunk_type": "header"
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
                "chunk_type": "analytics"
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
                "chunk_type": "recursive"
            }
        )
        return self.splitter.get_nodes_from_documents([doc])

class SemanticChunker(ChunkingStrategy):
    """
    State-of-the-art: Semantic Double-Pass Chunking.
    Combines hierarchical structure with semantic breakpoint detection to ensure
    that chunks are both contextually rich and semantically coherent.
    """
    
    def __init__(self, embed_model: Any):
        # Uses LlamaIndex's SemanticSplitter which detects topic shifts
        # using embedding similarity between sentences.
        from llama_index.core.node_parser import SemanticSplitterNodeParser
        self.splitter = SemanticSplitterNodeParser(
            buffer_size=1, 
            breakpoint_percentile_threshold=95, 
            embed_model=embed_model
        )
    
    def chunk(self, transcript: MeetingTranscript) -> List[Document]:
        # DOUBLE-PASS STRATEGY:
        # Pass 1: Build a rich global context header for metadata retrieval
        header_text = (
            f"MEETING SUMMARY CONTEXT\n"
            f"Title: {transcript.metadata.title}\n"
            f"Participants: {', '.join(transcript.metadata.participants)}\n"
            f"Date: {transcript.metadata.date.isoformat()}\n"
        )
        
        # Pass 2: Semantic splitting of the main content
        full_text = "\n".join([
            f"[{s.timestamp}] {s.speaker}: {s.content}" 
            for s in transcript.segments
        ])
        
        base_doc = Document(
            text=full_text,
            metadata={
                "meeting_id": transcript.metadata.meeting_id,
                "title": transcript.metadata.title,
                "date": transcript.metadata.date.isoformat(),
                "chunk_type": "semantic_core"
            }
        )
        
        # Parse into semantic nodes
        nodes = self.splitter.get_nodes_from_documents([base_doc])
        
        # Post-process nodes to inject the header context into EVERY chunk
        # This is a SOTA technique called "Context Injection"
        final_documents = []

        # 1. Add Analytics Chunk (SOTA recall enhancement)
        speaker_counts = {}
        for s in transcript.segments:
            speaker_counts[s.speaker] = speaker_counts.get(s.speaker, 0) + 1
        
        sorted_speakers = sorted(speaker_counts.items(), key=lambda x: x[1], reverse=True)
        stats_text = f"{header_text}\nMeeting Participation Stats:\n" + "\n".join([f"- {s}: {c} segments" for s, c in sorted_speakers])
        stats_text += f"\nTotal segments: {len(transcript.segments)}"
        
        stats_doc = Document(
            text=stats_text,
            metadata={
                **base_doc.metadata,
                "chunk_type": "analytics"
            }
        )
        final_documents.append(stats_doc)

        # 2. Add Semantic Chunks
        for node in nodes:
            # Inject context but wrap back as a Document to avoid LlamaIndex type issues
            doc = Document(
                text=f"{header_text}\n--- Segment Discussion ---\n{node.get_content()}",
                metadata={
                    **node.metadata,
                    "chunk_type": "semantic"
                }
            )
            final_documents.append(doc)
            
        return final_documents
