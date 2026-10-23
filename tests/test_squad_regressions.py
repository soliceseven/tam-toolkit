"""Offline regression coverage for findings from the Squad review."""

import csv
import json
from unittest.mock import Mock

import pytest

import common
import cost_anomaly_check
import support_case_summary


@pytest.mark.parametrize("value", ["=1+1", " +SUM(A1)", "\t@SUM(A1)", "\r-1", "\x00=1"])
def test_csv_formula_text_is_literal_and_json_is_unchanged(tmp_path, value):
    rows = [{"name": value, "count": -3}]
    common.write_rows(str(tmp_path / "out.csv"), rows, ["name", "count"])
    if "\x00" in value:
        # Python 3.9's CSV reader rejects NULs; inspect the serialized field.
        assert (tmp_path / "out.csv").read_bytes() == b"name,count\r\n'\x00=1,-3\r\n"
    else:
        with (tmp_path / "out.csv").open(newline="") as stream:
            result = next(csv.DictReader(stream))
        assert result["name"] == "'" + value
        assert result["count"] == "-3"
    common.write_rows(str(tmp_path / "out.json"), rows, [], "json")
    assert json.loads((tmp_path / "out.json").read_text()) == rows
    assert rows[0]["name"] == value


def _run(monkeypatch, module, client):
    session = Mock()
    session.client.return_value = client
    monkeypatch.setattr(module.boto3, "Session", lambda **kwargs: session)
    monkeypatch.setattr(module, "validate_session", lambda session: None)
    monkeypatch.setattr("sys.argv", ["prog"])
    module.main()


def _day(day, amount):
    return {"TimePeriod": {"Start": day}, "Total": {"UnblendedCost": {"Amount": str(amount)}}}


def test_cost_pages_are_combined_and_baseline_days_are_not_flagged(monkeypatch, capsys):
    client = Mock()
    client.get_cost_and_usage.side_effect = [
        {"ResultsByTime": [_day("2026-10-20", 100), _day("2026-10-21", 1)], "NextPageToken": "next"},
        {"ResultsByTime": [_day("2026-10-22", 1)]},
    ]
    _run(monkeypatch, cost_anomaly_check, client)
    assert "No anomalies detected." in capsys.readouterr().out
    assert client.get_cost_and_usage.call_args_list[1].kwargs["NextPageToken"] == "next"


def test_support_summary_includes_all_pages(monkeypatch, capsys):
    client = Mock()
    client.describe_cases.side_effect = [
        {"cases": [{"severityCode": "low", "status": "resolved"}], "nextToken": "next"},
        {"cases": [{"severityCode": "high", "status": "resolved"}]},
    ]
    _run(monkeypatch, support_case_summary, client)
    assert "2 cases in the last" in capsys.readouterr().out
    assert client.describe_cases.call_args_list[1].kwargs["nextToken"] == "next"
