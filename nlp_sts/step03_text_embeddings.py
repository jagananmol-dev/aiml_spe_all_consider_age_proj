"""
NLP pipeline — Step 3: Text embeddings (dense representation)

Each passage from step02_chunking.py, and later each question, becomes a
384-dimensional sentence embedding (all-MiniLM-L6-v2 by default):

- vectors are L2-normalised, so a dot product is the cosine similarity and
  search (step08_vector_search.py) is a single matrix product;
- a passage is embedded together with its document title, so a short
  passage keeps its context ("Dialysis SOP" + "check conductivity…");
- the same model is registered with step05_semantic_typing.py, so entity
  typing, entity merging and question-to-graph linking need no second model.
"""

import logging

logger = logging.getLogger("veda.intelligence.rag")


def load_embedding_model(model_name: str):
    """Load the sentence-transformers model and register it for entity typing."""
    from sentence_transformers import SentenceTransformer

    from . import step05_semantic_typing as semantic

    logger.info(f"Loading embedding model: {model_name}")
    # Load from the local cache first: without it, every start asks
    # huggingface.co for updates and fails when the machine is offline
    try:
        model = SentenceTransformer(model_name, local_files_only=True)
    except Exception:
        model = SentenceTransformer(model_name)
    # The knowledge graph types and links entities with this same
    # model (no second model in memory), batched and cached per phrase
    semantic.set_encoder(
        lambda texts: model.encode(
            texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False
        )
    )
    return model


def passage_texts(title: str | None, chunk_texts: list[str]) -> list[str]:
    """The text embedded for each passage: its document title, then the passage."""
    return [f"{title}\n\n{text}" if title else text for text in chunk_texts]


def embed_passages(model, texts: list[str]):
    """Embed passages in one batch; returns one normalised vector per text."""
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def embed_query(model, query: str) -> list[float]:
    """Embed a question the same way as the passages."""
    return model.encode(query, normalize_embeddings=True).tolist()
