"""Tests for ec2_inventory module."""

import json
from datetime import datetime

import boto3
import pytest
from botocore.exceptions import ProfileNotFound
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


def _stubbed_ec2(reservations, region="us-east-1"):
    ec2 = boto3.client("ec2", region_name=region)
    stubber = Stubber(ec2)
    stubber.add_response("describe_instances", {"Reservations": reservations})
    stubber.activate()
    return ec2


class TestMain:
    """Tests for main() end to end, with boto3, region discovery, and credential checks mocked out."""

    def _patch_common(self, monkeypatch, regions, clients_by_region):
        monkeypatch.setattr(script, "validate_session", lambda session: None)
        monkeypatch.setattr(script, "resolve_regions", lambda session, region_arg: regions)
        monkeypatch.setattr(
            script.boto3, "Session",
            lambda profile_name=None: FakeSession(clients_by_region),
        )

    def test_writes_inventory_with_tags_and_owner_fallback(self, tmp_path, monkeypatch):
        """Rows include the Name tag and fall back to lowercase 'owner' when 'Owner' is absent."""
        ec2 = _stubbed_ec2([{
            "Instances": [
                _instance("i-1", tags={"Name": "web-1", "Owner": "alice"}),
                _instance("i-2", tags={"Name": "web-2", "owner": "bob"}),
            ],
        }])
        output = tmp_path / "ec2.csv"

        self._patch_common(monkeypatch, ["us-east-1"], {"us-east-1": ec2})
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

        self._patch_common(monkeypatch, ["us-east-1"], {"us-east-1": ec2})
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

        monkeypatch.setattr(script, "validate_session", lambda session: None)
        monkeypatch.setattr(script, "resolve_regions", lambda session, region_arg: ["us-west-2", "us-east-1"])
        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FailingThenGoodSession())
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])

        script.main()

        rows = output.read_text().splitlines()
        assert len(rows) == 2
        assert "us-west-2" in capsys.readouterr().err

    def test_scans_every_region_it_is_given_not_just_one(self, tmp_path, monkeypatch):
        """More than one region is scanned, and rows from all of them end up in the output."""
        ec2_east = _stubbed_ec2([{"Instances": [_instance("i-east")]}], region="us-east-1")
        ec2_frankfurt = _stubbed_ec2([{"Instances": [_instance("i-fra")]}], region="eu-central-1")
        output = tmp_path / "ec2.csv"

        self._patch_common(
            monkeypatch,
            ["us-east-1", "eu-central-1"],
            {"us-east-1": ec2_east, "eu-central-1": ec2_frankfurt},
        )
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])

        script.main()

        rows = output.read_text().splitlines()
        regions_seen = {line.split(",")[0] for line in rows[1:]}
        assert regions_seen == {"us-east-1", "eu-central-1"}

    def test_region_flag_bypasses_discovery(self, tmp_path, monkeypatch):
        """--region scans exactly the listed regions without calling describe_regions."""
        ec2_east = _stubbed_ec2([{"Instances": [_instance("i-east")]}], region="us-east-1")
        ec2_sydney = _stubbed_ec2([{"Instances": [_instance("i-syd")]}], region="ap-southeast-2")
        output = tmp_path / "ec2.csv"
        seen_regions = set()

        class NoDiscoverySession:
            def client(self, service_name, region_name=None):
                assert service_name == "ec2", "must not call ec2.describe_regions"
                seen_regions.add(region_name)
                return {"us-east-1": ec2_east, "ap-southeast-2": ec2_sydney}[region_name]

        monkeypatch.setattr(script, "validate_session", lambda session: None)
        monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: NoDiscoverySession())
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--output", str(output), "--region", "us-east-1,ap-southeast-2"],
        )

        script.main()

        assert seen_regions == {"us-east-1", "ap-southeast-2"}

    def test_format_json_writes_json_to_default_filename(self, tmp_path, monkeypatch):
        """With --format json and no --output, main() writes ec2_inventory.json in the cwd."""
        ec2 = _stubbed_ec2([{"Instances": [_instance("i-1", tags={"Name": "web-1"})]}])
        monkeypatch.chdir(tmp_path)

        self._patch_common(monkeypatch, ["us-east-1"], {"us-east-1": ec2})
        monkeypatch.setattr("sys.argv", ["prog", "--format", "json"])

        script.main()

        data = json.loads((tmp_path / "ec2_inventory.json").read_text())
        assert data[0]["instance_id"] == "i-1"
        assert data[0]["name"] == "web-1"

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
