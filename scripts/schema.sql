PRAGMA foreign_keys = ON;

CREATE TABLE companies (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sector TEXT NOT NULL CHECK (sector IN ('tech', 'retail', 'logistics')),
    exchange TEXT NOT NULL,
    cik INTEGER NOT NULL UNIQUE,
    source_url TEXT NOT NULL CHECK (source_url LIKE 'https://%'),
    as_of_date TEXT NOT NULL,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE financial_observations (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL REFERENCES companies(ticker),
    metric TEXT NOT NULL,
    value REAL,
    unit TEXT,
    period_kind TEXT NOT NULL CHECK (period_kind IN ('instant','fiscal_year','ttm','observation')),
    period_start TEXT,
    period_end TEXT,
    reported_at TEXT,
    accession TEXT,
    source_tag TEXT,
    scale REAL NOT NULL CHECK (scale > 0),
    source_url TEXT NOT NULL CHECK (source_url LIKE 'https://%'),
    as_of_date TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(ticker, metric, period_kind, period_start, as_of_date, source_url)
);

CREATE TABLE financial_lineage (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES financial_observations(id) ON DELETE CASCADE,
    input_observation_id INTEGER NOT NULL REFERENCES financial_observations(id),
    role TEXT NOT NULL,
    source_url TEXT NOT NULL CHECK (source_url LIKE 'https://%'),
    as_of_date TEXT NOT NULL,
    UNIQUE(observation_id, input_observation_id, role)
);

CREATE TABLE hiring_signals (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL REFERENCES companies(ticker),
    signal TEXT,
    signal_kind TEXT NOT NULL CHECK (signal_kind IN ('headcount','hiring_signal')),
    value REAL,
    unit TEXT,
    observed_on TEXT NOT NULL,
    period_end TEXT,
    source_url TEXT NOT NULL CHECK (source_url LIKE 'https://%'),
    as_of_date TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(ticker, signal_kind, observed_on, source_url)
);

CREATE INDEX idx_financial_lookup ON financial_observations(ticker, metric, as_of_date DESC);
CREATE INDEX idx_hiring_lookup ON hiring_signals(ticker, observed_on DESC);
