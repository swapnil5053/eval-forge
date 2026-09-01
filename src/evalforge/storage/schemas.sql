CREATE TABLE IF NOT EXISTS traces (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    start_time  TIMESTAMPTZ NOT NULL,
    end_time    TIMESTAMPTZ,
    status      VARCHAR NOT NULL DEFAULT 'ok',
    tags        JSON,
    metadata    JSON
);

CREATE TABLE IF NOT EXISTS spans (
    id                 VARCHAR PRIMARY KEY,
    trace_id           VARCHAR NOT NULL,
    parent_span_id     VARCHAR,
    name               VARCHAR NOT NULL,
    type               VARCHAR NOT NULL DEFAULT 'general',
    start_time         TIMESTAMPTZ NOT NULL,
    end_time           TIMESTAMPTZ,
    status             VARCHAR NOT NULL DEFAULT 'ok',
    input              JSON,
    output             JSON,
    error              VARCHAR,
    model              VARCHAR,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    estimated_cost_usd DOUBLE,
    tags               JSON,
    metadata           JSON
);

CREATE TABLE IF NOT EXISTS feedback_scores (
    id         VARCHAR PRIMARY KEY,
    span_id    VARCHAR NOT NULL,
    name       VARCHAR NOT NULL,
    value      DOUBLE NOT NULL,
    reason     VARCHAR,
    source     VARCHAR NOT NULL DEFAULT 'sdk',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans (trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_start_time ON spans (start_time);
CREATE INDEX IF NOT EXISTS idx_spans_name ON spans (name);
CREATE INDEX IF NOT EXISTS idx_traces_start_time ON traces (start_time);
CREATE INDEX IF NOT EXISTS idx_traces_name ON traces (name);
CREATE INDEX IF NOT EXISTS idx_feedback_scores_span_id ON feedback_scores (span_id);
