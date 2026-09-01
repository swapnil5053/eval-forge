# Attribution

EvalForge is derived from [Opik](https://github.com/comet-ml/opik) by Comet ML,
licensed under Apache-2.0.

The tracing decorator pattern, context propagation model, and evaluation metric
structure are adapted from Opik's Python SDK (~25-30k lines).

The following components were built independently and do not exist in Opik:

- Spool-based trace ingestion architecture (vs. Opik's HTTP client to Java server)
- DuckDB embedded storage layer (vs. Opik's ClickHouse + MySQL + Redis)
- Faithfulness audit engine with claim-level decomposition
- SHAP token attribution traces
- Reflex dashboard (vs. Opik's React/TypeScript frontend)
- CLI-first interface

The remaining ~90% of Opik's codebase (219k-line Java backend service, ~1,900
React/TS files, 89.5k-line generated REST client, 15-container compose stack)
was not carried over. EvalForge targets single-developer use; Opik targets
team/enterprise deployment.

EvalForge's MCP server is not a novel idea: Opik ships `opik-mcp` and an
`opik mcp` command that registers it with Claude, Cursor and Codex. The
difference is architectural. Opik's server talks to a running Java backend over
HTTP; EvalForge's reads the local DuckDB file directly, so there is no server to
start, no API key and no workspace. It also exposes the faithfulness audit,
which has no upstream equivalent.
