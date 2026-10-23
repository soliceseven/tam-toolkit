"""Tests for trusted_advisor_cost module."""

import boto3
import pytest
from botocore.stub import Stubber

import trusted_advisor_cost as script


class FakeSession:
    """Stand-in for boto3.Session returning a pre-built support client, and optionally a ce client."""

    def __init__(self, support_client, ce_client=None):
        self._support_client = support_client
        self._ce_client = ce_client

    def client(self, service_name, region_name=None):
        if service_name == "support":
            return self._support_client
        if service_name == "ce":
            assert self._ce_client is not None, "test did not expect a Cost Explorer fallback call"
            return self._ce_client
        raise AssertionError(f"unexpected service: {service_name}")


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
    monkeypatch.setattr(script, "validate_session", lambda session: None)
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

        monkeypatch.setattr(script, "validate_session", lambda session: None)
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

        monkeypatch.setattr(script, "validate_session", lambda session: None)
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

        monkeypatch.setattr(script, "validate_session", lambda session: None)
        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(support))
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])
        script.main()

        rows = output.read_text().splitlines()
        assert len(rows) == 2  # header + the one check that succeeded
        assert "Idle Load Balancers" in capsys.readouterr().err

    def test_falls_back_to_cost_explorer_when_trusted_advisor_unavailable(self, tmp_path, monkeypatch, capsys):
        """On Basic/Developer support, Trusted Advisor checks fail and Cost Explorer rightsizing is used instead."""
        support = boto3.client("support", region_name="us-east-1")
        support_stubber = Stubber(support)
        support_stubber.add_client_error("describe_trusted_advisor_checks", service_error_code="SubscriptionRequiredException")
        support_stubber.activate()

        ce = boto3.client("ce", region_name="us-east-1")
        ce_stubber = Stubber(ce)
        ce_stubber.add_response("get_rightsizing_recommendation", {
            "RightsizingRecommendations": [
                {
                    "CurrentInstance": {"ResourceId": "i-modify"},
                    "RightsizingType": "Modify",
                    "ModifyRecommendationDetail": {
                        "TargetInstances": [
                            {"EstimatedMonthlySavings": "12.34", "DefaultTargetInstance": True},
                        ],
                    },
                },
                {
                    "CurrentInstance": {"ResourceId": "i-terminate"},
                    "RightsizingType": "Terminate",
                    "TerminateRecommendationDetail": {"EstimatedMonthlySavings": "56.78"},
                },
            ],
        })
        ce_stubber.activate()
        output = tmp_path / "ta_cost.csv"

        monkeypatch.setattr(script, "validate_session", lambda session: None)
        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(support, ce))
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])
        script.main()

        rows = output.read_text().splitlines()
        assert len(rows) == 3  # header + 2 rightsizing findings
        assert "i-modify,,12.34" in rows[1]
        assert "i-terminate,,56.78" in rows[2]
        assert "Falling back to Cost Explorer" in capsys.readouterr().err

    def test_exits_nonzero_when_both_trusted_advisor_and_fallback_fail(self, monkeypatch, capsys):
        """If the Cost Explorer fallback also fails, main() reports both errors and exits non-zero."""
        support = boto3.client("support", region_name="us-east-1")
        support_stubber = Stubber(support)
        support_stubber.add_client_error("describe_trusted_advisor_checks", service_error_code="SubscriptionRequiredException")
        support_stubber.activate()

        ce = boto3.client("ce", region_name="us-east-1")
        ce_stubber = Stubber(ce)
        ce_stubber.add_client_error("get_rightsizing_recommendation", service_error_code="DataUnavailableException")
        ce_stubber.activate()

        monkeypatch.setattr(script, "validate_session", lambda session: None)
        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(support, ce))
        monkeypatch.setattr("sys.argv", ["prog"])

        with pytest.raises(SystemExit) as exc_info:
            script.main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Cannot reach Trusted Advisor" in err
        assert "Cost Explorer fallback also failed" in err
