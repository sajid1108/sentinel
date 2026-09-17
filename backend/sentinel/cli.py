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
    from sentinel.features.builder import WORLD_TABLES, build_feature_table
    from sentinel.features.definitions import FEATURE_SET_VERSION
    from sentinel.settings import DATA_DIR

    missing = [OUTPUT_FILES[t] for t in WORLD_TABLES if not (DATA_DIR / OUTPUT_FILES[t]).exists()]
    if missing:
        sys.exit(f"missing {', '.join(missing)} in {DATA_DIR}; run `python -m sentinel.cli generate` first")
    print("Building point-in-time features...")
    start = time.perf_counter()
    world = {t: pd.read_parquet(DATA_DIR / OUTPUT_FILES[t]) for t in WORLD_TABLES}
    table = build_feature_table(world)
    path = DATA_DIR / "features.parquet"
    table.to_parquet(path, index=False)
    elapsed = time.perf_counter() - start
    print(f"  wrote {path}")
    print(f"  {len(table)} orders, {table.shape[1] - 4} features, feature_set_version {FEATURE_SET_VERSION}")
    print(f"  elapsed {elapsed:.1f} s")


def cmd_train(args):
    print("Training models...")
    print("[Phase 4] Not yet implemented")


def cmd_evaluate(args):
    print("Running evaluation...")
    print("[Phase 4] Not yet implemented")


def cmd_seed_db(args):
    print("Seeding demo database...")
    print("[Phase 6] Not yet implemented")


def cmd_serve(args):
    import uvicorn
    uvicorn.run(
        "sentinel.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def cmd_reset_demo(args):
    print("Resetting demo state...")
    print("[Phase 6] Not yet implemented")


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
    sub.add_parser("train", help="[Phase 4] Train return and abuse models")
    sub.add_parser("evaluate", help="[Phase 4] Run evaluation suite")
    sub.add_parser("seed-db", help="[Phase 6] Seed the demo database")

    serve_p = sub.add_parser("serve", help="Start the API server")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--reload", action="store_true")

    sub.add_parser("reset-demo", help="[Phase 6] Reset demo state")

    args = parser.parse_args()
    cmd_map = {
        "generate": cmd_generate,
        "world-stats": cmd_world_stats,
        "build-features": cmd_build_features,
        "train": cmd_train,
        "evaluate": cmd_evaluate,
        "seed-db": cmd_seed_db,
        "serve": cmd_serve,
        "reset-demo": cmd_reset_demo,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
