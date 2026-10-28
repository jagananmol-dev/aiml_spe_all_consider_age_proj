"""
NLP pipeline — Step 9: Rank fusion (Reciprocal Rank Fusion)

Merges the ranked lists from every retriever (dense vectors from
step08_vector_search.py, graph traversal, BM25 full-text) into one list:

    score(passage) = Σ over lists  1 / (k + rank)

A passage found by several retrievers rises; no retriever's raw scores need
to be comparable with another's. Next: step10_context_building.py.
"""


def reciprocal_rank_fusion(result_lists: list[list], k: int = 60, top_n: int = 8) -> list:
    """
    Fuse ranked lists of retrieved chunks (objects with document_id,
    chunk_text and score). Returns the top_n chunks, each with its fused score.
    """
    doc_scores: dict[str, float] = {}
    doc_chunks: dict[str, object] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            # The same passage from two retrievers counts once
            doc_key = f"{chunk.document_id}:{chunk.chunk_text[:100]}"
            rrf_score = 1.0 / (k + rank + 1)

            if doc_key in doc_scores:
                doc_scores[doc_key] += rrf_score
                # Keep the chunk with more context
                if len(chunk.chunk_text) > len(doc_chunks[doc_key].chunk_text):
                    doc_chunks[doc_key] = chunk
            else:
                doc_scores[doc_key] = rrf_score
                doc_chunks[doc_key] = chunk

    # Sort by fused score
    sorted_keys = sorted(doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True)

    fused_results = []
    for key in sorted_keys[:top_n]:
        chunk = doc_chunks[key]
        chunk.score = doc_scores[key]
        fused_results.append(chunk)

    return fused_results
