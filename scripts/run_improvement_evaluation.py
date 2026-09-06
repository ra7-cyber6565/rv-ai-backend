#!/usr/bin/env python3
"""Run an operator-provisioned final trial; never install or apply a patch."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.improvement_runtime import ImprovementStore, strict_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    bundles = []
    for path in (args.baseline, args.candidate):
        with path.open("rb") as handle:
            raw = handle.read(600001)
        if len(raw) > 600000:
            parser.error("implementation bundle exceeds limit")
        bundles.append(strict_json(raw))
    receipt = ImprovementStore().evaluate(args.project, args.proposal, *bundles)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["state"] == "CONDITIONAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
