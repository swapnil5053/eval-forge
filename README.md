# EvalForge

A lightweight LLM evaluation workbench for individual developers.

Trace your LLM calls with a decorator, store them in a single DuckDB file, and
query them with SQL, a CLI, a dashboard, or your coding assistant over MCP.
No server, no database to run, no account.

## Install

```bash
pip install evalforge          # tracing, storage, CLI
pip install evalforge[cost]    # adds litellm for cost estimation
pip install evalforge[all]     # adds the dashboard
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
evalforge trace show 1b4343ea # span tree for one trace (id prefix is enough)
evalforge trace stats         # volume, p50/p95/p99, error rate, tokens, spend
evalforge trace search paris  # search names, inputs and outputs
evalforge trace slow --threshold-ms 500
```

Or query them yourself - it is just a DuckDB file:

```bash
duckdb ~/.evalforge/evalforge.db \
  "SELECT name, type, prompt_tokens, estimated_cost_usd FROM spans ORDER BY start_time"
```

## How traces reach the database

DuckDB allows one writer, so the traced application never opens it. `@trace`
appends NDJSON to a per-process file under `~/.evalforge/spool`, and whichever
process runs ingestion owns the database. Nothing blocks your application, two
processes can be traced at once, and traces recorded while nothing is ingesting
simply wait in the spool.

```
@trace  ->  ~/.evalforge/spool/*.ndjson  ->  ingest  ->  evalforge.db  ->  CLI / dashboard / MCP
```

## Status

Tracing, spool ingestion, DuckDB storage with versioned migrations, the trace
analytics queries and the CLI are in place. The evaluation engine, faithfulness
audit, dashboard and MCP server are next.

## License

Apache-2.0. See [ATTRIBUTION.md](ATTRIBUTION.md) for provenance - EvalForge is
derived from [Opik](https://github.com/comet-ml/opik) by Comet ML.
