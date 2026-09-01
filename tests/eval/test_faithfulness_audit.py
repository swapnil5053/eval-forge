import pytest

from evalforge import trace
from evalforge.core import spool
from evalforge.eval import faithfulness_audit as fa
from evalforge.storage.duckdb_store import Store
from evalforge.storage.ingest import ingest_once

CONTEXT = [
    "Paris has been the capital of France since 987.",
    "The Eiffel Tower opened in 1889.",
]


def script(judge_stub, claims, verdicts):
    judge_stub.script = [
        ("You split an answer", {"claims": claims}),
        ("You check each claim", {"verdicts": verdicts}),
    ]


@pytest.fixture
def audited(judge_stub):
    script(
        judge_stub,
        ["Paris is the capital of France.", "The Eiffel Tower opened in 1898.",
         "France has 70 million people."],
        [
            {"index": 0, "verdict": "SUPPORTED", "evidence": [0], "rationale": "passage 0 says so"},
            {"index": 1, "verdict": "CONTRADICTED", "evidence": [1], "rationale": "1889, not 1898"},
            {"index": 2, "verdict": "UNSUPPORTED", "evidence": [], "rationale": "not mentioned"},
        ],
    )
    return fa.audit("What is the capital of France?", "an answer", CONTEXT)


def test_claims_are_classified(audited):
    assert [claim.verdict for claim in audited.claims] == [
        fa.SUPPORTED,
        fa.CONTRADICTED,
        fa.UNSUPPORTED,
    ]


def test_score_is_the_mean_credit(audited):
    assert audited.score == pytest.approx(1 / 3)


def test_problems_are_ranked_worst_first(audited):
    assert [claim.verdict for claim in audited.problems] == [fa.CONTRADICTED, fa.UNSUPPORTED]


def test_evidence_maps_back_to_passages(audited):
    contradiction = audited.problems[0]
    assert audited.evidence_for(contradiction) == [CONTEXT[1]]


def test_partial_support_scores_half(judge_stub):
    script(
        judge_stub,
        ["Paris is a European capital."],
        [{"index": 0, "verdict": "PARTIALLY_SUPPORTED", "evidence": [0], "rationale": "vaguer"}],
    )
    assert fa.audit("q", "a", CONTEXT).score == 0.5


def test_an_answer_with_no_claims_is_vacuously_faithful(judge_stub):
    judge_stub.script = [("You split an answer", {"claims": []})]
    result = fa.audit("q", "Hello!", CONTEXT)
    assert result.claims == []
    assert result.score == 1.0


def test_a_claim_the_judge_skipped_is_unsupported(judge_stub):
    script(judge_stub, ["first", "second"], [{"index": 0, "verdict": "SUPPORTED", "evidence": [0]}])
    result = fa.audit("q", "a", CONTEXT)

    assert result.claims[1].verdict == fa.UNSUPPORTED
    assert "no verdict" in result.claims[1].rationale


def test_an_unrecognised_verdict_becomes_unsupported(judge_stub):
    script(judge_stub, ["first"], [{"index": 0, "verdict": "probably fine", "evidence": [0]}])
    assert fa.audit("q", "a", CONTEXT).claims[0].verdict == fa.UNSUPPORTED


def test_out_of_range_evidence_is_dropped(judge_stub):
    script(judge_stub, ["first"], [{"index": 0, "verdict": "SUPPORTED", "evidence": [0, 9, "x"]}])
    assert fa.audit("q", "a", CONTEXT).claims[0].evidence == [0]


def test_verdicts_for_claims_that_do_not_exist_are_ignored(judge_stub):
    script(judge_stub, ["first"], [{"index": 4, "verdict": "SUPPORTED", "evidence": []}])
    assert len(fa.audit("q", "a", CONTEXT).claims) == 1


def test_extract_rag_reads_the_conventional_spans():
    spans = [
        _span("root", None, "general", {"question": "capital of France?"}, None),
        _span("retrieve", "root", "retrieval", None, CONTEXT),
        _span(
            "generate",
            "root",
            "llm",
            None,
            {"choices": [{"message": {"content": "Paris."}}]},
        ),
    ]

    query, context, answer, span_id = fa.extract_rag(spans)

    assert query == "capital of France?"
    assert context == CONTEXT
    assert answer == "Paris."
    assert span_id == "generate"


def test_extract_rag_explains_what_is_missing():
    spans = [_span("root", None, "general", {"question": "q"}, "answer")]
    with pytest.raises(ValueError, match="missing .*span of type 'retrieval'"):
        fa.extract_rag(spans)


def test_extract_rag_rejects_an_empty_retrieval():
    spans = [
        _span("root", None, "general", {"question": "q"}, None),
        _span("retrieve", "root", "retrieval", None, []),
        _span("generate", "root", "llm", None, "Paris."),
    ]
    with pytest.raises(ValueError, match="no usable context"):
        fa.extract_rag(spans)


def test_save_and_load_round_trip(tmp_path, audited):
    with Store(tmp_path / "evalforge.db") as store:
        fa.save(store, audited)
        loaded = fa.load(store, audited.id[:8])

        assert loaded.score == pytest.approx(audited.score)
        assert [claim.verdict for claim in loaded.claims] == [
            claim.verdict for claim in audited.claims
        ]
        assert loaded.context == CONTEXT
        assert loaded.evidence_for(loaded.problems[0]) == [CONTEXT[1]]

        listed = fa.recent(store)
        assert listed[0]["contradicted"] == 1
        assert listed[0]["claim_count"] == 3


def test_load_returns_none_for_an_unknown_id(tmp_path):
    with Store(tmp_path / "evalforge.db") as store:
        assert fa.load(store, "deadbeef") is None


def test_audit_trace_end_to_end(tmp_path, judge_stub):
    writer = spool.SpoolWriter(tmp_path / "spool")
    spool.set_writer(writer)
    try:

        @trace(name="retrieve", type="retrieval")
        def retrieve(question):
            return CONTEXT

        @trace(name="generate", type="llm")
        def generate(question, context):
            return {"choices": [{"message": {"content": "Paris, since 987."}}]}

        @trace(name="rag")
        def answer(question):
            return generate(question, retrieve(question))

        answer("What is the capital of France?")
    finally:
        writer.close()
        spool.set_writer(None)

    script(
        judge_stub,
        ["Paris is the capital of France since 987."],
        [{"index": 0, "verdict": "SUPPORTED", "evidence": [0], "rationale": "passage 0"}],
    )

    with Store(tmp_path / "evalforge.db") as store:
        ingest_once(store, tmp_path / "spool")
        trace_id = store.db.execute("SELECT id FROM traces").fetchone()[0]

        result = fa.audit_trace(store, trace_id[:8])

        assert result.trace_id == trace_id
        assert result.score == 1.0
        assert result.context == CONTEXT
        assert "Paris" in result.answer

        fa.save(store, result)
        assert store.count("audit_claims") == 1


def test_audit_trace_reports_a_missing_trace(tmp_path):
    with Store(tmp_path / "evalforge.db") as store:
        with pytest.raises(LookupError, match="no trace matching"):
            fa.audit_trace(store, "nope")


def _span(identifier, parent, span_type, span_input, span_output):
    from evalforge.storage.queries import SpanRow

    return SpanRow(
        id=identifier,
        trace_id="t1",
        parent_span_id=parent,
        name=identifier,
        type=span_type,
        status="ok",
        start_time=None,
        latency_ms=1.0,
        input=span_input,
        output=span_output,
        error=None,
        model=None,
        prompt_tokens=None,
        completion_tokens=None,
        cost_usd=None,
    )
