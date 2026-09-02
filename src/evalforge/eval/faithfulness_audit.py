"""Claim-level faithfulness auditing.

A faithfulness score of 0.62 tells you an answer is partly ungrounded but not
which part. This module decomposes an answer into individual claims, checks each
one against the retrieved context, and returns the claims that failed with the
evidence that was supposed to support them.

Two judge calls per audit: one to decompose, one to classify all claims at once.
"""

import dataclasses
import datetime
import json
import logging
from typing import Any, List, Optional, Sequence

from ..core.models import new_id, utcnow
from ..storage import queries
from ..storage.duckdb_store import Store
from . import judge

LOGGER = logging.getLogger(__name__)

SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
CONTRADICTED = "CONTRADICTED"

# How much of a claim's faithfulness each verdict is worth, and how loudly it
# should complain. A contradiction is worse than a gap: the context was there and
# the answer went against it.
VERDICT_CREDIT = {
    SUPPORTED: 1.0,
    PARTIALLY_SUPPORTED: 0.5,
    UNSUPPORTED: 0.0,
    CONTRADICTED: 0.0,
}
VERDICT_SEVERITY = {
    SUPPORTED: 0,
    PARTIALLY_SUPPORTED: 1,
    UNSUPPORTED: 2,
    CONTRADICTED: 3,
}

_DECOMPOSE_SYSTEM = """You split an answer into the individual factual claims it makes.

Rules:
1. One self-contained claim per item, in the answer's own words where possible.
2. Resolve pronouns so each claim stands alone.
3. Skip questions, greetings, hedges and anything that asserts nothing.
4. Do not merge two facts into one claim, and do not invent claims.

Answer with a single JSON object and nothing else:
{"claims": ["<claim>", "<claim>"]}"""

_CLASSIFY_SYSTEM = """You check each claim against numbered context passages.

For every claim assign exactly one verdict:
- SUPPORTED: the context states or directly entails the claim.
- PARTIALLY_SUPPORTED: the context supports part of the claim, or supports it with
  less specificity than the claim asserts.
- UNSUPPORTED: the context neither supports nor contradicts the claim. Say this for
  anything the context is simply silent about, however plausible it sounds.
- CONTRADICTED: the context states something incompatible with the claim.

Cite the passage numbers you relied on. Cite none for UNSUPPORTED.

Answer with a single JSON object and nothing else:
{"verdicts": [{"index": <claim number>, "verdict": "<verdict>",
               "evidence": [<passage numbers>], "rationale": "<one sentence>"}]}"""


@dataclasses.dataclass
class ClaimVerdict:
    claim: str
    verdict: str
    evidence: List[int] = dataclasses.field(default_factory=list)
    rationale: str = ""

    @property
    def severity(self) -> int:
        return VERDICT_SEVERITY[self.verdict]

    @property
    def credit(self) -> float:
        return VERDICT_CREDIT[self.verdict]


@dataclasses.dataclass
class FaithfulnessAudit:
    id: str
    query: str
    answer: str
    context: List[str]
    claims: List[ClaimVerdict]
    model: str
    created_at: datetime.datetime
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

    @property
    def score(self) -> float:
        """Mean credit across claims. An answer with no claims is vacuously faithful."""
        if not self.claims:
            return 1.0
        return sum(claim.credit for claim in self.claims) / len(self.claims)

    @property
    def problems(self) -> List[ClaimVerdict]:
        """Claims that are not fully supported, worst first."""
        return sorted(
            (claim for claim in self.claims if claim.severity > 0),
            key=lambda claim: claim.severity,
            reverse=True,
        )

    def count(self, verdict: str) -> int:
        return sum(1 for claim in self.claims if claim.verdict == verdict)

    def evidence_for(self, claim: ClaimVerdict) -> List[str]:
        return [self.context[index] for index in claim.evidence if 0 <= index < len(self.context)]


