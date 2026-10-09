"""
VEDA AI — Embedding-based entity typing

Patterns and term lists only find what someone wrote down in advance. This
module finds the rest in any domain: key phrases mined from the text are
embedded and take the entity type of their most similar schema example
(nearest-example classification), and unknown codes ("LN-2041", "AHU3") are
typed by the words around them.

Efficiency:
- one embedding model for everything: the RAG pipeline registers its
  already-loaded SentenceTransformer with set_encoder(), nothing else loads one;
- every phrase is embedded once per process (bounded LRU cache), and all of
  a document's uncached phrases go to the model in a single batch;
- the example matrix is embedded once per schema version;
- typing is one matrix product (phrases × examples) per document.

Without a registered encoder (tests, the Kafka worker before warm-up) the
extractor simply skips this step.
"""

import logging
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .schema import GraphSchema

logger = logging.getLogger("veda.intelligence.semantic")

# English function words: they end a candidate phrase. Language plumbing,
# not domain vocabulary.
STOPWORDS = frozenset(
    """a about above after again against all also am an and any are as at be because been before being
    below between both but by can could did do does doing done down during each either else every few for
    from further had has have having he her here hers herself him himself his how however i if in into is it
    its itself just least less let like may me might more most must my myself near need no nor not now of
    off on once only or other our ours ourselves out over own per please same shall she should since so
    some such than that the their theirs them themselves then there these they this those through thus to
    too under until up upon us use used using very via was we were what when where whether which while who
    whom whose why will with within without would yes yet you your yours yourself yourselves
    one two three four five six seven eight nine ten first second third new old high low good total
    each daily weekly monthly yearly annual per cent percent include includes including included
    """.split()
)

# Common verb forms that also end a phrase, so "vancomycin given" or
# "conductivity cell replacement followed" are typed without the verb.
# Words ending in "-ed" are treated the same way (see _is_breaker).
VERB_FORMS = frozenset(
    """given found shown shows show taken made done seen gets got uses covers remains remain continues
    requires require needs catch catches keeps keep goes went came comes says said told""".split()
)


def _is_breaker(word: str) -> bool:
    return (
        word in STOPWORDS
        or word in VERB_FORMS
        or (len(word) > 4 and word.endswith("ed"))
        or any(ch.isdigit() for ch in word)  # codes are typed separately
    )


# Words: letters (digits allowed after the first), joined by an apostrophe
# or hyphen. Underscores split words, so JSON keys like "endotoxin_eu_ml"
# never become phrases.
_TOKEN = re.compile(r"[^\W\d_][^\W_]*(?:['’\-][^\W_]+)*")
_PHRASE_BREAK = re.compile(r"[^\s]")  # anything but whitespace between tokens ends a phrase


class EmbeddingCache:
    """Normalised phrase vectors, computed once per phrase and batched."""

    def __init__(self, encode: Callable[[list[str]], np.ndarray], max_items: int = 50_000):
        self._encode = encode
        self._max = max_items
        self._vectors: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        with self._lock:
            missing = list(dict.fromkeys(t for t in texts if t not in self._vectors))
        if missing:
            vectors = np.asarray(self._encode(missing), dtype=np.float32)
            with self._lock:
                for text, vector in zip(missing, vectors):
                    self._vectors[text] = vector
                while len(self._vectors) > self._max:
                    self._vectors.popitem(last=False)
        with self._lock:
            out = []
            for t in texts:
                vector = self._vectors.get(t)
                if vector is None:  # evicted by a concurrent batch
                    vector = np.asarray(self._encode([t]), dtype=np.float32)[0]
                else:
                    self._vectors.move_to_end(t)
                out.append(vector)
        return np.stack(out)


_cache: EmbeddingCache | None = None


def set_encoder(encode: Callable[[list[str]], np.ndarray] | None) -> None:
    """Register the process's embedding function (normalised vectors), or None to disable."""
    global _cache
    _cache = EmbeddingCache(encode) if encode is not None else None
    _typers.clear()


def get_cache() -> EmbeddingCache | None:
    return _cache


