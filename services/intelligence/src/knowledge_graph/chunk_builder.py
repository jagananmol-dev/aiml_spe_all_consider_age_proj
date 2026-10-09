"""
VEDA AI — Chunk Builder

Prepares LLM-ready chunks from document text + extracted entities + graph context.
This is the critical bridge between the knowledge graph and any future paid LLM:

1. Splits document text into semantic chunks (paragraph/section-aware)
2. Enriches each chunk with its contained entities and their graph context
3. Estimates token counts for LLM context window management
4. Returns PreparedChunk objects ready to be sent to any LLM provider

The chunk format is provider-agnostic — works with OpenAI, Anthropic, Google, etc.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("veda.intelligence.chunk_builder")


# ── Data Models ───────────────────────────────────────


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


@dataclass
class PreparedContext:
    """Complete prepared context for an LLM query.

    This is the main output of the chunk preparation pipeline.
    Contains everything a paid LLM needs to generate an answer:
    - The original query
    - Ranked, deduplicated chunks with graph enrichment
    - The system prompt tuned for industrial domain
    - A pre-formatted prompt string ready for any LLM
    - Token budget information
    """

    query: str
    chunks: list[PreparedChunk]
    graph_context: list[dict]
    system_prompt: str
    formatted_prompt: str
    total_token_estimate: int
    entities_found: list[dict]
    retrieval_metadata: dict = field(default_factory=dict)


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

# Domain-neutral system prompt: every company (finance, healthcare, manufacturing…)
# gets an assistant grounded only in its own uploaded data.
SYSTEM_PROMPT = """You are the AI assistant for an organization on the VEDA platform. You answer questions using ONLY the context provided from that organization's own uploaded documents and data.

RULES:
1. Base every statement on the provided context and cite it with [Source N] notation
2. If the context doesn't contain the answer, say so clearly — never guess or invent facts
3. Keep the organization's terminology, units, names, and figures exactly as written
4. If sources conflict, point out the discrepancy and cite both
5. Be concise and well-structured; use lists or tables when they make the answer clearer
6. For medical, legal, financial, or safety-critical topics, add a short note that the answer is based on the organization's documents and should be verified by a qualified person"""


