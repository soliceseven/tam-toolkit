"""Tests for support_case_summary module."""

import boto3
import pytest
from botocore.stub import Stubber

import support_case_summary as script


class FakeSession:
    """Stand-in for boto3.Session returning a pre-built support client."""

    def __init__(self, client):
        self._client = client

    def client(self, service_name, region_name=None):
        assert service_name == "support"
        return self._client


def _case(case_id, severity="normal", status="opened", subject="", created="2024-01-01T00:00:00Z"):
    return {
        "caseId": case_id,
        "severityCode": severity,
        "status": status,
        "subject": subject,
        "timeCreated": created,
    }


def _run_main(monkeypatch, client, extra_args=None):
    monkeypatch.setattr(script, "validate_session", lambda session: None)
    monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(client))
    monkeypatch.setattr("sys.argv", ["prog", *(extra_args or [])])
    script.main()


class TestMain:
    """Tests for main() end to end, with the Support client stubbed."""

    def test_summarizes_cases_by_severity_and_status(self, monkeypatch, capsys):
        """Cases are grouped and counted by severity and status."""
        support = boto3.client("support", region_name="us-east-1")
        stubber = Stubber(support)
        stubber.add_response("describe_cases", {"cases": [
            _case("case-1", severity="high", status="opened"),
            _case("case-2", severity="high", status="resolved"),
            _case("case-3", severity="low", status="opened"),
        ]})
        stubber.activate()

        _run_main(monkeypatch, support)

        out = capsys.readouterr().out
        assert "3 cases in the last 30 days" in out
        assert "high         2" in out
        assert "low          1" in out
        assert "opened       2" in out
        assert "resolved     1" in out

    def test_lists_up_to_ten_open_cases_newest_first(self, monkeypatch, capsys):
        """Open cases are listed newest-first, capped at 10, and resolved/closed are excluded."""
        support = boto3.client("support", region_name="us-east-1")
        stubber = Stubber(support)
        cases = [_case(f"case-{i}", status="opened", created=f"2024-01-{i:02d}T00:00:00Z") for i in range(1, 13)]
        cases.append(_case("case-resolved", status="resolved"))
        stubber.add_response("describe_cases", {"cases": cases})
        stubber.activate()

        _run_main(monkeypatch, support)

        out = capsys.readouterr().out
        assert "12 still open:" in out
        assert "case-resolved" not in out
        # Newest-first, capped at 10: case-12 down to case-3 should appear, case-1/case-2 should not.
        for i in range(3, 13):
            assert f"case-{i}" in out
        assert "case-1 —" not in out and "case-2 —" not in out

    def test_no_cases_prints_message_and_returns(self, monkeypatch, capsys):
        """An empty case list prints a message without raising."""
        support = boto3.client("support", region_name="us-east-1")
        stubber = Stubber(support)
        stubber.add_response("describe_cases", {"cases": []})
        stubber.activate()

        _run_main(monkeypatch, support)

        assert "No cases in the last 30 days." in capsys.readouterr().out

    def test_support_api_failure_exits_nonzero(self, monkeypatch, capsys):
        """An API failure prints an error to stderr and exits with a non-zero status."""
        support = boto3.client("support", region_name="us-east-1")
        stubber = Stubber(support)
        stubber.add_client_error("describe_cases", service_error_code="AccessDeniedException")
        stubber.activate()

        with pytest.raises(SystemExit) as exc_info:
            _run_main(monkeypatch, support)

        assert exc_info.value.code == 1
        assert "Cannot reach AWS Support API" in capsys.readouterr().err
