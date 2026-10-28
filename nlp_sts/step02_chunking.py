"""
NLP pipeline — Step 2: Chunking

Splits a document's text (from step01_text_extraction.py) into passages of
at most max_chunk_size characters, keeping structure intact:

1. sections first (numbered headings, ALL-CAPS headers, Markdown #, rules),
   each heading staying with the section it introduces;
2. paragraphs, with a sliding-window overlap between neighbouring passages;
3. sentences, as a last resort for one huge paragraph;
4. tiny fragments (a lone heading, one CSV row) merged into their neighbours.

Next step: step03_text_embeddings.py embeds each passage. The same passages
are later assembled into the LLM prompt by step10_context_building.py.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("veda.intelligence.chunk_builder")


# ── Data model ────────────────────────────────────────


@dataclass
class PreparedChunk:
    """A single chunk of text ready to be sent to an LLM.

    Contains the text content, its source metadata, relevance score,
    graph context, and a token estimate for context window management.
    """

    text: str
    source_type: str  # "vector", "graph", "text", "document"
    relevance_score: float
    document_id: str
    metadata: dict = field(default_factory=dict)
    token_estimate: int = 0
    entities_in_chunk: list[dict] = field(default_factory=list)
    graph_context: list[dict] = field(default_factory=list)


# ── Constants ─────────────────────────────────────────

# Approximate tokens per character (conservative estimate for English)
CHARS_PER_TOKEN = 4

# Section/paragraph splitting patterns for industrial documents
SECTION_BREAK_PATTERNS = [
    r"\n\s*\d+\.\s+",  # Numbered sections: "1. ", "2.1 "
    r"\n\s*[A-Z][A-Z\s]{3,}:",  # ALL CAPS HEADERS:
    r"\n\s*#{1,3}\s+",  # Markdown headers
    r"\n\s*\-{3,}",  # Horizontal rules
    r"\n\s*={3,}",  # Double horizontal rules
]


class TextChunker:
    """Structure-aware splitting of document text into passages."""

    def __init__(self, max_chunk_size: int = 1500, chunk_overlap: int = 200):
        """
        Args:
            max_chunk_size: Maximum characters per chunk
            chunk_overlap: Overlap between adjacent chunks (for continuity)
        """
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from character count (conservative)."""
        return max(1, len(text) // CHARS_PER_TOKEN)

    def split_into_chunks(
        self,
        text: str,
        document_id: str,
        metadata: dict | None = None,
    ) -> list[PreparedChunk]:
        """
        Split document text into semantic chunks.

        Strategy:
        1. First, try to split on section breaks (numbered sections, headers)
        2. If sections are too large, split on paragraph breaks
        3. If paragraphs are too large, split on sentence boundaries
        4. Add overlap between chunks for context continuity

        Returns a list of PreparedChunk objects.
        """
        if not text or not text.strip():
            return []

        metadata = metadata or {}
        chunks: list[PreparedChunk] = []

        # Step 1: Split into sections
        sections = self._split_into_sections(text)

        for section_idx, section in enumerate(sections):
            if not re.search(r"\w", section):
                continue

            # Step 2: If section is small enough, use as-is
            if len(section) <= self.max_chunk_size:
                chunks.append(
                    PreparedChunk(
                        text=section.strip(),
                        source_type="document",
                        relevance_score=0.0,  # Will be set by retrieval
                        document_id=document_id,
                        metadata={
                            **metadata,
                            "chunk_index": len(chunks),
                            "section_index": section_idx,
                        },
                        token_estimate=self.estimate_tokens(section),
                    )
                )
            else:
                # Step 3: Split large sections into paragraphs
                sub_chunks = self._split_large_section(section)
                for sub_chunk in sub_chunks:
                    chunks.append(
                        PreparedChunk(
                            text=sub_chunk.strip(),
                            source_type="document",
                            relevance_score=0.0,
                            document_id=document_id,
                            metadata={
                                **metadata,
                                "chunk_index": len(chunks),
                                "section_index": section_idx,
                            },
                            token_estimate=self.estimate_tokens(sub_chunk),
                        )
                    )

        logger.info(
            f"Split document {document_id} into {len(chunks)} chunks "
            f"({sum(c.token_estimate for c in chunks)} estimated tokens)"
        )
        return chunks

    def merge_small_chunks(self, chunks: list[PreparedChunk]) -> list[PreparedChunk]:
        """
        Join neighbouring chunks while the result stays within max_chunk_size.

        Section splitting cuts at every heading and every record, which leaves
        fragments like a lone "## Treatment" paragraph or one CSV row. Such
        fragments lose their context (the patient, the centre, the machine)
        and crowd out better passages at retrieval time.
        """
        merged: list[PreparedChunk] = []
        for chunk in chunks:
            last = merged[-1] if merged else None
            if last and len(last.text) + 2 + len(chunk.text) <= self.max_chunk_size:
                last.text = f"{last.text}\n\n{chunk.text}"
                last.token_estimate = self.estimate_tokens(last.text)
            else:
                merged.append(
                    PreparedChunk(
                        text=chunk.text,
                        source_type=chunk.source_type,
                        relevance_score=chunk.relevance_score,
                        document_id=chunk.document_id,
                        metadata={**chunk.metadata, "chunk_index": len(merged)},
                        token_estimate=chunk.token_estimate,
                    )
                )
        return merged

    def _split_into_sections(self, text: str) -> list[str]:
        """
        Split text into sections based on structural markers.

        Splits *before* each marker (zero-width lookahead), so a heading such
        as "## Eligibility" or "2. Scope" stays at the start of the section it
        introduces instead of becoming a separate, meaningless chunk.
        """
        combined_pattern = "|".join(f"(?:{p})" for p in SECTION_BREAK_PATTERNS)
        splits = re.split(f"(?={combined_pattern})", text)

        # Drop fragments with no real content (e.g. a bare "##" or "---")
        sections = [s for s in splits if re.search(r"\w", s)]

        # If no structural breaks found, split on double newlines (paragraphs)
        if len(sections) <= 1:
            sections = text.split("\n\n")

        return sections

    def _split_large_section(self, text: str) -> list[str]:
        """Split a large section into overlapping chunks."""
        chunks: list[str] = []
        paragraphs = text.split("\n\n")

        current_chunk = ""
        for para in paragraphs:
            # If adding this paragraph would exceed max size, finalize current chunk
            if current_chunk and len(current_chunk) + len(para) + 2 > self.max_chunk_size:
                chunks.append(current_chunk)
                # Start new chunk with overlap from end of previous
                overlap_text = current_chunk[-self.chunk_overlap :] if self.chunk_overlap else ""
                current_chunk = overlap_text + "\n\n" + para if overlap_text else para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk)

        # If still too large (single massive paragraph), force-split on sentences
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > self.max_chunk_size * 1.5:
                final_chunks.extend(self._split_on_sentences(chunk))
            else:
                final_chunks.append(chunk)

        return final_chunks

    def _split_on_sentences(self, text: str) -> list[str]:
        """Last resort: split on sentence boundaries."""
        # Split on sentence-ending punctuation followed by space
        sentences = re.split(r"(?<=[.!?])\s+", text)

        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 > self.max_chunk_size:
                if current:
                    chunks.append(current)
                current = sentence
            else:
                current = current + " " + sentence if current else sentence

        if current.strip():
            chunks.append(current)

        return chunks