class ChunkBuilder:
    """
    Builds LLM-ready chunks from raw text, entities, and graph context.

    The key innovation is graph enrichment — each chunk is annotated with
    knowledge graph relationships, so the LLM has structural understanding
    (not just text similarity) of how entities connect.
    """

    def __init__(
        self,
        max_chunk_size: int = 1500,
        chunk_overlap: int = 200,
        max_total_tokens: int = 12000,
    ):
        """
        Args:
            max_chunk_size: Maximum characters per chunk
            chunk_overlap: Overlap between adjacent chunks (for continuity)
            max_total_tokens: Max total tokens across all chunks sent to LLM
        """
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_total_tokens = max_total_tokens

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

    def enrich_chunks_with_entities(
        self,
        chunks: list[PreparedChunk],
        entities: list[dict],
    ) -> list[PreparedChunk]:
        """
        Annotate each chunk with the entities it contains.

        Uses offset matching to determine which entities fall within
        each chunk's text span. This lets the LLM know what entities
        are relevant to each piece of context.
        """
        for chunk in chunks:
            chunk_lower = chunk.text.lower()
            matching_entities = []

            for entity in entities:
                # Check if entity value appears in this chunk
                entity_val = entity.get("normalized_value", entity.get("value", ""))
                if entity_val.lower() in chunk_lower:
                    matching_entities.append(
                        {
                            "type": entity["entity_type"],
                            "value": entity["value"],
                            "normalized_value": entity.get("normalized_value", entity["value"]),
                            "confidence": entity.get("confidence", 0.0),
                        }
                    )

            chunk.entities_in_chunk = matching_entities

        return chunks

    def enrich_chunks_with_graph(
        self,
        chunks: list[PreparedChunk],
        graph_context: list[dict],
    ) -> list[PreparedChunk]:
        """
        Attach relevant graph relationships to each chunk.

        For each chunk, finds graph relationships where either the source
        or target entity appears in the chunk text. This gives the LLM
        structural knowledge about entity connections.
        """
        for chunk in chunks:
            chunk_entity_values = {e["normalized_value"].lower() for e in chunk.entities_in_chunk}

            relevant_graph = []
            for rel in graph_context:
                source_val = rel.get("source_value", "").lower()
                target_val = rel.get("target_value", "").lower()

                if source_val in chunk_entity_values or target_val in chunk_entity_values:
                    relevant_graph.append(rel)

            chunk.graph_context = relevant_graph

        return chunks

    def build_formatted_prompt(
        self,
        query: str,
        chunks: list[PreparedChunk],
        graph_context: list[dict] | None = None,
    ) -> str:
        """
        Build a formatted prompt string ready for any LLM.

        Includes:
        1. Chunk context with source labels
        2. Graph context summary
        3. The user's query
        4. Instructions for response format

        The system prompt is NOT included here — it should be sent
        separately as the system message to the LLM.
        """
        # Build chunk context
        context_parts = []
        for i, chunk in enumerate(chunks):
            source_label = f"[Source {i + 1}: {chunk.source_type}]"
            if chunk.metadata.get("title"):
                source_label += f" ({chunk.metadata['title']})"

            # Add entity annotations
            entity_info = ""
            if chunk.entities_in_chunk:
                entity_names = [e["value"] for e in chunk.entities_in_chunk[:5]]
                entity_info = f"\n  Entities: {', '.join(entity_names)}"

            # Add graph annotations
            graph_info = ""
            if chunk.graph_context:
                graph_lines = []
                for rel in chunk.graph_context[:3]:  # Limit to 3 relationships per chunk
                    graph_lines.append(
                        f"  {rel['source_value']} --[{rel.get('relationship', 'RELATED_TO')}]--> "
                        f"{rel['target_value']}"
                    )
                graph_info = "\n  Graph Context:\n" + "\n".join(graph_lines)

            context_parts.append(f"{source_label}{entity_info}{graph_info}\n{chunk.text}")

        context = "\n\n---\n\n".join(context_parts)

        # Build global graph context summary
        graph_summary = ""
        if graph_context:
            graph_lines = []
            for rel in graph_context[:10]:  # Top 10 relationships
                graph_lines.append(
                    f"- {rel['source_value']} ({rel.get('source_type', '?')}) "
                    f"--[{rel.get('relationship', 'RELATED_TO')}]--> "
                    f"{rel['target_value']} ({rel.get('target_type', '?')})"
                )
            if graph_lines:
                graph_summary = "\n\nKnowledge Graph Relationships:\n" + "\n".join(graph_lines)

        prompt = f"""Context from the knowledge base:

{context}
{graph_summary}

---

Question: {query}

Answer using only the context above and cite sources as [Source N]."""

        return prompt

    def prepare_context(
        self,
        query: str,
        chunks: list[PreparedChunk],
        graph_context: list[dict] | None = None,
        entities_found: list[dict] | None = None,
        retrieval_metadata: dict | None = None,
    ) -> PreparedContext:
        """
        Build the final PreparedContext object ready for LLM consumption.

        This is the main entry point for the chunk builder — call this
        after retrieval and fusion to get the complete context package.

        Args:
            query: The user's original query
            chunks: Ranked chunks from RRF fusion
            graph_context: Knowledge graph relationships
            entities_found: Entities extracted from the query
            retrieval_metadata: Timing/scoring info from retrieval

        Returns:
            PreparedContext with everything a paid LLM needs
        """
        graph_context = graph_context or []
        entities_found = entities_found or []

        # Enrich chunks with entities and graph
        chunks = self.enrich_chunks_with_entities(chunks, entities_found)
        chunks = self.enrich_chunks_with_graph(chunks, graph_context)

        # Trim chunks to fit within token budget
        chunks = self._trim_to_token_budget(chunks)

        # Build formatted prompt
        formatted_prompt = self.build_formatted_prompt(query, chunks, graph_context)

        total_tokens = self.estimate_tokens(SYSTEM_PROMPT) + self.estimate_tokens(formatted_prompt)

        return PreparedContext(
            query=query,
            chunks=chunks,
            graph_context=graph_context,
            system_prompt=SYSTEM_PROMPT,
            formatted_prompt=formatted_prompt,
            total_token_estimate=total_tokens,
            entities_found=entities_found,
            retrieval_metadata=retrieval_metadata or {},
        )

    def _trim_to_token_budget(self, chunks: list[PreparedChunk]) -> list[PreparedChunk]:
        """
        Trim chunks to fit within the maximum token budget.

        Keeps the highest-relevance chunks first (they're already sorted
        by RRF score from the retrieval pipeline).
        """
        # Reserve tokens for system prompt and formatting
        available_tokens = self.max_total_tokens - self.estimate_tokens(SYSTEM_PROMPT) - 500

        selected = []
        used_tokens = 0

        for chunk in chunks:
            if used_tokens + chunk.token_estimate > available_tokens:
                break
            selected.append(chunk)
            used_tokens += chunk.token_estimate

        if len(selected) < len(chunks):
            logger.info(
                f"Trimmed from {len(chunks)} to {len(selected)} chunks "
                f"to fit token budget ({used_tokens}/{available_tokens} tokens)"
            )

        return selected
