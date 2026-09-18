import argparse
import sys


def cmd_generate(args):
    from sentinel.data.generator import generate, summarize, write_outputs
    from sentinel.settings import DATA_DIR

    print("Generating synthetic data...")
    world = generate()
    paths = write_outputs(world, DATA_DIR)
    for path in paths.values():
        print(f"  wrote {path}")
    s = summarize(world)
    print(f"  accounts {s['accounts']}, orders {s['orders']}, events {s['events']}")
    print(f"  return rate {s['return_rate']:.1%}, confirmed abuse {s['confirmed_abuse_rate']:.1%} of orders, "
          f"unresolved {s['unresolved']}")
    print(f"  TEST abuse positives {s['test_abuse_positives']}, rings {s['rings']}")
    print(f"  event log sha256 {s['sha256']}")


def cmd_world_stats(args):
    from sentinel.data.generator import SEED, generate, world_stats

    s = world_stats(generate())
    print(f"World (seed {SEED})")
    print(f"  accounts {s['accounts']}, orders {s['orders']}")
    print(f"  return rate {s['return_rate']:.1%}")
    print(f"  confirmed abuse {s['confirmed_abuse_share']:.1%} of orders")
    print(f"  UNRESOLVED {s['unresolved']} of {s['disputed_orders']} disputed orders "
          f"({s['unresolved_share_of_disputes']:.1%})")
    print("  abuse positives by split: "
          + ", ".join(f"{split} {n}" for split, n in s["positives_by_split"].items()))
    for ring_id, r in s["rings"].items():
        print(f"  ring {ring_id}: {r['members']} members, orders per member median {r['median_orders']:g}, "
              f"max {r['max_orders']}")
    print(f"  ring orders with >= 1 own prior flagged claim (180 d): "
          f"{s['ring_orders_with_own_prior_flagged_claim']:.1%}")


def cmd_build_features(args):
    import time

    import pandas as pd

    from sentinel.data.generator import OUTPUT_FILES
    from sentinel.features.builder import WORLD_TABLES, build_tables
    from sentinel.features.definitions import FEATURE_SET_VERSION
    from sentinel.settings import DATA_DIR

    missing = [OUTPUT_FILES[t] for t in WORLD_TABLES if not (DATA_DIR / OUTPUT_FILES[t]).exists()]
    if missing:
        sys.exit(f"missing {', '.join(missing)} in {DATA_DIR}; run `python -m sentinel.cli generate` first")
    print("Building point-in-time features...")
    start = time.perf_counter()
    world = {t: pd.read_parquet(DATA_DIR / OUTPUT_FILES[t]) for t in WORLD_TABLES}
    table, policy = build_tables(world)
    path = DATA_DIR / "features.parquet"
    table.to_parquet(path, index=False)
    policy_path = DATA_DIR / "policy_inputs.parquet"
    policy.to_parquet(policy_path, index=False)
    elapsed = time.perf_counter() - start
    print(f"  wrote {path}")
    print(f"  wrote {policy_path} (policy and baseline inputs, never model features)")
    print(f"  {len(table)} orders, {table.shape[1] - 4} features, feature_set_version {FEATURE_SET_VERSION}")
    print(f"  elapsed {elapsed:.1f} s")