def audit(
    query: str,
    answer: str,
    context: Sequence[str],
    model: str = judge.DEFAULT_MODEL,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
) -> FaithfulnessAudit:
    """Decompose an answer into claims and check each against the context."""
    claims = decompose(answer, model=model)
    verdicts = classify(claims, context, model=model) if claims else []
    return FaithfulnessAudit(
        id=new_id(),
        query=query,
        answer=answer,
        context=list(context),
        claims=verdicts,
        model=model,
        created_at=utcnow(),
        trace_id=trace_id,
        span_id=span_id,
    )


def decompose(answer: str, model: str = judge.DEFAULT_MODEL) -> List[str]:
    payload = judge.judge_json(
        _DECOMPOSE_SYSTEM, f"ANSWER:\n{answer}", model=model, required=["claims"]
    )
    claims = payload["claims"]
    if not isinstance(claims, list):
        raise judge.JudgeError(f"expected a list of claims, got {type(claims).__name__}")
    return [str(claim).strip() for claim in claims if str(claim).strip()]


def classify(
    claims: Sequence[str], context: Sequence[str], model: str = judge.DEFAULT_MODEL
) -> List[ClaimVerdict]:
    passages = "\n".join(f"[{index}] {passage}" for index, passage in enumerate(context))
    numbered = "\n".join(f"{index}. {claim}" for index, claim in enumerate(claims))
    payload = judge.judge_json(
        _CLASSIFY_SYSTEM,
        f"CONTEXT PASSAGES:\n{passages or '(none)'}\n\nCLAIMS:\n{numbered}",
        model=model,
        required=["verdicts"],
    )

    by_index = {}
    for entry in payload["verdicts"]:
        if not isinstance(entry, dict):
            LOGGER.debug("ignoring malformed verdict entry: %r", entry)
            continue
        index = _as_index(entry.get("index"))
        if index is None or not 0 <= index < len(claims):
            LOGGER.debug("ignoring verdict for out-of-range claim %r", entry.get("index"))
            continue
        by_index[index] = entry

    return [
        _verdict(claim, by_index.get(index), len(context))
        for index, claim in enumerate(claims)
    ]


def _verdict(claim: str, entry: Optional[dict], context_length: int) -> ClaimVerdict:
    if entry is None:
        return ClaimVerdict(
            claim=claim,
            verdict=UNSUPPORTED,
            rationale="the judge returned no verdict for this claim",
        )

    verdict = str(entry.get("verdict", "")).strip().upper()
    if verdict not in VERDICT_CREDIT:
        LOGGER.debug("unrecognised verdict %r, recording as %s", verdict, UNSUPPORTED)
        verdict = UNSUPPORTED

    evidence = [
        index
        for index in (_as_index(value) for value in entry.get("evidence") or [])
        if index is not None and 0 <= index < context_length
    ]
    return ClaimVerdict(
        claim=claim,
        verdict=verdict,
        evidence=evidence if verdict != UNSUPPORTED else [],
        rationale=str(entry.get("rationale", "")).strip(),
    )