# ── Typing against schema examples ─────────────────────


class SemanticTyper:
    """Nearest-example classifier over a schema's types, plus a background class."""

    def __init__(self, schema: GraphSchema, cache: EmbeddingCache):
        self.schema = schema
        self.cache = cache
        texts: list[str] = []
        labels: list[str] = []
        for t in schema.types.values():
            examples = [*t.examples, *t.terms]
            if t.description:
                examples.append(t.description)
            for text in dict.fromkeys(e.lower() for e in examples):
                texts.append(text)
                labels.append(t.name)
        self.type_names = sorted(set(labels))
        self.labels = np.asarray([self.type_names.index(label) for label in labels])
        self.examples = cache.encode(texts) if texts else np.zeros((0, 1), dtype=np.float32)
        background = [b.lower() for b in schema.semantic.get("background_examples", [])]
        self.background = cache.encode(background) if background else None
        # A phrase headed by a background noun ("incident report",
        # "disinfection log") names a record, not the thing itself
        self.background_heads = {b for b in background if " " not in b}
        # Phrases never become identifier types (assets come from codes)
        self.identifier_types = {t.name for t in schema.types.values() if t.identifier}

        # Identifier types are matched on the words around a code, by their examples only
        id_texts, id_labels = [], []
        for t in schema.types.values():
            if t.identifier:
                for e in dict.fromkeys(x.lower() for x in t.examples):
                    id_texts.append(e)
                    id_labels.append(t.name)
        self.id_labels = id_labels
        self.id_examples = cache.encode(id_texts) if id_texts else None

    def type_scores(self, vectors: np.ndarray) -> np.ndarray:
        """(n phrases × n types) best similarity to any example of each type."""
        sims = vectors @ self.examples.T
        scores = np.full((len(vectors), len(self.type_names)), -1.0, dtype=np.float32)
        for k in range(len(self.type_names)):
            cols = self.labels == k
            scores[:, k] = sims[:, cols].max(axis=1)
        return scores

    def _eligible(self, phrase: str) -> bool:
        words = phrase.split()
        if not words:
            return False
        if len(words) == 1 and not self.schema.semantic.get("allow_single_words", False):
            return (
                False  # single words are mostly generic ("alarm", "audit"); list real ones as terms
            )
        head = words[-1]
        return head not in self.background_heads and head.rstrip("s") not in self.background_heads

    def classify(self, phrases: list[str]) -> list[tuple[str, float] | None]:
        results: list[tuple[str, float] | None] = [None] * len(phrases)
        if not phrases or len(self.type_names) == 0:
            return results
        # Cheap filters first, so only plausible phrases reach the model
        keep = [i for i, p in enumerate(phrases) if self._eligible(p)]
        if not keep:
            return results
        cfg = self.schema.semantic
        vectors = self.cache.encode([phrases[i] for i in keep])
        scores = self.type_scores(vectors)
        background = (
            (vectors @ self.background.T).max(axis=1)
            if self.background is not None
            else np.full(len(keep), -1.0)
        )
        order = np.argsort(-scores, axis=1)
        threshold = cfg.get("min_similarity", 0.7)
        margin = cfg.get("min_margin", 0.06)
        for row, i in enumerate(keep):
            best = order[row, 0]
            top = float(scores[row, best])
            runner_up = float(scores[row, order[row, 1]]) if scores.shape[1] > 1 else -1.0
            name = self.type_names[best]
            if (
                name not in self.identifier_types
                and top >= threshold
                and top - runner_up >= margin
                and top > float(background[row])
            ):
                results[i] = (name, top)
        return results

    def classify_identifiers(self, contexts: list[str]) -> list[tuple[str, float] | None]:
        if self.id_examples is None or not contexts:
            return [None] * len(contexts)
        threshold = self.schema.semantic.get("identifier_context_similarity", 0.55)
        vectors = self.cache.encode(contexts)
        sims = vectors @ self.id_examples.T
        background = (
            (vectors @ self.background.T).max(axis=1)
            if self.background is not None
            else np.full(len(contexts), -1.0)
        )
        results: list[tuple[str, float] | None] = []
        for row, bg in zip(sims, background):
            j = int(row.argmax())
            # "risk RSK-02", "policy HR-03": closer to a background word than an asset
            ok = row[j] >= threshold and row[j] > bg
            results.append((self.id_labels[j], float(row[j])) if ok else None)
        return results


