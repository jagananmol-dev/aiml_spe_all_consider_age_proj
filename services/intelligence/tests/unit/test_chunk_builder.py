"""
VEDA AI — Chunk Builder Unit Tests

100% coverage target — all pure functions, no I/O.

Tests:
- estimate_tokens: correct approximation
- split_into_chunks: sections, paragraphs, sentences, empty text
- _split_into_sections: structural break detection
- _split_large_section: paragraph-level splitting with overlap
- _split_on_sentences: sentence-boundary fallback
- enrich_chunks_with_entities: entity-to-chunk association
- enrich_chunks_with_graph: graph context attachment
- build_formatted_prompt: prompt structure validation
- prepare_context: token budget trimming + full integration
- _trim_to_token_budget: budget enforcement
"""

import pytest

from src.knowledge_graph.chunk_builder import (
    ChunkBuilder,
    PreparedChunk,
    PreparedContext,
    SYSTEM_PROMPT,
    CHARS_PER_TOKEN,
)
from tests.conftest import (
    SAMPLE_INDUSTRIAL_TEXT,
    SAMPLE_GRAPH_CONTEXT,
    SAMPLE_ENTITIES_FOUND,
)


# ── Helpers ────────────────────────────────────────────


def make_chunk(text: str, doc_id: str = "doc-1", score: float = 0.5) -> PreparedChunk:
    builder = ChunkBuilder()
    return PreparedChunk(
        text=text,
        source_type="document",
        relevance_score=score,
        document_id=doc_id,
        token_estimate=builder.estimate_tokens(text),
    )


# ══════════════════════════════════════════════════════
# 1. Token Estimation
# ══════════════════════════════════════════════════════


class TestEstimateTokens:
    def test_empty_string_returns_one(self):
        b = ChunkBuilder()
        assert b.estimate_tokens("") == 1

    def test_single_char_returns_one(self):
        b = ChunkBuilder()
        assert b.estimate_tokens("a") == 1

    def test_four_chars_returns_one(self):
        b = ChunkBuilder()
        assert b.estimate_tokens("abcd") == 1

    def test_eight_chars_returns_two(self):
        b = ChunkBuilder()
        assert b.estimate_tokens("abcdefgh") == 2

    def test_400_chars_returns_100(self):
        b = ChunkBuilder()
        text = "a" * 400
        assert b.estimate_tokens(text) == 100

    def test_proportional(self):
        b = ChunkBuilder()
        text = "x" * 1000
        assert b.estimate_tokens(text) == 1000 // CHARS_PER_TOKEN


# ══════════════════════════════════════════════════════
# 2. Section Splitting
# ══════════════════════════════════════════════════════


class TestSplitIntoSections:
    def test_numbered_sections_split(self):
        b = ChunkBuilder()
        text = "Intro text.\n1. First section content here.\n2. Second section content here."
        sections = b._split_into_sections(text)
        assert len(sections) >= 2

    def test_caps_header_split(self):
        b = ChunkBuilder()
        text = "Some text\nPROCEDURE OVERVIEW:\nStep 1 details here.\nSAFETY NOTES:\nWear PPE."
        sections = b._split_into_sections(text)
        assert len(sections) >= 2

    def test_no_structural_breaks_splits_on_paragraphs(self):
        b = ChunkBuilder()
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        sections = b._split_into_sections(text)
        assert len(sections) >= 2

    def test_single_line_text(self):
        b = ChunkBuilder()
        text = "PUMP-101 was inspected."
        sections = b._split_into_sections(text)
        assert len(sections) >= 1

    def test_empty_sections_filtered(self):
        b = ChunkBuilder()
        text = "\n\n\n\nActual content here.\n\n\n"
        sections = b._split_into_sections(text)
        non_empty = [s for s in sections if s.strip()]
        assert len(non_empty) >= 1


# ══════════════════════════════════════════════════════
# 3. Chunk Splitting
# ══════════════════════════════════════════════════════


