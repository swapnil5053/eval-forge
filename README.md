# EvalForge

A lightweight LLM evaluation workbench for individual developers.

Trace your LLM calls with a decorator, store them in a single DuckDB file, evaluate
them with LLM-as-a-judge metrics, audit RAG answers claim by claim, and read the
results from a CLI, a dashboard, or your coding assistant over MCP.

No server. No account. One file on disk.

```
@trace  ->  ~/.evalforge/spool/*.ndjson  ->  ingest  ->  evalforge.db  ->  CLI / dashboard / MCP
```

## Install

```bash
pip install evalforge              # tracing, storage, CLI
pip install evalforge[eval]        # adds litellm for judge metrics and cost estimation
pip install evalforge[dashboard]   # adds the Reflex dashboard
pip install evalforge[mcp]         # adds the MCP server
pip install evalforge[all]         # everything, including SHAP attribution
```

## Quick start

```bash
evalforge init
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


answer("What is the capital of France?")
```

```bash
evalforge ingest              # load spooled traces into DuckDB
evalforge trace list          # recent traces
evalforge trace show 1b4343ea # span tree for one trace (an id prefix is enough)
evalforge trace stats         # volume, p50/p95/p99, error rate, tokens, spend
evalforge trace search paris  # search names, inputs and outputs
```

Or query it yourself — it is just a DuckDB file:

```bash
duckdb ~/.evalforge/evalforge.db \
  "SELECT name, type, prompt_tokens, estimated_cost_usd FROM spans ORDER BY start_time"
```

## Evaluate

Metrics are plain functions. There is no base class and no `.score()` method, so your
own metric is any function with the same shape — the runner passes each one only the
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
print(results.means())
```

Scores run 0 to 1, but not all of them are good when high — `hallucination` and
`toxicity` are bad when high. Every `Score` carries `higher_is_better`, so the CLI,
the dashboard and the comparison view never have to guess which way a metric points.

Ships with `hallucination`, `faithfulness`, `answer_relevance`, `context_precision`,
`context_recall`, `toxicity`, `coherence` and `conciseness`. The judge runs through
LiteLLM, so any provider works — including a local Ollama, which keeps the whole
loop offline.

The same run from a config file:

```bash
evalforge eval run experiment.yaml
evalforge eval list
evalforge eval show rag-v2
```

## Audit a RAG answer claim by claim

A faithfulness score of 0.62 says an answer is partly ungrounded. It does not say
*which part*. `evalforge audit` decomposes the answer into individual claims and
checks each one against the passages that were actually retrieved:

```bash
evalforge audit run 1b4343ea
```

```
faithfulness 0.50  2 claims  1 unsupported  0 contradicted

SUPPORTED            Paris is the capital of France.
                     evidence: Paris has been the capital of France since 987.
UNSUPPORTED          It has 9 bridges.
                     the context is silent on this
```

Claims are ranked by severity: a contradiction outranks a gap, because the context
was there and the answer went against it. This is the part of EvalForge with no
upstream equivalent.

## Dashboard

```bash
evalforge serve
```

Ingests anything waiting in the spool, then serves a dark instrument panel on
localhost:8000 — metric strip, 7-day volume and latency percentiles, token and cost
breakdowns, recent errors, a trace explorer whose rows open into a `tree(1)`-style
span view with a proportional waterfall, experiment comparison with per-item score
deltas, datasets, and the claim-level audit reports.

The dashboard opens DuckDB **read-only**, so it keeps working while an evaluation
holds the write lock — it shows the last ingested state until that finishes.

## Query it from Claude or Cursor

```bash
evalforge mcp install    # prints the client config block
evalforge mcp serve      # runs the server on stdio
```

Exposes `list_traces`, `get_trace`, `get_trace_stats`, `search_traces`,
`list_experiments`, `get_experiment` and `run_faithfulness_audit`, plus the
`evalforge://stats` and `evalforge://traces/latest` resources.

Opik ships an MCP server too, so this is not a novel idea — the difference is
architectural. Theirs talks to a running Java backend over HTTP and needs a server,
an API key and a workspace. This one opens the DuckDB file directly: nothing to
start, nothing to authenticate, and it can expose the faithfulness audit.

## How traces reach the database

DuckDB allows one writer, so the traced application never opens it. `@trace` appends
NDJSON to a per-process file under `~/.evalforge/spool`, and whichever process runs
ingestion owns the database. Nothing blocks your application, two processes can be
traced at once, and traces recorded while nothing is ingesting simply wait in the
spool.

Files being written end in `.ndjson.active` and are renamed once sealed, so the
ingester never reads a half-written line; a file abandoned by a crashed process is
adopted after five minutes.

## Architecture

```
evalforge/
├── core/        @trace, contextvar span stack, spool writer, cost estimation
├── storage/     DuckDB, numbered SQL migrations, the analytical query layer
├── eval/        judge, metrics, datasets, experiment runner, faithfulness audit,
│                SHAP / occlusion token attribution
├── dashboard/   Reflex panel — all styling flows from one styles.py
├── mcp/         the MCP server
└── cli/         init, ingest, status, trace, eval, audit, serve, mcp
```

One language, one process, one file. `docs/index.html` is the project's landing
page — self-contained, no build step; point GitHub Pages at `docs/` to publish it.

## Docker

```bash
docker compose up --build
```

Single container, embedded DuckDB, data on a named volume at `/data`. The image runs
as a non-root user and carries a health check. Note the dashboard builds its frontend
on first launch, which needs network access once.

## Why EvalForge?

Opik and Langfuse are excellent *team platforms*: multi-tenant, horizontally scalable,
many services. The cost of that architecture is paid at install time by every user,
including the solo developer who wants to trace one RAG pipeline on a laptop.

EvalForge takes the opposite position — one language, one process, one file on disk —
and accepts the limits that come with it: single user, single node, no production
online scoring. In exchange, install is `pip install evalforge`, your traces are a
portable file you can query with plain SQL, and there is nothing to deploy.

## Development

```bash
pip install -e ".[all]"
python -m pytest          # 189 tests
python examples/rag_pipeline.py && evalforge ingest && evalforge trace stats
```

## License

Apache-2.0. See [ATTRIBUTION.md](ATTRIBUTION.md) for provenance — EvalForge is
derived from [Opik](https://github.com/comet-ml/opik) by Comet ML.
