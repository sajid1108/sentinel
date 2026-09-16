PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- World (synthetic, truncated at DEMO_CLOCK)
CREATE TABLE accounts (
  account_id   TEXT PRIMARY KEY,
  created_at   TEXT NOT NULL,
  source       TEXT NOT NULL CHECK (source IN ('SYNTHETIC','DEMO'))
);

CREATE TABLE identifiers (
  identifier_id        TEXT PRIMARY KEY CHECK (length(identifier_id) = 32),
  kind                 TEXT NOT NULL CHECK (kind IN ('DEVICE','ADDRESS','PAYMENT_TOKEN')),
  is_multi_tenant      INTEGER NOT NULL DEFAULT 0,
  multi_tenant_set_at  TEXT,
  display_label        TEXT NOT NULL
);

CREATE TABLE orders (
  order_id                 TEXT PRIMARY KEY,
  account_id               TEXT NOT NULL REFERENCES accounts(account_id),
  placed_at                TEXT NOT NULL,
  order_value_inr          REAL NOT NULL CHECK (order_value_inr > 0),
  discount_pct             REAL NOT NULL CHECK (discount_pct BETWEEN 0 AND 90),
  n_items                  INTEGER NOT NULL CHECK (n_items >= 1),
  n_variants_same_product  INTEGER NOT NULL,
  primary_category         TEXT NOT NULL,
  delivery_speed           TEXT NOT NULL CHECK (delivery_speed IN ('STANDARD','EXPRESS')),
  payment_method           TEXT NOT NULL CHECK (payment_method IN ('PREPAID_CARD','PREPAID_UPI','COD')),
  device_id                TEXT NOT NULL REFERENCES identifiers(identifier_id),
  address_id               TEXT NOT NULL REFERENCES identifiers(identifier_id),
  payment_token_id         TEXT REFERENCES identifiers(identifier_id),
  source                   TEXT NOT NULL CHECK (source IN ('HISTORY','DEMO','LIVE')),
  split                    TEXT CHECK (split IN ('TRAIN','GAP','CALIBRATION','TEST','RECENT')),
  CHECK ((payment_method = 'COD') = (payment_token_id IS NULL))
);
CREATE INDEX ix_orders_account_time ON orders(account_id, placed_at);
CREATE INDEX ix_orders_device_time  ON orders(device_id, placed_at);
CREATE INDEX ix_orders_token_time   ON orders(payment_token_id, placed_at);
CREATE INDEX ix_orders_address_time ON orders(address_id, placed_at);

CREATE TABLE order_lines (
  order_id     TEXT NOT NULL REFERENCES orders(order_id),
  line_no      INTEGER NOT NULL,
  sku_id       TEXT NOT NULL,
  product_id   TEXT NOT NULL,
  variant      TEXT NOT NULL,
  category     TEXT NOT NULL,
  unit_price_inr REAL NOT NULL,
  quantity     INTEGER NOT NULL,
  PRIMARY KEY (order_id, line_no)
);

