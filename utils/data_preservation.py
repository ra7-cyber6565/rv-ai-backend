"""Retention policy for stored research, independent of temporary-file cleanup.

Default to preserving stored results, checkpoints and archive copies. Operators
can explicitly restore legacy retention with INFINITY_PRESERVE_STORED_DATA=false.
This does not disable user-requested memory corrections/deletion or disposal of
temporary work files created by the current operation.
"""
from __future__ import annotations

import os
from typing import Mapping


def preserve_stored_data(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    # Missing, misspelled and ambiguous values cannot authorize destruction.
    return str(source.get("INFINITY_PRESERVE_STORED_DATA", "true")).strip().lower() not in {
        "false", "0", "off", "no",
    }
