"""
NLP pipeline — Step 8: Vector search (dense retrieval with a graph boost)

Ranks a tenant's passages against the question embedding from
step03_text_embeddings.py:

1. cosine similarity of every passage (one matrix product, vectors are
   normalised);
2. graph boost: passages that name an entity the question was linked to in
   the knowledge graph (step07_relation_extraction.py) gain boost_amount;
3. top-k selection;
4. similarity cut-off, with a low-confidence fallback: when nothing clears
   min_score, the closest few passages are still returned, flagged, so the
   answer can use them or say what is missing.

Loading the vectors from PostgreSQL and caching them stays in the service
(services/intelligence/src/rag/local_store.py). Next: step09_rank_fusion.py.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class SearchResult:
    """Passage positions in rank order, their scores, and search stats."""

    positions: list[int]
    scores: list[float]
    low_confidence: bool
    boosted: int | None = None  # passages raised by the graph boost (None: boost off)


def rank_passages(
    matrix: np.ndarray,
    query_embedding: list[float],
    top_k: int,
    min_score: float = 0.0,
    fallback_k: int = 0,
    document_ids: list[str] | None = None,
    texts: list[str] | None = None,
    boost: dict[str, set[str]] | None = None,
    boost_amount: float = 0.0,
) -> SearchResult:
    """
    Rank the rows of `matrix` (one normalised passage vector per row).

    `boost` maps document_id → entity names (lower case) from the graph; a
    passage of such a document that names one of them gains boost_amount.
    `document_ids` and `texts` (row-aligned) are needed only for the boost.
    """
    query = np.asarray(query_embedding, dtype=np.float32)
    scores = matrix @ query

    boosted = None
    if boost and boost_amount and document_ids is not None and texts is not None:
        boosted = 0
        for j, (document_id, text) in enumerate(zip(document_ids, texts)):
            terms = boost.get(document_id)
            if terms:
                lowered = text.lower()
                if any(term in lowered for term in terms):
                    scores[j] += boost_amount
                    boosted += 1

    # Top-k without sorting every passage: partition, then sort the k best
    k = min(top_k, len(scores))
    best = np.argpartition(-scores, k - 1)[:k]
    best = best[np.argsort(-scores[best])]

    # Nothing clears the cut-off: still return the closest few (when asked),
    # flagged as a weak match, so the answer can use or rule them out
    low_confidence = bool(fallback_k > 0 and not (scores[best] >= min_score).any())
    if low_confidence:
        best = best[:fallback_k]
    else:
        best = best[scores[best] >= min_score]

    return SearchResult(
        positions=[int(i) for i in best],
        scores=[float(scores[i]) for i in best],
        low_confidence=low_confidence,
        boosted=boosted,
    )