def _as_index(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def audit_trace(
    store: Store, trace_id: str, model: str = judge.DEFAULT_MODEL
) -> FaithfulnessAudit:
    """Audit a recorded RAG trace. ``trace_id`` may be an id prefix."""
    row, spans = queries.trace_detail(store, trace_id)
    if row is None:
        raise LookupError(f"no trace matching {trace_id!r}")

    query, context, answer, span_id = extract_rag(spans)
    return audit(
        query=query,
        answer=answer,
        context=context,
        model=model,
        trace_id=row.id,
        span_id=span_id,
    )


def extract_rag(spans: Sequence[queries.SpanRow]) -> tuple:
    """Pull (query, context, answer, answering span id) out of a trace's spans.

    The convention is the one a RAG pipeline falls into naturally: the root span's
    input holds the question, a span of type ``retrieval`` returns the passages, and
    a span of type ``llm`` returns the answer.
    """
    roots = [span for span in spans if span.parent_span_id is None]
    retrieval = [span for span in spans if span.type == "retrieval"]
    generation = [span for span in spans if span.type == "llm"]

    missing = []
    if not roots:
        missing.append("a root span carrying the question")
    if not retrieval:
        missing.append("a span of type 'retrieval' returning the context")
    if not generation:
        missing.append("a span of type 'llm' returning the answer")
    if missing:
        raise ValueError(
            "this trace cannot be audited as RAG: it is missing " + ", ".join(missing)
        )

    context = _as_passages(retrieval[-1].output)
    if not context:
        raise ValueError(
            f"the retrieval span {retrieval[-1].name!r} returned no usable context"
        )

    answer = _as_text(generation[-1].output)
    if not answer:
        raise ValueError(
            f"the llm span {generation[-1].name!r} returned no usable answer text"
        )

    return _as_text(roots[0].input), context, answer, generation[-1].id


def save(store: Store, audit_result: FaithfulnessAudit) -> None:
    """Persist an audit and its claims."""
    store.upsert(
        "faithfulness_audits",
        [
            {
                "id": audit_result.id,
                "trace_id": audit_result.trace_id,
                "span_id": audit_result.span_id,
                "query": audit_result.query,
                "answer": audit_result.answer,
                "context": audit_result.context,
                "score": audit_result.score,
                "claim_count": len(audit_result.claims),
                "unsupported": audit_result.count(UNSUPPORTED),
                "contradicted": audit_result.count(CONTRADICTED),
                "model": audit_result.model,
                "created_at": audit_result.created_at,
            }
        ]
    )
    store.upsert(
        "audit_claims",
        [
            {
                "id": new_id(),
                "audit_id": audit_result.id,
                "position": position,
                "claim": claim.claim,
                "verdict": claim.verdict,
                "severity": claim.severity,
                "evidence": claim.evidence,
                "rationale": claim.rationale,
            }
            for position, claim in enumerate(audit_result.claims)
        ]
    )


def load(store: Store, audit_id: str) -> Optional[FaithfulnessAudit]:
    """Read back a saved audit. ``audit_id`` may be an id prefix."""
    rows = store.db.execute(
        """
        SELECT id, trace_id, span_id, query, answer, context, model,
               epoch_ms(created_at)
        FROM faithfulness_audits WHERE id LIKE ? LIMIT 2
        """,
        [f"{audit_id}%"],
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise ValueError(f"audit id prefix {audit_id!r} matches more than one audit")

    identifier, trace_id, span_id, query, answer, context, model, created_ms = rows[0]
    claims = store.db.execute(
        """
        SELECT claim, verdict, evidence, rationale
        FROM audit_claims WHERE audit_id = ? ORDER BY position
        """,
        [identifier],
    ).fetchall()

    return FaithfulnessAudit(
        id=identifier,
        query=query,
        answer=answer,
        context=json.loads(context) if context else [],
        claims=[
            ClaimVerdict(
                claim=claim,
                verdict=verdict,
                evidence=json.loads(evidence) if evidence else [],
                rationale=rationale or "",
            )
            for claim, verdict, evidence, rationale in claims
        ],
        model=model,
        created_at=queries.moment(created_ms),
        trace_id=trace_id,
        span_id=span_id,
    )


def recent(store: Store, limit: int = 20) -> List[dict]:
    """Saved audits, newest first, as plain dicts for listing."""
    rows = store.db.execute(
        """
        SELECT id, trace_id, query, score, claim_count, unsupported, contradicted,
               epoch_ms(created_at)
        FROM faithfulness_audits ORDER BY created_at DESC LIMIT ?
        """,
        [limit],
    ).fetchall()
    columns = (
        "id", "trace_id", "query", "score", "claim_count",
        "unsupported", "contradicted", "created_at",
    )
    return [
        dict(zip(columns, row[:-1] + (queries.moment(row[-1]),))) for row in rows
    ]


def _as_passages(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key in ("context", "contexts", "passages", "documents", "output"):
            if key in value:
                return _as_passages(value[key])
        return []
    if isinstance(value, (list, tuple)):
        return [_as_text(item) for item in value if _as_text(item)]
    return [str(value)]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        choices = value.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict) and message.get("content"):
                return str(message["content"])
        for key in ("answer", "output", "text", "content", "question", "query", "input"):
            if value.get(key):
                return _as_text(value[key])
        if len(value) == 1:
            return _as_text(next(iter(value.values())))
        return ""
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return _as_text(value[0])
    return str(value)
