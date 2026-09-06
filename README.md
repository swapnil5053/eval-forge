# EvalForge

**Local-first LLM evaluation.** Trace your pipeline with a decorator, evaluate it with
LLM-as-a-judge metrics, and audit RAG answers claim by claim — from one `pip install`,
against a single DuckDB file. No server, no account, no cloud.

`Python 3.10+` · `Apache-2.0` · `189 tests` · [landing page](docs/index.html)

![EvalForge landing page](docs/screenshots/landing.png)

---

## Why this exists

Opik and Langfuse are excellent *team platforms*: multi-tenant, horizontally scalable,
a dozen services. The cost of that architecture is paid at install time by every user —
including the solo developer who wants to trace one RAG pipeline on a laptop.

EvalForge takes the opposite position: **one language, one process, one file on disk.**
It accepts the limits that follow — single user, single node, no production online
scoring — and in exchange install is `pip install evalforge`, your traces are a portable
file you can query with plain SQL, and there is nothing to deploy.

## Quick start

```bash
pip install evalforge && evalforge init
```

```python
from evalforge import trace

@trace(name="retrieve", type="retrieval")
def retrieve(question: str) -> list[str]:
    return vector_store.search(question)

@trace
def generate(question: str, context: list[str]):
    return client.chat.completions.create(...)

@trace(name="rag-pipeline")
def answer(question: str):
    return generate(question, retrieve(question))
```

```bash
evalforge ingest       # load spooled traces into DuckDB
evalforge trace stats  # volume, p50/p95/p99, error rate, tokens, spend
evalforge serve        # the dashboard, on localhost:8000
```

Or skip the tooling entirely — it is just a file:

```bash
duckdb ~/.evalforge/evalforge.db "SELECT name, model, estimated_cost_usd FROM spans"
```

## Claim-level faithfulness auditing

A faithfulness score of 0.58 tells you an answer is partly ungrounded. It does not tell
you **which part**. EvalForge decomposes the answer into individual claims and checks
each one against the passages that were actually retrieved:

![Claim-level audit report](docs/screenshots/audit.png)

Claims are ranked by severity — a contradiction outranks a gap, because the context was
there and the answer went against it. Two judge calls per audit: one to decompose, one
to classify. This is the part with no upstream equivalent.

```bash
evalforge audit run 1b4343ea
```

## Evaluate

Metrics are plain functions. No base class, no `.score()` method, no registry object —
your own metric is any function with the same shape, and the runner passes each one only
the arguments its signature declares.

```python
from evalforge import evaluate
from evalforge.eval.metrics import faithfulness, hallucination

results = evaluate(
    dataset="my_rag_dataset",
    task=my_rag_pipeline,
    metrics=[faithfulness, hallucination],
    num_workers=4,
    name="rag-v2",
)
```

Ships with `hallucination`, `faithfulness`, `answer_relevance`, `context_precision`,
`context_recall`, `toxicity`, `coherence` and `conciseness`. The judge runs through
LiteLLM, so any provider works — including a local Ollama, which keeps the loop offline.

## Query it from Claude or Cursor

```bash
evalforge mcp install   # prints the client config block
```

Exposes `list_traces`, `get_trace`, `get_trace_stats`, `search_traces`,
`list_experiments`, `get_experiment` and `run_faithfulness_audit` over MCP.

## Four decisions worth explaining

**Spool, not a socket.** DuckDB allows one writer, so the traced application never opens
it. `@trace` appends NDJSON to a per-process file; whichever process runs ingestion owns
the database. Nothing blocks your app, two processes can be traced at once, and traces
recorded while nothing is ingesting simply wait. Files being written end in
`.ndjson.active` and are renamed once sealed, so the ingester never reads a half-written
line; one abandoned by a crashed process is adopted after five minutes.

**Every score declares its polarity.** Scores run 0–1, but `hallucination` and `toxicity`
are *bad* when high. Mixed polarity is fine in isolation and poison in a dashboard, so
every `Score` carries `higher_is_better` and every consumer reads it. Nothing in the
codebase hard-codes "low is bad".

**Timestamps cross the boundary as numbers.** Reading a `TIMESTAMPTZ` makes DuckDB
require `pytz`, which the base install does not carry — a dependency for a formatting
concern. Timestamps come back as epoch milliseconds and are rebuilt as UTC in Python.

**Costs are attributed once.** A function that returns its child's LLM response would
otherwise have those tokens counted twice. Each priced response is fingerprinted by
identity *and* usage, so a pass-through wrapper stays at zero and only the call that
made the request carries the cost.

## Architecture

```
@trace  →  ~/.evalforge/spool/*.ndjson  →  ingest  →  evalforge.db  →  CLI · dashboard · MCP

src/evalforge/
├── core/       @trace, contextvar span stack, spool writer, cost estimation
├── storage/    DuckDB, numbered SQL migrations, the analytical query layer
├── eval/       judge, metrics, datasets, experiment runner, faithfulness audit,
│               SHAP / occlusion token attribution
├── dashboard/  Reflex panel — all styling flows from one styles.py
├── mcp/        the MCP server
└── cli/        init · ingest · status · trace · eval · audit · serve · mcp
```

The dashboard opens DuckDB **read-only**, so it keeps working while an evaluation holds
the write lock. `docs/index.html` is the landing page — self-contained, no build step;
point GitHub Pages at `docs/` to publish it.

## Install options

| Extra | Adds |
|---|---|
| `evalforge` | tracing, storage, CLI |
| `evalforge[eval]` | LiteLLM — judge metrics and cost estimation |
| `evalforge[dashboard]` | Reflex dashboard |
| `evalforge[mcp]` | MCP server |
| `evalforge[attribution]` | SHAP token attribution |
| `evalforge[all]` | everything |

## Docker

```bash
docker compose up --build
```

Single container, embedded DuckDB, data on a named volume, non-root, health-checked.
The dashboard builds its frontend on first launch, which needs network access once.

## Development

```bash
pip install -e ".[all]"
python -m pytest                    # 189 tests
python examples/rag_pipeline.py && evalforge ingest && evalforge trace stats
```

## Attribution

Derived from [Opik](https://github.com/comet-ml/opik) by Comet ML (Apache-2.0). The
tracing decorator pattern, context propagation model and judge prompt rubrics are adapted
from their Python SDK — roughly 25–30k lines of it. The other ~90% of Opik (a 219k-line
Java service, ~1,900 React/TS files, an 89.5k-line generated REST client, a 15-container
compose stack) was not carried over; the storage layer, dashboard, faithfulness audit,
attribution module, MCP server and CLI were built independently.

See [ATTRIBUTION.md](ATTRIBUTION.md) for the full breakdown. Licensed Apache-2.0.