CREATE TABLE order_events (
  event_id        INTEGER PRIMARY KEY,
  order_id        TEXT NOT NULL REFERENCES orders(order_id),
  event_type      TEXT NOT NULL CHECK (event_type IN (
                    'DELIVERED','RTO','CANCELLED',
                    'RETURN_REQUESTED','EXCHANGE_REQUESTED','CLAIM_FILED',
                    'QC_PASSED','QC_FLAGGED','CARRIER_EVIDENCE',
                    'ABUSE_CONFIRMED','ABUSE_CLEARED','REFUNDED')),
  occurred_at     TEXT NOT NULL,
  attributes_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_order_events_order_time ON order_events(order_id, occurred_at);
CREATE INDEX ix_order_events_type_time  ON order_events(event_type, occurred_at);

-- Offline-only tables
CREATE TABLE order_labels (
  order_id                  TEXT PRIMARY KEY REFERENCES orders(order_id),
  return_label              INTEGER,
  return_type               TEXT CHECK (return_type IN ('NONE','FULL','PARTIAL','EXCHANGE')),
  returned_value_fraction   REAL,
  abuse_status              TEXT NOT NULL CHECK (abuse_status IN
                              ('CONFIRMED','CLEARED','NO_CLAIM','UNRESOLVED','NOT_MATURED')),
  abuse_label               INTEGER,
  return_label_resolved_at  TEXT,
  abuse_label_resolved_at   TEXT,
  label_definition_version  TEXT NOT NULL
);
CREATE TABLE sim_ground_truth (
  account_id  TEXT PRIMARY KEY,
  archetype   TEXT NOT NULL,
  ring_id     TEXT
);

-- Governance
CREATE TABLE policy_versions (
  policy_version   TEXT PRIMARY KEY,
  config_toml      TEXT NOT NULL,
  config_sha256    TEXT NOT NULL,
  activated_at     TEXT NOT NULL
);

CREATE TABLE model_registry (
  model_version        TEXT PRIMARY KEY,
  model_name           TEXT NOT NULL CHECK (model_name IN ('RETURN','ABUSE')),
  trained_at           TEXT NOT NULL,
  train_window         TEXT NOT NULL,
  calibration_window   TEXT NOT NULL,
  calibration_method   TEXT NOT NULL CHECK (calibration_method IN ('ISOTONIC','SIGMOID')),
  feature_set_version  TEXT NOT NULL,
  features_json        TEXT NOT NULL,
  sklearn_version      TEXT NOT NULL,
  artifact_sha256      TEXT NOT NULL,
  metrics_json         TEXT NOT NULL
);

-- Decisions
CREATE TABLE decisions (
  decision_id             TEXT PRIMARY KEY,
  order_id                TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
  scored_at               TEXT NOT NULL,
  features_as_of          TEXT NOT NULL,
  feature_set_version     TEXT NOT NULL,
  features_json           TEXT NOT NULL,
  p_return                REAL CHECK (p_return IS NULL OR p_return BETWEEN 0 AND 1),
  p_abuse                 REAL CHECK (p_abuse IS NULL OR p_abuse BETWEEN 0 AND 1),
  p_abuse_without_graph   REAL,
  return_model_version    TEXT NOT NULL REFERENCES model_registry(model_version),
  abuse_model_version     TEXT NOT NULL REFERENCES model_registry(model_version),
  policy_version          TEXT NOT NULL REFERENCES policy_versions(policy_version),
  cost_optimal_action     TEXT CHECK (cost_optimal_action IS NULL OR cost_optimal_action IN ('ALLOW','PREPAID_ONLY','MANUAL_REVIEW','BLOCK')),
  recommended_action      TEXT NOT NULL CHECK (recommended_action IN ('ALLOW','PREPAID_ONLY','MANUAL_REVIEW','BLOCK')),
  current_action          TEXT NOT NULL CHECK (current_action IN ('ALLOW','PREPAID_ONLY','MANUAL_REVIEW','BLOCK')),
  status                  TEXT NOT NULL CHECK (status IN
                            ('AUTO_APPLIED','PENDING_REVIEW','OVERRIDDEN','APPEAL_OPEN')),
  selected_rule           TEXT NOT NULL CHECK (selected_rule IN ('MIN_EXPECTED_COST','MIN_EXPECTED_COST_WITHIN_GUARDRAILS','DEGRADED_MODE_FALLBACK')),
  costs_json              TEXT NOT NULL,
  guardrails_json         TEXT NOT NULL,
  reasons_json            TEXT NOT NULL,
  graph_summary_json      TEXT NOT NULL,
  degraded_mode           INTEGER NOT NULL DEFAULT 0,
  source                  TEXT NOT NULL CHECK (source IN ('DEMO','BACKTEST_REPLAY','LIVE')),
  latest_audit_event_id   TEXT NOT NULL,
  -- Only degraded decisions may lack scores (no model output means nothing to record).
  CHECK ((degraded_mode = 1) OR (p_return IS NOT NULL AND p_abuse IS NOT NULL AND cost_optimal_action IS NOT NULL))
);
CREATE INDEX ix_decisions_queue ON decisions(status, current_action, scored_at);

CREATE TRIGGER decisions_core_immutable
BEFORE UPDATE OF decision_id, order_id, scored_at, features_as_of, feature_set_version,
                 features_json, p_return, p_abuse, p_abuse_without_graph,
                 return_model_version, abuse_model_version, policy_version,
                 cost_optimal_action, recommended_action, selected_rule,
                 costs_json, guardrails_json, reasons_json, graph_summary_json,
                 degraded_mode, source
ON decisions
BEGIN SELECT RAISE(ABORT, 'decision core fields are immutable'); END;

-- Audit (append-only, tamper-evident)
CREATE TABLE audit_events (
  seq                   INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id              TEXT NOT NULL UNIQUE,
  event_type            TEXT NOT NULL CHECK (event_type IN
                          ('DECISION_CREATED','OVERRIDE_APPLIED','APPEAL_OPENED')),
  occurred_at           TEXT NOT NULL,
  order_id              TEXT NOT NULL REFERENCES orders(order_id),
  decision_id           TEXT NOT NULL REFERENCES decisions(decision_id),
  actor_type            TEXT NOT NULL CHECK (actor_type IN ('SYSTEM','REVIEWER')),
  actor_id              TEXT NOT NULL,
  previous_action       TEXT CHECK (previous_action IS NULL OR previous_action IN ('ALLOW','PREPAID_ONLY','MANUAL_REVIEW','BLOCK')),
  new_action            TEXT NOT NULL CHECK (new_action IN ('ALLOW','PREPAID_ONLY','MANUAL_REVIEW','BLOCK')),
  policy_version        TEXT NOT NULL,
  return_model_version  TEXT NOT NULL,
  abuse_model_version   TEXT NOT NULL,
  payload_json          TEXT NOT NULL,
  prev_hash             TEXT NOT NULL,
  event_hash            TEXT NOT NULL UNIQUE
);
CREATE INDEX ix_audit_order ON audit_events(order_id, seq);

CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

-- Probe logging
CREATE TABLE probe_events (
  id               INTEGER PRIMARY KEY,
  occurred_at      TEXT NOT NULL,
  device_id        TEXT,
  account_id       TEXT,
  attempts_24h     INTEGER NOT NULL,
  distinct_carts_24h INTEGER NOT NULL
);
