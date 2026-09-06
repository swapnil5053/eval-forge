"""A believable week of traffic, written straight to the database.

The point is that someone can install EvalForge and see every page of the panel
populated without owning an API key, a RAG pipeline or a dataset. Nothing here
calls a model: the numbers, the failures and the judge verdicts are all fixtures,
and the same seed produces the same database every time so a screenshot taken
today matches one taken next month.
"""

import datetime
import random
import uuid
from typing import Dict, List, Optional, Tuple

from .storage.duckdb_store import Store

SEED = 11
DAYS = 7

# Everything the seeder writes, so 'evalforge demo --replace' can clear exactly
# what it put there and nothing else.
TABLES = (
    "audit_claims", "faithfulness_audits", "experiment_results", "experiments",
    "dataset_items", "datasets", "feedback_scores", "spans", "traces",
)

MODELS = (
    ("gpt-4o-mini", 0.15 / 1_000_000, 0.60 / 1_000_000),
    ("claude-sonnet-4-5", 3.00 / 1_000_000, 15.00 / 1_000_000),
    ("ollama/llama3", 0.0, 0.0),
)

# A support assistant over a returns policy: small enough to read, real enough
# that the audit findings below are the ones such a bot actually gets wrong.
PASSAGES = (
    "Refunds are issued to the original payment method within 30 days.",
    "Damaged items qualify for refunded shipping fees.",
    "Store credit is issued for items returned after the 30-day window.",
    "Opened software and gift cards are not returnable.",
)

ANSWER = "Refunds go to the original payment method within 30 days of delivery."

QUESTIONS = (
    "How are refunds issued?",
    "Can store credit become cash?",
    "What is the refund window?",
    "Do I pay shipping on a damaged item?",
    "Is opened software returnable?",
    "How long until the money is back on my card?",
)

PIPELINE = (
    ("classify-intent", "llm", 0.10),
    ("retrieve", "retrieval", 0.22),
    ("generate", "llm", 0.68),
)


def seed(store: Store, days: int = DAYS, rng_seed: int = SEED) -> Dict[str, int]:
    """Fill an empty database with a week of traffic. Returns what it wrote."""
    rng = random.Random(rng_seed)
    now = datetime.datetime.now(datetime.timezone.utc)

    traces, spans = _traffic(rng, now, days)
    store.upsert("traces", traces)
    store.upsert("spans", spans)

    dataset_id, items = _dataset(now)
    store.upsert("datasets", [_dataset_row(dataset_id, now)])
    store.upsert("dataset_items", items)

    # Its own generator, so tuning the traffic above cannot quietly move the
    # scores below and turn the regression this seeds into a rounding error.
    experiments, results = _experiments(
        random.Random(rng_seed + 1), dataset_id, items, now
    )
    store.upsert("experiments", experiments)
    store.upsert("experiment_results", results)

    audits, claims = _audits(now, traces)
    store.upsert("faithfulness_audits", audits)
    store.upsert("audit_claims", claims)

    return {
        "traces": len(traces),
        "spans": len(spans),
        "datasets": 1,
        "dataset_items": len(items),
        "experiments": len(experiments),
        "audits": len(audits),
    }


