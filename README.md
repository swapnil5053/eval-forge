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

## Evaluate

Metrics are plain functions. There is no base class and no `.score()` method, so
your own metric is any function with the same shape.

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

Scores run 0 to 1, but not all of them are good when high - `hallucination` and
`toxicity` are bad when high. Every `Score` carries `higher_is_better`, so the CLI
and the dashboard never have to guess which way a metric points.

The same run from a config file:

```bash
evalforge eval run experiment.yaml
evalforge eval list
evalforge eval show rag-v2
```

## Audit a RAG answer claim by claim

A faithfulness score of 0.62 says an answer is partly ungrounded. It does not say
*which part*. `evalforge audit` decomposes the answer into individual claims and
checks each one against the passages that were retrieved:

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

Tracing, spool ingestion, DuckDB storage with versioned migrations, trace
analytics, the evaluation engine, the faithfulness audit, token attribution and
the CLI are in place. The dashboard and the MCP server are next.

## License

Apache-2.0. See [ATTRIBUTION.md](ATTRIBUTION.md) for provenance - EvalForge is
derived from [Opik](https://github.com/comet-ml/opik) by Comet ML.
