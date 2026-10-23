"""Tests for ec2_inventory module."""

from datetime import datetime

import boto3
from botocore.stub import Stubber

import ec2_inventory as script


class FakeSession:
    """Stand-in for boto3.Session returning a pre-built ec2 client per region."""

    def __init__(self, clients_by_region):
        self._clients_by_region = clients_by_region

    def client(self, service_name, region_name=None):
        assert service_name == "ec2"
        return self._clients_by_region[region_name]


def _instance(instance_id, state="running", tags=None):
    return {
        "InstanceId": instance_id,
        "InstanceType": "t3.micro",
        "State": {"Name": state},
        "Placement": {"AvailabilityZone": "us-east-1a"},
        "Tags": [{"Key": k, "Value": v} for k, v in (tags or {}).items()],
        "LaunchTime": datetime(2024, 1, 1),
    }


def _stubbed_ec2(reservations):
    ec2 = boto3.client("ec2", region_name="us-east-1")
    stubber = Stubber(ec2)
    stubber.add_response("describe_instances", {"Reservations": reservations})
    stubber.activate()
    return ec2


class TestMain:
    """Tests for main() end to end, with boto3 and region discovery mocked out."""

    def test_writes_inventory_with_tags_and_owner_fallback(self, tmp_path, monkeypatch):
        """Rows include the Name tag and fall back to lowercase 'owner' when 'Owner' is absent."""
        ec2 = _stubbed_ec2([{
            "Instances": [
                _instance("i-1", tags={"Name": "web-1", "Owner": "alice"}),
                _instance("i-2", tags={"Name": "web-2", "owner": "bob"}),
            ],
        }])
        output = tmp_path / "ec2.csv"

        monkeypatch.setattr(script, "get_all_regions", lambda session: ["us-east-1"])
        monkeypatch.setattr(
            script.boto3, "Session",
            lambda profile_name=None: FakeSession({"us-east-1": ec2}),
        )
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])

        script.main()

        rows = output.read_text().splitlines()
        assert "i-1,running,t3.micro,us-east-1a,web-1,alice" in rows[1]
        assert "i-2,running,t3.micro,us-east-1a,web-2,bob" in rows[2]

    def test_state_filter_excludes_non_matching_instances(self, tmp_path, monkeypatch, capsys):
        """--state filters out instances not in the requested state."""
        ec2 = _stubbed_ec2([{
            "Instances": [
                _instance("i-running", state="running"),
                _instance("i-stopped", state="stopped"),
            ],
        }])
        output = tmp_path / "ec2.csv"

        monkeypatch.setattr(script, "get_all_regions", lambda session: ["us-east-1"])
        monkeypatch.setattr(
            script.boto3, "Session",
            lambda profile_name=None: FakeSession({"us-east-1": ec2}),
        )
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output), "--state", "running"])

        script.main()

        rows = output.read_text().splitlines()
        assert len(rows) == 2  # header + one matching instance
        assert "i-running" in rows[1]
        assert "Wrote" in capsys.readouterr().out

    def test_skips_region_on_error_and_continues(self, tmp_path, monkeypatch, capsys):
        """A region that raises an error is skipped, and other regions are still collected."""
        ec2 = _stubbed_ec2([{"Instances": [_instance("i-ok")]}])
        output = tmp_path / "ec2.csv"

        class FailingThenGoodSession:
            def client(self, service_name, region_name=None):
                if region_name == "us-west-2":
                    raise RuntimeError("access denied")
                return ec2

        monkeypatch.setattr(script, "get_all_regions", lambda session: ["us-west-2", "us-east-1"])
        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FailingThenGoodSession())
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])

        script.main()

        rows = output.read_text().splitlines()
        assert len(rows) == 2
        assert "us-west-2" in capsys.readouterr().err