def _traffic(
    rng: random.Random, now: datetime.datetime, days: int
) -> Tuple[List[dict], List[dict]]:
    """A week of pipeline runs, busiest mid-week, with a bad afternoon in it."""
    traces: List[dict] = []
    spans: List[dict] = []

    for day in range(days - 1, -1, -1):
        midnight = (now - datetime.timedelta(days=day)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # A hump in the middle of the week, and today is only part-way through.
        volume = int(55 + 65 * (1 - abs(day - 3) / 3.5))
        if day == 0:
            volume = int(volume * now.hour / 24) or 6

        # One afternoon the retriever came back empty and generation fell over.
        broken_hours = {16, 17} if day == 2 else set()

        for _ in range(volume):
            started = midnight + datetime.timedelta(
                seconds=rng.randrange(6 * 3600, 23 * 3600)
            )
            failing = started.hour in broken_hours and rng.random() < 0.55
            trace_id = _identifier()
            question = rng.choice(QUESTIONS)
            latency = 0.0
            trace_spans: List[dict] = []

            for name, kind, share in PIPELINE:
                budget = rng.uniform(0.24, 1.25) * share
                span_failed = failing and name in ("generate", "classify-intent")
                span = _span(rng, trace_id, name, kind, started, latency, budget, question)
                if span_failed:
                    span["status"] = "error"
                    span["output"] = None
                    span["error"] = (
                        "LookupError: no context retrieved"
                        if name == "generate"
                        else f"LookupError: no context retrieved for {question!r}"
                    )
                trace_spans.append(span)
                latency += budget

            traces.append(
                {
                    "id": trace_id,
                    "name": "rag-pipeline",
                    "start_time": started,
                    "end_time": started + datetime.timedelta(seconds=latency),
                    "status": "error" if failing else "ok",
                    "tags": ["demo"],
                    "metadata": {"question": question},
                }
            )
            spans.extend(trace_spans)

    return traces, spans


def _span(
    rng: random.Random,
    trace_id: str,
    name: str,
    kind: str,
    started: datetime.datetime,
    offset: float,
    budget: float,
    question: str,
) -> dict:
    begin = started + datetime.timedelta(seconds=offset)
    span = {
        "id": _identifier(),
        "trace_id": trace_id,
        "parent_span_id": None,
        "name": name,
        "type": kind,
        "start_time": begin,
        "end_time": begin + datetime.timedelta(seconds=budget),
        "status": "ok",
        "input": {"question": question},
        "output": {"passages": list(PASSAGES[:2])} if kind == "retrieval" else ANSWER,
        "error": None,
        "tags": [],
        "metadata": {},
    }
    if kind == "llm":
        model, prompt_rate, completion_rate = MODELS[rng.randrange(len(MODELS))]
        if name == "classify-intent":
            prompt, completion = rng.randrange(40, 90), rng.randrange(1, 6)
        else:
            prompt, completion = rng.randrange(700, 1600), rng.randrange(90, 320)
        span.update(
            {
                "model": model,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "estimated_cost_usd": prompt * prompt_rate + completion * completion_rate,
            }
        )
    return span


def _dataset_row(dataset_id: str, now: datetime.datetime) -> dict:
    return {
        "id": dataset_id,
        "name": "returns-policy",
        "description": "Questions a support bot gets about the returns policy.",
        "created_at": now - datetime.timedelta(days=6),
        "metadata": {"source": "demo"},
    }


def _dataset(now: datetime.datetime) -> Tuple[str, List[dict]]:
    dataset_id = _identifier()
    created = now - datetime.timedelta(days=6)
    expected = (
        "To the original payment method, within 30 days.",
        "No - returns after 30 days are refunded as store credit.",
        "30 days from delivery.",
        "No, shipping is refunded on damaged items.",
        "No, opened software cannot be returned.",
        "Within 30 days of the return being accepted.",
    )
    items = [
        {
            "id": _identifier(),
            "dataset_id": dataset_id,
            "input": {"question": question},
            "expected_output": {"answer": answer},
            "metadata": {},
            "created_at": created,
        }
        for question, answer in zip(QUESTIONS, expected)
    ]
    return dataset_id, items


def _experiments(
    rng: random.Random, dataset_id: str, items: List[dict], now: datetime.datetime
) -> Tuple[List[dict], List[dict]]:
    """Three runs: a baseline, a better prompt, and a cheaper model that regressed.

    The third exists so `evalforge eval gate` has something to fail on, and so the
    comparison view has a red delta in it the first time anyone opens it.
    """
    runs = (
        ("rag-v1", 5, {"faithfulness": 0.74, "answer_relevance": 0.82}),
        ("rag-v2-prompt", 3, {"faithfulness": 0.87, "answer_relevance": 0.89}),
        ("rag-v3-cheap-model", 1, {"faithfulness": 0.55, "answer_relevance": 0.71}),
    )
    experiments, results = [], []
    for name, days_ago, centres in runs:
        created = now - datetime.timedelta(days=days_ago)
        experiment_id = _identifier()
        experiments.append(
            {
                "id": experiment_id,
                "name": name,
                "dataset_id": dataset_id,
                "created_at": created,
                "metadata": {"model": "gpt-4o-mini", "source": "demo"},
            }
        )
        for item in items:
            results.append(
                {
                    "id": _identifier(),
                    "experiment_id": experiment_id,
                    "dataset_item_id": item["id"],
                    "trace_id": None,
                    "output": {"answer": ANSWER},
                    "scores": {
                        metric: {
                            "metric_name": metric,
                            "value": round(min(1.0, max(0.0, rng.gauss(centre, 0.08))), 2),
                            "higher_is_better": True,
                            "reason": "replayed from a fixture",
                        }
                        for metric, centre in centres.items()
                    },
                    "latency_ms": round(rng.uniform(700, 2400), 1),
                    "error": None,
                    "created_at": created,
                }
            )
    return experiments, results


def _audits(
    now: datetime.datetime, traces: List[dict]
) -> Tuple[List[dict], List[dict]]:
    """Three saved reports, including the one where the bot invented a fee."""
    reports = (
        (
            "How are refunds issued?",
            "Refunds go back to the original card; store credit can be converted to "
            "cash and an 8% restocking fee applies.",
            0.58,
            (
                ("A restocking fee of 8% applies to opened boxes.", "CONTRADICTED", 3),
                ("Store credit can be converted to cash.", "UNSUPPORTED", 2),
                ("Processing takes 5-7 business days.", "PARTIALLY_SUPPORTED", 1),
                ("Refunds are issued to the original payment method.", "SUPPORTED", 0),
                ("Refunds are available within 30 days.", "SUPPORTED", 0),
                ("Shipping fees are refunded for damaged items.", "SUPPORTED", 0),
            ),
        ),
        (
            "Can store credit become cash?",
            "Store credit cannot be converted to cash, and refunds after 30 days are "
            "issued as credit.",
            0.75,
            (
                ("Store credit expires after one year.", "UNSUPPORTED", 2),
                ("Store credit cannot be converted to cash.", "SUPPORTED", 0),
                ("Late returns are refunded as store credit.", "SUPPORTED", 0),
            ),
        ),
        (
            "What is the refund window?",
            "Refunds are issued within 30 days to the original payment method.",
            0.92,
            (
                ("Refunds are issued within 30 days.", "SUPPORTED", 0),
                ("Refunds go to the original payment method.", "SUPPORTED", 0),
            ),
        ),
    )

    audits, claims = [], []
    for offset, (question, answer, score, verdicts) in enumerate(reports):
        audit_id = _identifier()
        trace_id = traces[-(offset + 1)]["id"] if traces else None
        audits.append(
            {
                "id": audit_id,
                "trace_id": trace_id,
                "span_id": None,
                "query": question,
                "answer": answer,
                "context": list(PASSAGES[:2]),
                "score": score,
                "claim_count": len(verdicts),
                "unsupported": sum(1 for _, v, _ in verdicts if v == "UNSUPPORTED"),
                "contradicted": sum(1 for _, v, _ in verdicts if v == "CONTRADICTED"),
                "model": "gpt-4o-mini",
                "created_at": now - datetime.timedelta(hours=9 + offset),
            }
        )
        for position, (claim, verdict, severity) in enumerate(verdicts):
            claims.append(
                {
                    "id": _identifier(),
                    "audit_id": audit_id,
                    "position": position,
                    "claim": claim,
                    "verdict": verdict,
                    "severity": severity,
                    "evidence": [0] if severity in (0, 1, 3) else [],
                    "rationale": (
                        "passage states this" if verdict == "SUPPORTED"
                        else "context is silent or disagrees"
                    ),
                }
            )
    return audits, claims


def _identifier() -> str:
    return uuid.uuid4().hex
