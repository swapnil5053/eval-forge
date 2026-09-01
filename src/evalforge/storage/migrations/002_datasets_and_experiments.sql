CREATE TABLE IF NOT EXISTS datasets (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    description VARCHAR,
    created_at  TIMESTAMPTZ NOT NULL,
    metadata    JSON
);

CREATE TABLE IF NOT EXISTS dataset_items (
    id              VARCHAR PRIMARY KEY,
    dataset_id      VARCHAR NOT NULL,
    input           JSON NOT NULL,
    expected_output JSON,
    metadata        JSON,
    created_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    id         VARCHAR PRIMARY KEY,
    name       VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata   JSON
);

CREATE TABLE IF NOT EXISTS experiment_results (
    id              VARCHAR PRIMARY KEY,
    experiment_id   VARCHAR NOT NULL,
    dataset_item_id VARCHAR NOT NULL,
    trace_id        VARCHAR,
    output          JSON,
    scores          JSON,
    latency_ms      DOUBLE,
    error           VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_datasets_name ON datasets (name);
CREATE INDEX IF NOT EXISTS idx_dataset_items_dataset_id ON dataset_items (dataset_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_experiments_name ON experiments (name);
CREATE INDEX IF NOT EXISTS idx_experiments_dataset_id ON experiments (dataset_id);
CREATE INDEX IF NOT EXISTS idx_experiment_results_experiment_id
    ON experiment_results (experiment_id);
CREATE INDEX IF NOT EXISTS idx_experiment_results_dataset_item_id
    ON experiment_results (dataset_item_id);