def cmd_train(args):
    import time

    from sentinel.evaluation.splits import load_offline_data
    from sentinel.models.registry import ArtifactError, existing_artifacts, save_bundles
    from sentinel.models.train import excluded_label_counts, train_all
    from sentinel.settings import ARTIFACTS_DIR, DEMO_CLOCK

    if existing_artifacts(ARTIFACTS_DIR) and not args.force:
        sys.exit(f"artifacts already exist in {ARTIFACTS_DIR}; refusing to overwrite (pass --force)")
    print("Training models...")
    start = time.perf_counter()
    data = load_offline_data()
    for split, counts in excluded_label_counts(data.frame).items():
        print(f"  excluded (NULL label) {split}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    results = train_all(data.frame, trained_at=DEMO_CLOCK)
    try:
        registry = save_bundles({n: r.bundle for n, r in results.items()}, ARTIFACTS_DIR, force=args.force)
    except ArtifactError as exc:
        sys.exit(str(exc))
    for name, entry in registry["models"].items():
        tw, cw = entry["train_window"], entry["calibration_window"]
        print(f"  {entry['model_version']}: train {tw['rows']} rows ({tw['positives']} positive), "
              f"calibration {cw['rows']} rows ({cw['positives']} positive), {entry['calibration_method']}")
        print(f"    sha256 {entry['sha256']}")
    print(f"  wrote {ARTIFACTS_DIR / 'model_registry.json'}")
    print(f"  elapsed {time.perf_counter() - start:.1f} s")


def _load_bundles():
    from sentinel.models.registry import MODEL_NAMES, ArtifactError, load_bundle

    try:
        return {name: load_bundle(name) for name in MODEL_NAMES}
    except ArtifactError as exc:
        sys.exit(str(exc))


def cmd_build_reference(args):
    """Per-feature reference vector for ablation attributions: the typical genuine CALIBRATION order (§6.5).

    Numeric features use the median, categoricals the most frequent value. Built from labelled rows here,
    offline, and committed; models/ never sees a label."""
    from sentinel.features import definitions
    from sentinel.models import registry
    from sentinel.models.train import CALIBRATION
    from sentinel.evaluation.splits import load_offline_data

    print("Building attribution reference vector...")
    bundles = _load_bundles()
    frame = load_offline_data().frame
    rows = frame[(frame["split"] == CALIBRATION) & (frame["abuse_label"] == 0)]
    if rows.empty:
        raise SystemExit("no genuine CALIBRATION rows; run generate and build-features first")

    values = {}
    for name in definitions.all_features():
        column = rows[name]
        if name in definitions.CATEGORICAL_FEATURES:
            values[name] = str(column.mode().iloc[0])
        else:
            values[name] = float(column.astype("float64").median())

    versions = {n: b["model_version"] for n, b in bundles.items()}
    payload = registry.save_reference(values, definitions.FEATURE_SET_VERSION, versions, len(rows))
    print(f"  {len(rows)} genuine CALIBRATION rows, {len(values)} features, "
          f"feature set {payload['feature_set_version']}")
    print(f"  models {', '.join(f'{k}={v}' for k, v in sorted(versions.items()))}")
    print(f"  sha256 {payload['sha256']}")
    print(f"  wrote {registry.reference_path()}")


def cmd_evaluate(args):
    import json
    import time

    from sentinel.evaluation.report import run_evaluation
    from sentinel.evaluation.splits import load_offline_data
    from sentinel.policy.config import load_policy_config
    from sentinel.settings import ARTIFACTS_DIR

    print("Running evaluation...")
    start = time.perf_counter()
    report, _ = run_evaluation(load_offline_data(), _load_bundles(), load_policy_config())
    path = ARTIFACTS_DIR / "reports" / "evaluation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for m in report["models"]:
        detail = report["model_details"][m["model"]]
        print(f"  {m['model']:6s} {m['model_version']}: PR-AUC {m['pr_auc']:.3f} "
              f"[{m['pr_auc_ci95'][0]:.3f}, {m['pr_auc_ci95'][1]:.3f}], Brier {m['brier']:.4f}, "
              f"ECE {m['ece_10bin_quantile']:.4f} (CALIBRATION {detail['calibration_slice_ece_10bin_quantile']:.4f}), "
              f"prevalence {detail['test']['prevalence']:.3f}")
    g = report["graph_uplift"]
    r3 = report["cold_start_ring_recall_detail"]
    print(f"  graph uplift: PR-AUC {g['test_pr_auc_full']:.3f} vs no-graph {g['test_pr_auc_no_graph']:.3f} "
          f"(+{g['uplift']:.3f})")
    print(f"  R3 recall (p_abuse >= 0.5): full {r3['full']['recall']:.3f}, no-graph {r3['no_graph']['recall']:.3f} "
          f"of {r3['full']['abusive_orders']}")
    print(f"  FREQUENT_RETURNER corr(p_return, p_abuse) {report['separation']['pearson_p_return_p_abuse']:.3f}")
    ft = report["backtest_details"]["fixed_threshold"]
    print(f"  FIXED_THRESHOLD tuned on CALIBRATION: tau_review {ft['tau_review']:.2f}, tau_block {ft['tau_block']:.2f}")
    print(f"  {'strategy':16s} {'cost/1000':>12s} {'loss prev.':>12s} {'gen.block':>9s} {'friction':>9s} "
          f"{'MR/1000':>8s} {'prec.blk':>8s} {'recall':>7s}")
    for s in report["backtest"]:
        print(f"  {s['strategy']:16s} {s['realized_cost_per_1000']['display']:>12s} "
              f"{s['abuse_loss_prevented']['display']:>12s} {s['genuine_block_rate']:9.4f} "
              f"{s['customer_friction_rate']:9.4f} {s['manual_reviews_per_1000']:8.1f} {s['precision_block']:8.3f} "
              f"{s['recall_intercepted']:7.3f}")
    print(f"  wrote {path}")
    print(f"  elapsed {time.perf_counter() - start:.1f} s")


def cmd_score_demos(args):
    from sentinel.evaluation.demos import score_demos
    from sentinel.money import format_inr
    from sentinel.policy.config import load_policy_config

    bundles = _load_bundles()
    print(f"Scoring demo orders with {bundles['return']['model_version']} and {bundles['abuse']['model_version']}")
    for d in score_demos(bundles, load_policy_config()):
        f, decision = d.features, d.decision
        print(f"\n{d.order_id}")
        print(f"  order {format_inr(f['order_value_inr'])} {f['primary_category']}, account age "
              f"{f['account_age_days']:.0f} d, {f['prior_orders']} prior orders, "
              f"{f['prior_suspicious_claims_180d']} suspicious claims (180 d), CLV {format_inr(d.clv_inr)}")
        print(f"  graph: device others {f['device_other_accounts_30d']}, device confirmed weight "
              f"{f['device_confirmed_abuse_weight']:.2f}, token others {f['token_other_accounts_30d']}, "
              f"component {f['component_size_reliable_90d']} (ratio {f['component_abuse_ratio_smoothed']:.3f}), "
              f"linked 24 h {f['linked_orders_24h']}, same SKU 7 d {f['linked_same_sku_7d']}")
        print(f"  counted signals: {', '.join(d.counted_signals) or 'none'}")
        print(f"  p_return {d.p_return:.4f}   p_abuse {d.p_abuse:.4f}")
        for c in decision.costs:
            state = "" if c.feasible else f"  (removed by {', '.join(c.excluded_by)})"
            print(f"    {c.action.value:14s} {c.expected_cost.display:>9s}{state}")
        triggered = [g.guardrail_id for g in decision.guardrails if g.triggered]
        print(f"  selected {decision.selected_action.value} (cost-optimal {decision.cost_optimal_action.value}, "
              f"{decision.selected_rule}); guardrails triggered: {', '.join(triggered) or 'none'}")


def cmd_seed_db(args):
    from sentinel.db.seed import seed_database

    print("Seeding demo database...")
    try:
        report = seed_database()
    except FileNotFoundError as exc:
        sys.exit(f"{exc}; run generate, build-features and train first")
    _print_seed_report(report)


def _print_seed_report(report):
    print("  world as of DEMO_CLOCK: " + ", ".join(f"{t} {n}" for t, n in report.world_rows.items()))
    print(f"  TEST orders {report.test_orders}; SENTINEL non-ALLOW {report.non_allow_test_orders}; "
          f"ALLOW drawn to fill {report.allow_filled}")
    print("  decisions by action: " + ", ".join(f"{a} {n}" for a, n in report.by_action.items()))
    print("  decisions by source: " + ", ".join(f"{s} {n}" for s, n in report.by_source.items()))
    for note in report.notes:
        print(f"  note: {note}")
    print(f"  wrote {report.path}")
    print(f"  elapsed {report.elapsed_s:.1f} s")


def cmd_serve(args):
    import uvicorn
    uvicorn.run(
        "sentinel.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def cmd_reset_demo(args):
    from sentinel.db.seed import DemoModeOff, reset_demo

    print("Resetting demo state (delete the database file, then seed)...")
    try:
        report = reset_demo()
    except DemoModeOff as exc:
        sys.exit(str(exc))
    _print_seed_report(report)


def main():
    # B10: Fix Windows console encoding for ₹ symbol
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="Sentinel: Return Abuse Detection CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="Generate the synthetic world into data/")
    sub.add_parser("world-stats", help="Print prevalence and ring diagnostics for the seeded world")
    sub.add_parser("build-features", help="Build point-in-time features into data/features.parquet")
    train_p = sub.add_parser("train", help="Train and register the return and abuse models")
    train_p.add_argument("--force", action="store_true", help="overwrite existing artifacts")
    sub.add_parser("build-reference", help="Build the attribution reference vector into artifacts/models/")
    sub.add_parser("evaluate", help="Evaluate models and backtest strategies into artifacts/reports/evaluation.json")
    sub.add_parser("score-demos", help="Score the three demo orders through the committed models and policy")
    sub.add_parser("seed-db", help="Recreate data/sentinel.db: as-of-DEMO_CLOCK world plus 250 backtest-replay decisions")

    serve_p = sub.add_parser("serve", help="Start the API server")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--reload", action="store_true")

    sub.add_parser("reset-demo", help="Delete the demo database and seed it again (DEMO_MODE only)")

    args = parser.parse_args()
    cmd_map = {
        "generate": cmd_generate,
        "world-stats": cmd_world_stats,
        "build-features": cmd_build_features,
        "train": cmd_train,
        "build-reference": cmd_build_reference,
        "evaluate": cmd_evaluate,
        "score-demos": cmd_score_demos,
        "seed-db": cmd_seed_db,
        "serve": cmd_serve,
        "reset-demo": cmd_reset_demo,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
