# EvalForge

Local-first LLM evaluation. Trace a pipeline with one decorator, score it with
LLM-as-a-judge metrics, and audit RAG answers **claim by claim** — from a single
`pip install`, against a single DuckDB file. No server, no account, no cloud.

`Python 3.10+` · `6.4k lines` · `195 tests` · [landing page](https://swapnil5053.github.io/eval-forge/)

![EvalForge landing page](docs/screenshots/landing.png)

---

## What it does

| | |
|---|---|
| **Trace** | `@trace` on any function — nested spans, token counts, latency, per-call cost |
| **Store** | One DuckDB file. Numbered SQL migrations. Queryable with plain SQL |
| **Evaluate** | 8 judge metrics + your own plain functions, run concurrently over a dataset |
| **Audit** | Decompose an answer into claims, verify each against retrieved context |
| **Attribute** | SHAP / occlusion token attribution over judge scores |
| **Inspect** | Reflex dashboard, a `rich` CLI, and an MCP server for Claude or Cursor |

## Install

```bash
pip install evalforge && evalforge init
```

## Trace

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
evalforge serve        # dashboard on localhost:8000
```

Or skip the tooling — it is just a file:

```bash
duckdb ~/.evalforge/evalforge.db "SELECT name, model, estimated_cost_usd FROM spans"
```

## Claim-level faithfulness auditing

A faithfulness score of 0.58 says an answer is partly ungrounded. It does not say
**which part**. EvalForge decomposes the answer into individual claims and checks each
one against the passages actually retrieved.

![Claim-level audit report](docs/screenshots/audit.png)

```bash
evalforge audit run 1b4343ea
```

Claims are ranked by severity — a contradiction outranks a gap, because the context was
there and the answer went against it. Two judge calls per audit: one to decompose, one to
classify. No upstream equivalent.

## Evaluate

Metrics are plain functions. No base class, no `.score()` method, no registry object. Your
own metric is any function with the same shape; the runner passes each one only the
arguments its signature declares.

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

Built in: `hallucination`, `faithfulness`, `answer_relevance`, `context_precision`,
`context_recall`, `toxicity`, `coherence`, `conciseness`. The judge runs through LiteLLM,
so any provider works — including a local Ollama, which keeps the loop fully offline.

## Query it from Claude or Cursor

```bash
evalforge mcp install   # prints the client config block
```

Seven tools over MCP: `list_traces`, `get_trace`, `get_trace_stats`, `search_traces`,
`list_experiments`, `get_experiment`, `run_faithfulness_audit`.

## Engineering decisions

**Spool, not a socket.** DuckDB allows one writer, so the traced application never opens
it. `@trace` appends NDJSON to a per-process file; whichever process ingests owns the
database. Nothing blocks the app, two processes can be traced at once, and traces written
while nothing is ingesting simply wait. Open files end in `.ndjson.active` and are renamed
when sealed, so the ingester never reads a half-written line; one abandoned by a crashed
process is adopted after five minutes.

**Every score declares its polarity.** Scores run 0–1, but `hallucination` and `toxicity`
are *bad* when high. Mixed polarity is survivable in isolation and poison in a dashboard,
so every `Score` carries `higher_is_better` and every consumer reads it. Nothing in the
codebase hard-codes "low is bad".

**Timestamps cross the boundary as numbers.** Reading a `TIMESTAMPTZ` makes DuckDB require
`pytz` — a dependency for a formatting concern. Timestamps come back as epoch milliseconds
and are rebuilt as UTC in Python.

**Costs are attributed once.** A wrapper that returns its child's LLM response would
otherwise have those tokens counted twice. Each priced response is fingerprinted by
identity *and* usage, so a pass-through stays at zero and only the call that made the
request carries the cost.

## Architecture

```
@trace  →  ~/.evalforge/spool/*.ndjson  →  ingest  →  evalforge.db  →  CLI · dashboard · MCP
```

```
src/evalforge/
├── core/       @trace, contextvar span stack, spool writer, cost estimation
├── storage/    DuckDB, numbered SQL migrations, the analytical query layer
├── eval/       judge, metrics, datasets, experiment runner, faithfulness audit,
│               SHAP / occlusion token attribution
├── dashboard/  Reflex panel — all styling flows from one styles.py
├── mcp/        the MCP server
└── cli/        init · ingest · status · trace · eval · audit · serve · mcp
```

The dashboard and the MCP server open DuckDB **read-only**, so both keep working while an
evaluation holds the write lock.

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

Single container, embedded DuckDB, data on a named volume, non-root, health-checked. The
dashboard builds its frontend on first launch, which needs network access once.

## Development

```bash
pip install -e ".[all]"
python -m pytest                    # 195 tests
python examples/rag_pipeline.py && evalforge ingest && evalforge trace stats
```

`docs/index.html` is the landing page — self-contained, no build step. Open it directly,
or point GitHub Pages at `docs/`.

## Attribution

Derived from [Opik](https://github.com/comet-ml/opik) by Comet ML. The tracing decorator
pattern, context propagation model and judge prompt rubrics are adapted from their Python
SDK. The other ~90% of Opik — a 219k-line Java service, ~1,900 React/TS files, an
89.5k-line generated REST client, a 15-container compose stack — was not carried over; the
storage layer, dashboard, faithfulness audit, attribution module, MCP server and CLI were
built independently. Full breakdown in [ATTRIBUTION.md](ATTRIBUTION.md).

Apache-2.0, inherited from upstream — see [LICENSE](LICENSE).
