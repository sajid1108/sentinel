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


def cmd_build_features(args):
    print("Building point-in-time features...")
    print("[Phase 3] Not yet implemented")


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
    sub.add_parser("build-features", help="[Phase 3] Build point-in-time features")
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