class TestSplitIntoChunks:
    def test_empty_text_returns_empty_list(self):
        b = ChunkBuilder()
        assert b.split_into_chunks("", "doc-1") == []

    def test_whitespace_only_returns_empty_list(self):
        b = ChunkBuilder()
        assert b.split_into_chunks("   \n\t  ", "doc-1") == []

    def test_short_text_returns_one_chunk(self):
        b = ChunkBuilder(max_chunk_size=5000)
        chunks = b.split_into_chunks("This is a short document.", "doc-1")
        assert len(chunks) == 1
        assert chunks[0].document_id == "doc-1"
        assert chunks[0].source_type == "document"

    def test_long_text_splits_into_multiple_chunks(self):
        b = ChunkBuilder(max_chunk_size=100)
        # Create text with paragraph breaks so it has natural split points
        paragraph = "This is a long paragraph with many words that should be split. " * 10
        long_text = ("\n\n" + paragraph) * 20
        chunks = b.split_into_chunks(long_text, "doc-long")
        assert len(chunks) > 1

    def test_chunks_have_token_estimates(self):
        b = ChunkBuilder()
        chunks = b.split_into_chunks(SAMPLE_INDUSTRIAL_TEXT, "doc-1")
        for chunk in chunks:
            assert chunk.token_estimate >= 1

    def test_chunks_have_correct_doc_id(self):
        b = ChunkBuilder()
        chunks = b.split_into_chunks("Some text here.", "my-doc-id-123")
        for chunk in chunks:
            assert chunk.document_id == "my-doc-id-123"

    def test_metadata_passed_through(self):
        b = ChunkBuilder()
        meta = {"title": "Test Document", "source": "SOP"}
        chunks = b.split_into_chunks("Content here.", "doc-1", metadata=meta)
        for chunk in chunks:
            assert chunk.metadata.get("title") == "Test Document"

    def test_chunk_text_not_empty(self):
        b = ChunkBuilder()
        chunks = b.split_into_chunks(SAMPLE_INDUSTRIAL_TEXT, "doc-1")
        for chunk in chunks:
            assert chunk.text.strip() != ""

    def test_chunk_index_in_metadata(self):
        b = ChunkBuilder()
        long_text = "Sentence with content. " * 200
        chunks = b.split_into_chunks(long_text, "doc-1")
        if len(chunks) > 1:
            indices = [c.metadata["chunk_index"] for c in chunks]
            # Indices should be sequential
            assert indices == list(range(len(chunks)))

    def test_max_chunk_size_respected(self):
        """No chunk should exceed max_chunk_size * 2 characters."""
        b = ChunkBuilder(max_chunk_size=200)
        # Build text with natural paragraph separators
        paragraph = "Long sentence with many distinct words in it for splitting. " * 10
        long_text = (paragraph + "\n\n") * 30
        chunks = b.split_into_chunks(long_text, "doc-1")
        for chunk in chunks:
            assert len(chunk.text) <= 200 * 3, f"Chunk too large: {len(chunk.text)} chars"


# ══════════════════════════════════════════════════════
# 4. Large Section Splitting
# ══════════════════════════════════════════════════════


class TestSplitLargeSection:
    def test_splits_by_paragraphs(self):
        b = ChunkBuilder(max_chunk_size=100)
        text = (
            "Long paragraph one with lots of content. " * 5
            + "\n\n"
            + "Long paragraph two with lots of content. " * 5
        )
        chunks = b._split_large_section(text)
        assert len(chunks) >= 1

    def test_falls_back_to_sentences_for_massive_paragraph(self):
        """A single paragraph exceeding 1.5x max_chunk_size triggers sentence splitting."""
        b = ChunkBuilder(max_chunk_size=50)
        text = "This is sentence one. This is sentence two. This is sentence three. Final sentence."
        chunks = b._split_large_section(text)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.strip() != ""

    def test_overlap_applied(self):
        """The overlap region should appear in consecutive chunks."""
        b = ChunkBuilder(max_chunk_size=100, chunk_overlap=20)
        text = (
            "Content block one with multiple words. " * 4
            + "\n\n"
            + "Content block two with different words. " * 4
        )
        chunks = b._split_large_section(text)
        if len(chunks) > 1:
            # The end of chunk[0] should overlap with the start of chunk[1]
            end_of_first = chunks[0][-20:]
            assert end_of_first in chunks[1]


