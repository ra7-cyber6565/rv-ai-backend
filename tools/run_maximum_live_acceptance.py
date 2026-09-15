#!/usr/bin/env python3
"""Pinned production entrypoint for the MAXIMUM live acceptance harness.

Unlike the reusable validator module, this command refuses to start unless the
operator supplies one exact 40-hex Git revision. The core harness then checks
that `/health.build_revision` is exactly that reviewed revision before creating
any research job.
"""
from __future__ import annotations

import argparse
import re
import sys

from tools import maximum_live_acceptance as core


_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--receipt-file", required=True)
    parser.add_argument("--expected-build-revision", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--question", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    revision = str(args.expected_build_revision or "").strip()
    if not _FULL_SHA.fullmatch(revision):
        print("MAXIMUM_ACCEPTANCE_FAIL: expected build revision must be one full 40-hex Git SHA", file=sys.stderr)
        return 2

    forwarded = [
        "--base-url", args.base_url,
        "--receipt-file", args.receipt_file,
        "--expected-build-revision", revision.lower(),
        "--timeout-seconds", str(args.timeout_seconds),
        "--poll-seconds", str(args.poll_seconds),
    ]
    if args.question:
        forwarded.extend(["--question", args.question])
    return core.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
