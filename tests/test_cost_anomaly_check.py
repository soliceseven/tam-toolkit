"""Tests for cost_anomaly_check module."""

import boto3
import pytest
from botocore.exceptions import ProfileNotFound
from botocore.stub import Stubber

import cost_anomaly_check as script


class FakeSession:
    """Stand-in for boto3.Session returning a pre-built Cost Explorer client."""

    def __init__(self, client):
        self._client = client

    def client(self, service_name, region_name=None):
        assert service_name == "ce"
        return self._client


def _cost_response(amounts):
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": f"2024-01-{i + 1:02d}", "End": f"2024-01-{i + 2:02d}"},
                "Total": {"UnblendedCost": {"Amount": str(a)}},
            }
            for i, a in enumerate(amounts)
        ],
    }


def _run_main(monkeypatch, ce_client, extra_args=None):
    monkeypatch.setattr(script, "validate_session", lambda session: None)
    monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(ce_client))
    monkeypatch.setattr("sys.argv", ["prog", *(extra_args or [])])
    script.main()


class TestMain:
    """Tests for main() end to end, with the Cost Explorer client stubbed."""

    def test_flags_day_spending_above_threshold(self, monkeypatch, capsys):
        """A day spending >= threshold x trailing average is flagged with its % over."""
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response("get_cost_and_usage", _cost_response([10, 10, 10, 50]))
        stubber.activate()

        _run_main(monkeypatch, ce)

        out = capsys.readouterr().out
        assert "Trailing 3-day average: $10.00/day" in out
        assert "2024-01-04  $50.00  (+400% vs average)" in out

    def test_no_anomalies_when_all_days_near_average(self, monkeypatch, capsys):
        """No day is flagged when spend stays close to the trailing average."""
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response("get_cost_and_usage", _cost_response([10, 10, 10, 11]))
        stubber.activate()

        _run_main(monkeypatch, ce)

        assert "No anomalies detected." in capsys.readouterr().out

    def test_not_enough_data_returns_early(self, monkeypatch, capsys):
        """Fewer than 3 days of data produces a message and no further processing."""
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response("get_cost_and_usage", _cost_response([10, 10]))
        stubber.activate()

        _run_main(monkeypatch, ce)

        assert "Not enough data." in capsys.readouterr().out

    def test_custom_threshold_changes_what_is_flagged(self, monkeypatch, capsys):
        """A higher --threshold requires a larger relative spike to flag a day."""
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response("get_cost_and_usage", _cost_response([10, 10, 10, 12]))
        stubber.activate()

        _run_main(monkeypatch, ce, extra_args=["--threshold", "2.0"])

        assert "No anomalies detected." in capsys.readouterr().out

    def test_cost_explorer_failure_exits_nonzero(self, monkeypatch, capsys):
        """An API failure prints an error to stderr and exits with a non-zero status."""
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_client_error("get_cost_and_usage", service_error_code="AccessDeniedException")
        stubber.activate()

        with pytest.raises(SystemExit) as exc_info:
            _run_main(monkeypatch, ce)

        assert exc_info.value.code == 1
        assert "Cannot reach Cost Explorer" in capsys.readouterr().err

    def test_invalid_profile_exits_cleanly_instead_of_raw_traceback(self, monkeypatch, capsys):
        """A bad --profile raises ProfileNotFound at Session() construction, caught with a clean exit."""
        def raise_profile_not_found(profile_name=None):
            raise ProfileNotFound(profile="bogus")

        monkeypatch.setattr(script.boto3, "Session", raise_profile_not_found)
        monkeypatch.setattr("sys.argv", ["prog", "--profile", "bogus"])

        with pytest.raises(SystemExit) as exc_info:
            script.main()

        assert exc_info.value.code == 1
        assert "bogus" in capsys.readouterr().err