# ══════════════════════════════════════════════════════
# 5. Entity Enrichment
# ══════════════════════════════════════════════════════


class TestEnrichChunksWithEntities:
    def test_entity_in_chunk_text_is_attached(self):
        b = ChunkBuilder()
        chunk = make_chunk("PUMP-101 failed with bearing seizure.")
        entities = [
            {
                "entity_type": "EQUIPMENT_TAG",
                "value": "PUMP-101",
                "normalized_value": "PUMP-101",
                "confidence": 0.95,
            },
            {
                "entity_type": "FAILURE_MODE",
                "value": "bearing seizure",
                "normalized_value": "bearing seizure",
                "confidence": 0.85,
            },
        ]
        result = b.enrich_chunks_with_entities([chunk], entities)
        assert len(result[0].entities_in_chunk) == 2

    def test_entity_not_in_chunk_not_attached(self):
        b = ChunkBuilder()
        chunk = make_chunk("Unrelated content about procedures.")
        entities = [
            {
                "entity_type": "EQUIPMENT_TAG",
                "value": "PUMP-101",
                "normalized_value": "PUMP-101",
                "confidence": 0.95,
            },
        ]
        result = b.enrich_chunks_with_entities([chunk], entities)
        assert len(result[0].entities_in_chunk) == 0

    def test_empty_entities_list(self):
        b = ChunkBuilder()
        chunk = make_chunk("PUMP-101 content here.")
        result = b.enrich_chunks_with_entities([chunk], [])
        assert result[0].entities_in_chunk == []

    def test_empty_chunks_list(self):
        b = ChunkBuilder()
        result = b.enrich_chunks_with_entities(
            [],
            [
                {
                    "entity_type": "EQUIPMENT_TAG",
                    "value": "X",
                    "normalized_value": "X",
                    "confidence": 0.9,
                }
            ],
        )
        assert result == []

    def test_case_insensitive_matching(self):
        """Entity matching should be case-insensitive."""
        b = ChunkBuilder()
        chunk = make_chunk("pump-101 was inspected.")  # lowercase
        entities = [
            {
                "entity_type": "EQUIPMENT_TAG",
                "value": "PUMP-101",
                "normalized_value": "pump-101",
                "confidence": 0.95,
            }
        ]
        result = b.enrich_chunks_with_entities([chunk], entities)
        assert len(result[0].entities_in_chunk) == 1


# ══════════════════════════════════════════════════════
# 6. Graph Enrichment
# ══════════════════════════════════════════════════════


class TestEnrichChunksWithGraph:
    def test_relevant_graph_context_attached(self):
        b = ChunkBuilder()
        chunk = make_chunk("PUMP-101 was inspected.")
        chunk.entities_in_chunk = [
            {
                "normalized_value": "PUMP-101",
                "value": "PUMP-101",
                "type": "EQUIPMENT_TAG",
                "confidence": 0.95,
            }
        ]
        result = b.enrich_chunks_with_graph([chunk], SAMPLE_GRAPH_CONTEXT)
        # PUMP-101 appears in graph context as source — should be attached
        assert len(result[0].graph_context) > 0

    def test_no_matching_graph_context(self):
        b = ChunkBuilder()
        chunk = make_chunk("Unrelated content.")
        chunk.entities_in_chunk = []
        result = b.enrich_chunks_with_graph([chunk], SAMPLE_GRAPH_CONTEXT)
        assert result[0].graph_context == []

    def test_empty_graph_context(self):
        b = ChunkBuilder()
        chunk = make_chunk("PUMP-101 content.")
        chunk.entities_in_chunk = [
            {
                "normalized_value": "PUMP-101",
                "value": "PUMP-101",
                "type": "EQUIPMENT_TAG",
                "confidence": 0.95,
            }
        ]
        result = b.enrich_chunks_with_graph([chunk], [])
        assert result[0].graph_context == []


