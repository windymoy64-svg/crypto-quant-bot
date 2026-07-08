from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.paper.engine import PaperEngineConfig, PaperTradingEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run paper trading engine once")
    parser.add_argument("--config", default="configs/paper.json")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def load_config(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main() -> None:
    args = parse_args()
    data = load_config(args.config)
    if args.symbols:
        data["symbols"] = args.symbols
    if args.timeframe:
        data["timeframe"] = args.timeframe
    if args.limit is not None:
        data["limit"] = args.limit

    config = PaperEngineConfig.from_dict(data)
    result = PaperTradingEngine().run_once(config)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()