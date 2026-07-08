from __future__ import annotations

import argparse

from app.research.runner import generate_strategy_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate research-only strategy validation reports from existing artifacts")
    parser.add_argument("--logs-dir", default="logs")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    paths = generate_strategy_report(args.logs_dir, args.output_dir)
    print(f"JSON: {paths['json']}")
    print(f"HTML: {paths['html']}")
    print(f"CSV: {paths['csv']}")


if __name__ == "__main__":
    main()