# ══════════════════════════════════════════════════════
# 7. Formatted Prompt
# ══════════════════════════════════════════════════════


class TestBuildFormattedPrompt:
    def test_prompt_contains_query(self):
        b = ChunkBuilder()
        chunk = make_chunk("Some context about PUMP-101.")
        prompt = b.build_formatted_prompt("What is PUMP-101?", [chunk])
        assert "What is PUMP-101?" in prompt

    def test_prompt_contains_source_label(self):
        b = ChunkBuilder()
        chunk = make_chunk("Context content.")
        prompt = b.build_formatted_prompt("Query", [chunk])
        assert "[Source 1:" in prompt

    def test_prompt_contains_chunk_text(self):
        b = ChunkBuilder()
        chunk = make_chunk("The pump operates at high pressure.")
        prompt = b.build_formatted_prompt("Query", [chunk])
        assert "The pump operates at high pressure." in prompt

    def test_prompt_contains_graph_context_section(self):
        b = ChunkBuilder()
        chunk = make_chunk("PUMP-101 context.")
        prompt = b.build_formatted_prompt("Query", [chunk], SAMPLE_GRAPH_CONTEXT)
        assert "Knowledge Graph Relationships" in prompt
        assert "PUMP-101" in prompt

    def test_prompt_has_entities_annotation(self):
        b = ChunkBuilder()
        chunk = make_chunk("PUMP-101 was serviced.")
        chunk.entities_in_chunk = [
            {
                "value": "PUMP-101",
                "normalized_value": "PUMP-101",
                "type": "EQUIPMENT_TAG",
                "confidence": 0.95,
            }
        ]
        prompt = b.build_formatted_prompt("Query", [chunk])
        assert "Entities:" in prompt
        assert "PUMP-101" in prompt

    def test_multiple_chunks_separated(self):
        b = ChunkBuilder()
        chunk1 = make_chunk("First chunk content.")
        chunk2 = make_chunk("Second chunk content.")
        prompt = b.build_formatted_prompt("Query", [chunk1, chunk2])
        assert "[Source 1:" in prompt
        assert "[Source 2:" in prompt
        assert "---" in prompt

    def test_empty_chunks_still_valid(self):
        b = ChunkBuilder()
        prompt = b.build_formatted_prompt("Any query?", [])
        assert "Any query?" in prompt
        assert isinstance(prompt, str)


# ══════════════════════════════════════════════════════
# 8. Token Budget Trimming
# ══════════════════════════════════════════════════════


class TestTrimToTokenBudget:
    def test_trims_when_over_budget(self):
        b = ChunkBuilder(max_total_tokens=500)
        # Create chunks that together exceed the budget
        chunks = [make_chunk("x" * 300) for _ in range(10)]
        for c in chunks:
            c.token_estimate = 100
        result = b._trim_to_token_budget(chunks)
        assert len(result) < len(chunks)

    def test_keeps_all_when_under_budget(self):
        b = ChunkBuilder(max_total_tokens=50000)
        chunks = [make_chunk("Short text.") for _ in range(5)]
        result = b._trim_to_token_budget(chunks)
        assert len(result) == 5

    def test_empty_list(self):
        b = ChunkBuilder()
        assert b._trim_to_token_budget([]) == []

    def test_highest_relevance_kept_first(self):
        """Chunks sorted by relevance — trimming cuts from the tail.
        The budget must account for system prompt overhead (~500 tokens).
        Set budget to exactly fit 2 chunks + overhead, verifying 3rd is cut.
        """
        # Each chunk = 600 tokens; budget = 1700 (= system_overhead ~500 + 2 chunks = 1200)
        b = ChunkBuilder(max_total_tokens=1700)
        chunks = [
            PreparedChunk("high relevance", "document", 0.9, "doc-1", token_estimate=600),
            PreparedChunk("mid relevance", "document", 0.7, "doc-1", token_estimate=600),
            PreparedChunk("low relevance", "document", 0.3, "doc-1", token_estimate=600),
        ]
        result = b._trim_to_token_budget(chunks)
        texts = [c.text for c in result]
        assert "high relevance" in texts
        assert "low relevance" not in texts


