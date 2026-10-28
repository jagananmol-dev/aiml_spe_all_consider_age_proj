"""
Retrieval evaluation for the demo tenants, without the LLM.

Runs the known-answer questions of scripts/demo/check_chat.py (Nephrova,
synthetic) and scripts/enron/check_chat.py (Enron, real) through the same
retrieval the chatbot uses (RAGPipeline.prepare) and reports, per tenant:

- Hit@k: a passage in the top k contains every expected string of an answer
  alternative (the evidence an answer needs reached the LLM);
- MRR: mean reciprocal rank of the first such passage;
- retrieval latency (median, p95);
- the same with the knowledge-graph boost off (ablation).

Run from the repository root with the intelligence venv:

    services/intelligence/.venv/Scripts/python.exe scripts/eval/retrieval_eval.py [--tenant nephrova|enron]
"""

import argparse
import asyncio
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Local-mode settings, as scripts/dev.js starts the intelligence service
for line in (ROOT / ".env").read_text().splitlines():
    if line.startswith("DATABASE_URL="):
        os.environ.setdefault("VEDA_DATABASE_URL", line.split("=", 1)[1].strip())
os.environ.update(
    {
        "VEDA_VECTOR_BACKEND": "local",
        "VEDA_GRAPH_BACKEND": "local",
        "VEDA_GRAPH_ENABLED": "false",
        "VEDA_OPENSEARCH_ENABLED": "false",
        "VEDA_MAX_CHUNK_TOKENS": "3500",
    }
)
sys.path.insert(0, str(ROOT / "services" / "intelligence"))

import psycopg  # noqa: E402

from src.rag.pipeline import rag_pipeline, settings  # noqa: E402

KS = (1, 3, 5, 8)


def load_checks(path: Path) -> list[tuple[str, list[list[str]]]]:
    """CHECKS from a check_chat.py, as (question, alternatives of required strings)."""
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(f"checks_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.pop(0)
    out = []
    for question, expected in module.CHECKS:
        alternatives = expected if expected and isinstance(expected[0], list) else [expected]
        out.append((question, alternatives))
    return out


def first_hit(passages: list[str], alternatives: list[list[str]]) -> int | None:
    """1-based rank of the first passage that holds one whole answer alternative."""
    for rank, text in enumerate(passages, start=1):
        lowered = text.lower()
        if any(all(s.lower() in lowered for s in alt) for alt in alternatives):
            return rank
    return None


def tenant_id(slug: str) -> str:
    with psycopg.connect(settings.database_url) as conn:
        row = conn.execute("SELECT id::text FROM tenants WHERE slug = %s", [slug]).fetchone()
    if not row:
        raise SystemExit(f"No tenant {slug}")
    return row[0]


async def evaluate(slug: str, checks, boost: float) -> dict:
    settings.graph_retrieval_boost = boost
    tid = tenant_id(slug)
    await rag_pipeline.prepare("warm up", tid)  # loads the model and the tenant index
    ranks, latencies, rows = [], [], []
    for question, alternatives in checks:
        started = time.perf_counter()
        context = await rag_pipeline.prepare(question, tid)
        latencies.append((time.perf_counter() - started) * 1000)
        rank = first_hit([c.text for c in context.chunks], alternatives)
        ranks.append(rank)
        rows.append({"question": question, "rank": rank})
    n = len(checks)
    return {
        "questions": n,
        **{f"hit@{k}": sum(1 for r in ranks if r and r <= k) / n for k in KS},
        "mrr": sum(1 / r for r in ranks if r) / n,
        "latency_ms_median": statistics.median(latencies),
        "latency_ms_p95": sorted(latencies)[max(0, round(0.95 * n) - 1)],
        "per_question": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tenant", choices=["nephrova", "enron"], action="append")
    parser.add_argument("--json", type=Path, help="also write the results here")
    args = parser.parse_args()

    suites = {
        "nephrova": ROOT / "scripts" / "demo" / "check_chat.py",
        "enron": ROOT / "scripts" / "enron" / "check_chat.py",
    }
    results = {}
    default_boost = settings.graph_retrieval_boost
    for slug in args.tenant or list(suites):
        checks = load_checks(suites[slug])
        results[slug] = {
            "graph_boost": asyncio.run(evaluate(slug, checks, default_boost)),
            "no_graph_boost": asyncio.run(evaluate(slug, checks, 0.0)),
        }

    header = f"{'tenant':<10}{'variant':<16}" + "".join(f"{'Hit@' + str(k):>8}" for k in KS)
    print(header + f"{'MRR':>8}{'p50 ms':>9}{'p95 ms':>9}")
    for slug, variants in results.items():
        for name, r in variants.items():
            print(
                f"{slug:<10}{name:<16}"
                + "".join(f"{r[f'hit@{k}']:>8.2f}" for k in KS)
                + f"{r['mrr']:>8.3f}{r['latency_ms_median']:>9.0f}{r['latency_ms_p95']:>9.0f}"
            )
    for slug, variants in results.items():
        misses = [q["question"] for q in variants["graph_boost"]["per_question"] if not q["rank"]]
        if misses:
            print(f"\n{slug}: evidence not retrieved for {len(misses)} question(s):")
            for q in misses:
                print(f"  - {q}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
