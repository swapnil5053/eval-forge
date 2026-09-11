# EvalForge

A local toolkit for **tracing, evaluating, and debugging LLM application pipelines**.
It records function calls and model usage into a local DuckDB database, compares runs, and
inspects RAG answers at the claim level. No server, account, or hosted backend.

[![ci](https://github.com/swapnil5053/eval-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/swapnil5053/eval-forge/actions/workflows/ci.yml)

**Python 3.10+ · 6.9k lines · 216 tests · DuckDB · Apache-2.0** · [Landing page](https://swapnil5053.github.io/eval-forge/)

![EvalForge](docs/screenshots/landing.png)

## Try it without writing any code

```bash
pip install "evalforge[dashboard]"
evalforge demo
```

Seeds a week of sample traffic and opens the dashboard with every page populated — traces,
an afternoon of failures, three experiments, a dataset, three claim-level audits. Nothing
calls a model, so no API key is needed, and the seed is fixed.

## Trace

```python
from evalforge import trace

@trace(name="retrieve", type="retrieval")
def retrieve(question: str):
    return vector_store.search(question)

@trace
def generate(question: str, context: list[str]):
    return client.chat.completions.create(...)

@trace(name="pipeline")
def answer(question: str):
    return generate(question, retrieve(question))
```

```bash
evalforge ingest       # load the spool into DuckDB
evalforge trace stats  # volume, p50/p95/p99, error rate, tokens, spend
evalforge serve        # the dashboard, on localhost:8000
```

Everything lands in `~/.evalforge/` — a `spool/` directory and one `evalforge.db`. It is
plain DuckDB, so you can skip the tooling entirely:

```bash
duckdb ~/.evalforge/evalforge.db "SELECT name, model, estimated_cost_usd FROM spans"
```

## Evaluate

Metrics are regular Python functions, not objects with a required interface — the runner
inspects each signature and passes only the arguments it asks for, so your own metric is
written exactly like a built-in one.

```python
from evalforge import evaluate
from evalforge.eval.metrics import faithfulness, hallucination

results = evaluate(
    dataset="my_dataset",
    task=my_pipeline,
    metrics=[faithfulness, hallucination],
    num_workers=4,
    name="rag-v2",
)
```

Ships with `faithfulness`, `hallucination`, `answer_relevance`, `context_precision`,
`context_recall`, `toxicity`, `coherence` and `conciseness`. The judge runs through
LiteLLM, so any provider works — including a local Ollama, which keeps the loop offline.

### Failing a build on a regression

```bash
evalforge eval gate rag-v2 --baseline rag-v1 --max-drop 0.05
```

```text
metric            rag-v1  rag-v2   delta
faithfulness       0.810   0.740  -0.070  FAIL
hallucination      0.120   0.090  +0.030  ok

1 metric regressed past 0.050: faithfulness
```

Exits non-zero, so it can gate a pull request. Which direction counts as a regression comes
from each score's own polarity — hallucination rising fails for the same reason
faithfulness falling does.

## Claim-level RAG audit

A single faithfulness score does not show *which part* of an answer is wrong. The audit
splits the answer into claims and checks each against the context actually retrieved.

![Claim-level audit](docs/screenshots/audit.png)

```bash
evalforge audit run 1b4343ea
```

Every claim gets one of four verdicts — `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`,
`CONTRADICTED` — ranked by severity, with a contradiction treated as worse than missing
evidence: the context was there and the answer went against it. Two model calls per audit,
one to extract the claims and one to classify them.

## Architecture

```text
@trace → ~/.evalforge/spool/*.ndjson → ingest → evalforge.db → CLI · dashboard · MCP

src/evalforge/
├── core/       @trace, contextvar span stack, spool writer, cost estimation
├── storage/    DuckDB, numbered SQL migrations, the analytical query layer
├── eval/       judge, metrics, datasets, experiments, faithfulness audit, attribution
├── dashboard/  Reflex panel — all styling flows from one styles.py
├── mcp/        the MCP server
└── cli/        init · ingest · status · trace · eval · audit · demo · serve · mcp
```

The application never writes to DuckDB. `@trace` appends events to a per-process NDJSON
file and the ingester moves them in later, which keeps tracing off the hot path and stops
several processes competing for a write lock DuckDB grants to only one of them. The
dashboard and MCP server open the database read-only, so both keep working while an
evaluation holds that lock.

## Four decisions worth explaining

**Spool, not a socket.** A file being written ends in `.ndjson.active` and is renamed once
sealed, so the ingester never reads a half-written line; one abandoned by a crashed process
is adopted after a timeout.

**Every score declares its polarity.** Scores run 0–1, but `hallucination` and `toxicity`
are *bad* when high. Every `Score` carries `higher_is_better` and every consumer reads it,
so nothing in the codebase hard-codes "low is bad".

**Ingestion is batched, but not blindly.** Upserting spans one row at a time took 22
seconds for 2,400 of them; a few hundred rows per statement takes 0.4. The catch is that
DuckDB applies the conflict clause once per statement, so a span whose start and end land
in the same batch would keep the first write and silently drop the second — exactly the
merge the spool depends on. Batches are cut before any id they already hold.

**Costs are attributed once.** One model response can pass through several traced
functions. Each is fingerprinted by identity *and* usage, so a wrapper that returns its
child's response is not charged for tokens it did not request.

## Install options

| Extra | Includes |
| --- | --- |
| `evalforge` | Tracing, storage, CLI |
| `evalforge[eval]` | Judge metrics and cost estimation, via LiteLLM |
| `evalforge[dashboard]` | Reflex dashboard |
| `evalforge[mcp]` | MCP server |
| `evalforge[attribution]` | SHAP token attribution |
| `evalforge[all]` | Everything |

## Query it from Claude or Cursor

```bash
evalforge mcp install
```

Exposes `list_traces`, `get_trace`, `get_trace_stats`, `search_traces`, `list_experiments`,
`get_experiment` and `run_faithfulness_audit` over MCP.

## Docker

```bash
docker compose up --build
```

One container with the dashboard and embedded DuckDB, storage on a named volume, non-root,
health-checked.

## Development

```bash
pip install -e ".[all]"
python -m pytest        # 216 tests
ruff check src tests
```

CI runs the suite on Python 3.10, 3.11 and 3.12, lints, builds the Docker image, and
installs the built wheel into an empty environment to seed a demo database with it — the
only way to catch something missing from the package that tests importing from `src/`
cannot see.

`docs/index.html` is the landing page: one self-contained file, no build step. Open it
directly, or point GitHub Pages at `docs/`.

## Attribution

Derived in part from [Opik](https://github.com/comet-ml/opik) by Comet ML — the tracing
decorator pattern, context propagation model and judge prompt rubrics are adapted from
their Python SDK. The storage layer, dashboard, claim-level audit, attribution module, MCP
server and CLI were built independently. Full breakdown in [ATTRIBUTION.md](ATTRIBUTION.md).

Apache-2.0, inherited from Opik. See [LICENSE](LICENSE).