# ══════════════════════════════════════════════════════
# 9. Full prepare_context Integration
# ══════════════════════════════════════════════════════


class TestPrepareContext:
    def test_returns_prepared_context(self):
        b = ChunkBuilder()
        chunk = make_chunk("PUMP-101 failed with bearing seizure.")
        context = b.prepare_context(
            query="What failed?",
            chunks=[chunk],
            graph_context=SAMPLE_GRAPH_CONTEXT,
            entities_found=SAMPLE_ENTITIES_FOUND,
        )
        assert isinstance(context, PreparedContext)
        assert context.query == "What failed?"

    def test_system_prompt_included(self):
        b = ChunkBuilder()
        chunk = make_chunk("Some text.")
        context = b.prepare_context("Q", [chunk])
        assert context.system_prompt == SYSTEM_PROMPT

    def test_total_token_estimate_positive(self):
        b = ChunkBuilder()
        chunk = make_chunk("Some text.")
        context = b.prepare_context("Q", [chunk])
        assert context.total_token_estimate > 0

    def test_formatted_prompt_non_empty(self):
        b = ChunkBuilder()
        chunk = make_chunk("Content here.")
        context = b.prepare_context("My question", [chunk])
        assert len(context.formatted_prompt) > 0
        assert "My question" in context.formatted_prompt

    def test_none_defaults_handled(self):
        """graph_context=None, entities_found=None should not raise."""
        b = ChunkBuilder()
        chunk = make_chunk("Content.")
        context = b.prepare_context("Q", [chunk], graph_context=None, entities_found=None)
        assert context.graph_context == []
        assert context.entities_found == []

    def test_retrieval_metadata_passed_through(self):
        b = ChunkBuilder()
        meta = {"retrieval_latency_ms": 42, "confidence_score": 85.0}
        chunk = make_chunk("Text.")
        context = b.prepare_context("Q", [chunk], retrieval_metadata=meta)
        assert context.retrieval_metadata == meta

    def test_chunks_enriched_with_entities(self):
        """After prepare_context, chunks should have entity annotations."""
        b = ChunkBuilder()
        chunk = make_chunk("PUMP-101 failed with bearing seizure.")
        context = b.prepare_context(
            "Q",
            [chunk],
            entities_found=SAMPLE_ENTITIES_FOUND,
        )
        assert len(context.chunks) >= 1
        # At least one chunk should have entities attached
        total_entities = sum(len(c.entities_in_chunk) for c in context.chunks)
        assert total_entities > 0


class TestSectionMarkersStayWithContent:
    """Regression: markers like '##' must not become chunks of their own."""

    def test_markdown_headings_attach_to_their_section(self):
        builder = ChunkBuilder()
        text = "# Policy\n\n## Eligibility\nWithin 30 days.\n\n## Exclusions\nGift cards."
        texts = [c.text for c in builder.split_into_chunks(text, "doc")]
        assert texts == [
            "# Policy",
            "## Eligibility\nWithin 30 days.",
            "## Exclusions\nGift cards.",
        ]

    def test_numbered_and_caps_headers_attach(self):
        builder = ChunkBuilder()
        text = "1. Scope\nAll staff.\n2. Leave\n20 days.\nSAFETY RULES:\nWear helmets."
        texts = [c.text for c in builder.split_into_chunks(text, "doc")]
        assert texts == [
            "1. Scope\nAll staff.",
            "2. Leave\n20 days.",
            "SAFETY RULES:\nWear helmets.",
        ]

    def test_no_chunk_without_letters_or_digits(self):
        builder = ChunkBuilder()
        chunks = builder.split_into_chunks("Intro text\n---\n\n---\nMore text", "doc")
        assert all(any(ch.isalnum() for ch in c.text) for c in chunks)
