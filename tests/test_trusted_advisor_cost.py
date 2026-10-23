"""Tests for trusted_advisor_cost module."""

import boto3
import pytest
from botocore.stub import Stubber

import trusted_advisor_cost as script


class FakeSession:
    """Stand-in for boto3.Session returning a pre-built support client."""

    def __init__(self, client):
        self._client = client

    def client(self, service_name, region_name=None):
        assert service_name == "support"
        return self._client


def _check(check_id, name, category):
    return {"id": check_id, "name": name, "category": category, "description": "", "metadata": []}


def _check_result(flagged_resources, flagged_count=None):
    for res in flagged_resources:
        res.setdefault("status", "warning")
    return {
        "result": {
            "checkId": "check-id",
            "timestamp": "2024-01-01T00:00:00Z",
            "status": "warning",
            "resourcesSummary": {
                "resourcesProcessed": len(flagged_resources),
                "resourcesFlagged": flagged_count or len(flagged_resources),
                "resourcesIgnored": 0,
                "resourcesSuppressed": 0,
            },
            "categorySpecificSummary": {},
            "flaggedResources": flagged_resources,
        },
    }


def _run_main(monkeypatch, client, extra_args=None):
    monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(client))
    monkeypatch.setattr("sys.argv", ["prog", *(extra_args or [])])
    script.main()


class TestMain:
    """Tests for main() end to end, with the Support (Trusted Advisor) client stubbed."""

    def test_includes_known_cost_check_and_any_cost_category_check(self, tmp_path, monkeypatch):
        """A check is evaluated if its name is a known cost check, or its category mentions cost."""
        support = boto3.client("support", region_name="us-east-1")
        stubber = Stubber(support)
        stubber.add_response("describe_trusted_advisor_checks", {"checks": [
            _check("1", "Low Utilization Amazon EC2 Instances", "performance"),
            _check("2", "Some Other Check", "Cost Optimizing"),
            _check("3", "Unrelated Security Check", "security"),
        ]})
        stubber.add_response(
            "describe_trusted_advisor_check_result",
            _check_result([{"resourceId": "i-1", "region": "us-east-1", "metadata": ["i-1", "$10.00"]}]),
        )
        stubber.add_response(
            "describe_trusted_advisor_check_result",
            _check_result([{"resourceId": "lb-1", "region": "us-east-1", "metadata": ["lb-1", "$5.00"]}]),
        )
        stubber.activate()
        output = tmp_path / "ta_cost.csv"

        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(support))
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])
        script.main()

        rows = output.read_text().splitlines()
        assert len(rows) == 3  # header + 2 findings
        assert "Unrelated Security Check" not in output.read_text()

    def test_picks_largest_dollar_figure_in_metadata_as_savings(self, tmp_path, monkeypatch):
        """The savings estimate is the largest dollar figure among a resource's metadata fields."""
        support = boto3.client("support", region_name="us-east-1")
        stubber = Stubber(support)
        stubber.add_response("describe_trusted_advisor_checks", {"checks": [
            _check("1", "Idle Load Balancers", "cost_optimizing"),
        ]})
        stubber.add_response(
            "describe_trusted_advisor_check_result",
            _check_result([{
                "resourceId": "lb-1",
                "region": "us-west-2",
                "metadata": ["lb-1", "5", "$123.45", "not-a-number"],
            }]),
        )
        stubber.activate()
        output = tmp_path / "ta_cost.csv"

        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(support))
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])
        script.main()

        row = output.read_text().splitlines()[1]
        assert row == "Idle Load Balancers,lb-1,us-west-2,123.45"

    def test_check_result_failure_is_skipped_not_fatal(self, tmp_path, monkeypatch, capsys):
        """A failure fetching one check's result is logged and skipped; others still run."""
        support = boto3.client("support", region_name="us-east-1")
        stubber = Stubber(support)
        stubber.add_response("describe_trusted_advisor_checks", {"checks": [
            _check("1", "Idle Load Balancers", "cost_optimizing"),
            _check("2", "Unassociated Elastic IP Addresses", "cost_optimizing"),
        ]})
        stubber.add_client_error("describe_trusted_advisor_check_result", service_error_code="AccessDeniedException")
        stubber.add_response(
            "describe_trusted_advisor_check_result",
            _check_result([{"resourceId": "eip-1", "region": "us-east-1", "metadata": ["eip-1", "$2.00"]}]),
        )
        stubber.activate()
        output = tmp_path / "ta_cost.csv"

        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(support))
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])
        script.main()

        rows = output.read_text().splitlines()
        assert len(rows) == 2  # header + the one check that succeeded
        assert "Idle Load Balancers" in capsys.readouterr().err

    def test_checks_api_failure_exits_nonzero(self, monkeypatch, capsys):
        """An API failure listing checks prints an error to stderr and exits non-zero."""
        support = boto3.client("support", region_name="us-east-1")
        stubber = Stubber(support)
        stubber.add_client_error("describe_trusted_advisor_checks", service_error_code="SubscriptionRequiredException")
        stubber.activate()

        with pytest.raises(SystemExit) as exc_info:
            _run_main(monkeypatch, support)

        assert exc_info.value.code == 1
        assert "Cannot reach Trusted Advisor" in capsys.readouterr().err
