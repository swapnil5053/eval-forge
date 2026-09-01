CREATE TABLE IF NOT EXISTS faithfulness_audits (
    id             VARCHAR PRIMARY KEY,
    trace_id       VARCHAR,
    span_id        VARCHAR,
    query          VARCHAR,
    answer         VARCHAR,
    context        JSON,
    score          DOUBLE NOT NULL,
    claim_count    INTEGER NOT NULL,
    unsupported    INTEGER NOT NULL,
    contradicted   INTEGER NOT NULL,
    model          VARCHAR,
    created_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_claims (
    id            VARCHAR PRIMARY KEY,
    audit_id      VARCHAR NOT NULL,
    position      INTEGER NOT NULL,
    claim         VARCHAR NOT NULL,
    verdict       VARCHAR NOT NULL,
    severity      INTEGER NOT NULL,
    evidence      JSON,
    rationale     VARCHAR
);

CREATE TABLE IF NOT EXISTS token_attributions (
    id          VARCHAR PRIMARY KEY,
    span_id     VARCHAR,
    trace_id    VARCHAR,
    method      VARCHAR NOT NULL,
    text        VARCHAR NOT NULL,
    tokens      JSON NOT NULL,
    scores      JSON NOT NULL,
    baseline    DOUBLE,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_faithfulness_audits_trace_id ON faithfulness_audits (trace_id);
CREATE INDEX IF NOT EXISTS idx_faithfulness_audits_created_at ON faithfulness_audits (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_claims_audit_id ON audit_claims (audit_id);
CREATE INDEX IF NOT EXISTS idx_token_attributions_span_id ON token_attributions (span_id);
