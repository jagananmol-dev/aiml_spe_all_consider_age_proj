"""
NLP pipeline — Step 10: Context building (the LLM prompt)

The last step before generation. The ranked passages from
step09_rank_fusion.py are:

1. annotated with the question's entities (step06) and graph facts (step07);
2. trimmed to the token budget, best passages first;
3. formatted into one provider-agnostic prompt with [Source N] labels,
   next to a domain-neutral system prompt.

The web app (apps/web/src/lib/chatPrompt.ts) streams the final answer from
the LLM with these passages.
"""

import logging
from dataclasses import dataclass, field

from .step02_chunking import PreparedChunk, TextChunker

logger = logging.getLogger("veda.intelligence.chunk_builder")


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


class ChunkBuilder(TextChunker):
    """
    Builds LLM-ready chunks from raw text, entities, and graph context.

    Splitting comes from TextChunker (step 2); this class adds graph
    enrichment — each chunk is annotated with knowledge graph relationships,
    so the LLM has structural understanding (not just text similarity) of
    how entities connect.
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
        super().__init__(max_chunk_size, chunk_overlap)
        self.max_total_tokens = max_total_tokens

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
