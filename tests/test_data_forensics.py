import pytest

from research_engine.data_forensics import ColumnRule, audit_rows


def _rows():
    return [
        {
            "id": index,
            "value": float(index),
            "timestamp": f"2026-01-{index + 1:02d}T00:00:00+00:00",
        }
        for index in range(10)
    ]


def test_clean_dataset_has_stable_hash_and_no_critical_findings():
    rules = [
        ColumnRule("id", "numeric", required=True, minimum=0),
        ColumnRule("value", "numeric", required=True, minimum=0, maximum=20),
        ColumnRule("timestamp", "timestamp", required=True, monotonic_increasing=True),
    ]
    first = audit_rows(_rows(), rules, primary_key="id")
    second = audit_rows(_rows(), rules, primary_key="id")
    assert first.dataset_sha256 == second.dataset_sha256
    assert first.row_count == 10
    assert first.critical_count == 0
    assert first.passed is True
    assert first.fraud_proven is False


def test_conflicting_primary_key_is_critical_but_exact_duplicate_is_warning():
    rows = _rows()
    rows.append(dict(rows[0]))
    duplicate = audit_rows(
        rows,
        [ColumnRule("id", "numeric", required=True)],
        primary_key="id",
    )
    codes = {(issue.code, issue.severity) for issue in duplicate.issues}
    assert ("duplicate_row", "warning") in codes
    assert ("duplicate_primary_key", "warning") in codes
    assert duplicate.passed is True

    rows = _rows()
    rows.append({**rows[0], "value": 999.0})
    conflict = audit_rows(
        rows,
        [ColumnRule("id", "numeric", required=True)],
        primary_key="id",
    )
    assert any(
        issue.code == "conflicting_primary_key" and issue.severity == "critical"
        for issue in conflict.issues
    )
    assert conflict.passed is False
    assert conflict.fraud_proven is False


def test_missing_nonfinite_and_out_of_range_values_fail_closed():
    rows = _rows()
    rows[1]["value"] = None
    rows[2]["value"] = float("nan")
    rows[3]["value"] = 50.0
    report = audit_rows(
        rows,
        [ColumnRule("value", "numeric", required=True, minimum=0, maximum=10)],
    )
    codes = {issue.code for issue in report.issues}
    assert "missing_required" in codes
    assert "nonfinite_numeric" in codes
    assert "above_maximum" in codes
    assert report.critical_count >= 3
    assert report.passed is False


def test_time_order_reversal_is_critical_and_abrupt_numeric_step_is_visible():
    rows = _rows()
    rows[6]["timestamp"] = "2025-12-01T00:00:00+00:00"
    rows[7]["value"] = 100.0
    report = audit_rows(
        rows,
        [
            ColumnRule("timestamp", "timestamp", required=True, monotonic_increasing=True),
            ColumnRule("value", "numeric", required=True, max_step=10.0),
        ],
    )
    assert any(issue.code == "order_reversal" for issue in report.issues)
    assert any(issue.code == "abrupt_step" for issue in report.issues)
    assert report.passed is False


def test_robust_outlier_is_warning_not_automatic_fraud_claim():
    rows = _rows()
    rows[8]["value"] = 1_000.0
    report = audit_rows(
        rows,
        [ColumnRule("value", "numeric", required=True, robust_outlier_z=4.0)],
    )
    outliers = [issue for issue in report.issues if issue.code == "robust_outlier"]
    assert outliers
    assert all(issue.severity == "warning" for issue in outliers)
    assert report.fraud_proven is False


def test_invalid_schema_and_row_shapes_are_rejected():
    with pytest.raises(ValueError, match="duplicate column rules"):
        audit_rows(_rows(), [ColumnRule("id"), ColumnRule("id")])
    with pytest.raises(ValueError, match="each row"):
        audit_rows([{"id": 1}, 2], [ColumnRule("id")])
    with pytest.raises(ValueError, match="unsupported"):
        audit_rows(_rows(), [ColumnRule("id", kind="mystery")])