_typers: dict[str, SemanticTyper] = {}
_typers_lock = threading.Lock()


def get_typer(schema: GraphSchema) -> SemanticTyper | None:
    """The typer for a schema version, or None when no encoder is registered."""
    cache = _cache
    if cache is None or not schema.semantic.get("enabled", True):
        return None
    with _typers_lock:
        typer = _typers.get(schema.fingerprint)
        if typer is None or typer.cache is not cache:
            typer = _typers[schema.fingerprint] = SemanticTyper(schema, cache)
        return typer


# ── Candidate mining ───────────────────────────────────


@dataclass
class Candidate:
    phrase: str  # lower-cased, used for typing and as the normalised value
    surface: str  # first occurrence as written
    spans: list[tuple[int, int]]


def candidate_phrases(
    text: str, max_words: int = 4, min_chars: int = 4, limit: int = 400
) -> list[Candidate]:
    """
    Content-word runs (no stop words, digits or punctuation inside) of up to
    max_words words — the noun-phrase-like spans worth typing. Longer runs
    keep their last max_words words (English heads come last).
    """
    found: dict[str, Candidate] = {}

    def emit(run: list[re.Match]) -> None:
        run = run[-max_words:]
        start, end = run[0].start(), run[-1].end()
        surface = text[start:end]
        phrase = " ".join(m.group(0).lower() for m in run)
        if len(phrase) < min_chars:
            return
        cand = found.get(phrase)
        if cand is None:
            found[phrase] = Candidate(phrase, surface, [(start, end)])
        else:
            cand.spans.append((start, end))

    run: list[re.Match] = []
    last_end = 0
    for m in _TOKEN.finditer(text):
        gap = text[last_end : m.start()]
        word = m.group(0).lower().strip("'’-")
        if run and (_PHRASE_BREAK.search(gap) or "\n" in gap):
            emit(run)
            run = []
        if _is_breaker(word) or len(word) < 2:
            if run:
                emit(run)
                run = []
        else:
            run.append(m)
        last_end = m.end()
    if run:
        emit(run)

    # Keep the phrases most likely to matter: repeated, then multi-word
    ranked = sorted(
        found.values(), key=lambda c: (-len(c.spans), -c.phrase.count(" "), c.spans[0][0])
    )
    return ranked[:limit]


def identifier_context(text: str, start: int, end: int, words: int = 3, window: int = 40) -> str:
    """
    Up to `words` content words right before a code, on its line ("machine
    HD-K04", "loan LN-2041"). The words after a code describe what it is
    about rather than what it is ("RSK-04 Dialysis machine failure" is a
    risk, not a machine), so they are not used; no words means no typing.
    """
    line_start = text.rfind("\n", 0, start) + 1
    before = [
        w.lower()
        for w in _TOKEN.findall(text[max(line_start, start - window) : start])
        if w.lower() not in STOPWORDS
    ]
    return " ".join(before[-words:])


def merge_similar(
    values: list[str], vectors: np.ndarray, threshold: float, protected: set[str] | None = None
) -> dict[str, str]:
    """
    Map each value to a canonical one: greedy clustering in the given order,
    so earlier values (existing nodes, exact terms) become the canonical
    names. Protected values (curated terms) always keep their own name:
    "disinfection" and "chemical disinfection" are both listed, so both stay.
    """
    protected = protected or set()
    canonical: dict[str, str] = {}
    centres: list[int] = []
    for i, value in enumerate(values):
        if centres and value not in protected:
            sims = vectors[centres] @ vectors[i]
            j = int(sims.argmax())
            if sims[j] >= threshold:
                canonical[value] = canonical[values[centres[j]]]
                continue
        centres.append(i)
        canonical[value] = value
    return canonical
