"""Tests for the common module (region discovery, session validation, and output helpers)."""

import json

import boto3
import pytest
from botocore.exceptions import ProfileNotFound
from botocore.stub import Stubber

from common import (
    default_output_path,
    get_all_regions,
    resolve_regions,
    validate_session,
    write_rows,
)


class FakeSession:
    """Minimal stand-in for boto3.Session that hands back a pre-built client."""

    def __init__(self, client):
        self._client = client

    def client(self, service_name, region_name=None):
        assert service_name == "ec2"
        assert region_name == "us-east-1"
        return self._client


def test_get_all_regions_returns_region_names():
    """get_all_regions extracts RegionName from each region in describe_regions."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    stubber = Stubber(ec2)
    stubber.add_response(
        "describe_regions",
        {"Regions": [{"RegionName": "us-east-1"}, {"RegionName": "eu-west-1"}]},
    )
    stubber.activate()

    regions = get_all_regions(FakeSession(ec2))

    assert regions == ["us-east-1", "eu-west-1"]


def test_get_all_regions_empty_when_no_regions_returned():
    """get_all_regions returns an empty list if the account has no enabled regions."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    stubber = Stubber(ec2)
    stubber.add_response("describe_regions", {"Regions": []})
    stubber.activate()

    assert get_all_regions(FakeSession(ec2)) == []


class TestResolveRegions:
    """Tests for resolve_regions."""

    def test_explicit_region_arg_is_parsed_and_not_discovered(self):
        """A --region value is split on commas and trimmed, without calling describe_regions."""
        class ExplodingSession:
            def client(self, service_name, region_name=None):
                raise AssertionError("should not discover regions when --region is given")

        assert resolve_regions(ExplodingSession(), "us-east-1, eu-west-1") == ["us-east-1", "eu-west-1"]

    def test_no_region_arg_falls_back_to_get_all_regions(self):
        """With no --region value, resolve_regions discovers all enabled regions."""
        ec2 = boto3.client("ec2", region_name="us-east-1")
        stubber = Stubber(ec2)
        stubber.add_response("describe_regions", {"Regions": [{"RegionName": "us-east-1"}]})
        stubber.activate()

        assert resolve_regions(FakeSession(ec2), None) == ["us-east-1"]

    def test_empty_region_arg_falls_back_to_get_all_regions(self):
        """An empty --region string behaves the same as not passing one."""
        ec2 = boto3.client("ec2", region_name="us-east-1")
        stubber = Stubber(ec2)
        stubber.add_response("describe_regions", {"Regions": [{"RegionName": "us-east-1"}]})
        stubber.activate()

        assert resolve_regions(FakeSession(ec2), "") == ["us-east-1"]


class TestValidateSession:
    """Tests for validate_session."""

    def test_passes_through_when_credentials_present(self):
        """A session with resolvable credentials does not raise or exit."""
        class SessionWithCreds:
            def get_credentials(self):
                return object()

        validate_session(SessionWithCreds())  # should not raise

    def test_exits_when_no_credentials_found(self, capsys):
        """A session with no resolvable credentials exits with status 1 and a clear message."""
        class SessionWithoutCreds:
            def get_credentials(self):
                return None

        with pytest.raises(SystemExit) as exc_info:
            validate_session(SessionWithoutCreds())

        assert exc_info.value.code == 1
        assert "no AWS credentials found" in capsys.readouterr().err

    def test_exits_on_profile_not_found(self, capsys):
        """An invalid --profile raises ProfileNotFound, which exits with status 1."""
        class SessionWithBadProfile:
            def get_credentials(self):
                raise ProfileNotFound(profile="bogus")

        with pytest.raises(SystemExit) as exc_info:
            validate_session(SessionWithBadProfile())

        assert exc_info.value.code == 1
        assert "bogus" in capsys.readouterr().err


class TestWriteRows:
    """Tests for write_rows."""

    def test_csv_writes_header_and_rows(self, tmp_path):
        """write_rows in CSV mode writes the header followed by each row in fieldnames order."""
        path = tmp_path / "out.csv"
        rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]

        write_rows(str(path), rows, fieldnames=["a", "b"], fmt="csv")

        # read_text() applies universal-newline translation, so \r\n reads back as \n.
        assert path.read_text() == "a,b\n1,2\n3,4\n"

    def test_csv_empty_rows_writes_only_header(self, tmp_path):
        """write_rows in CSV mode with no rows still produces a valid header line."""
        path = tmp_path / "out.csv"

        write_rows(str(path), [], fieldnames=["a", "b"], fmt="csv")

        assert path.read_text() == "a,b\n"

    def test_json_writes_rows_as_a_list(self, tmp_path):
        """write_rows in JSON mode writes the rows as a JSON array, ignoring fieldnames order."""
        path = tmp_path / "out.json"
        rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]

        write_rows(str(path), rows, fieldnames=["a", "b"], fmt="json")

        assert json.loads(path.read_text()) == rows


class TestDefaultOutputPath:
    """Tests for default_output_path."""

    def test_appends_the_format_as_an_extension(self):
        """default_output_path joins the base name and format with a dot."""
        assert default_output_path("alarms", "csv") == "alarms.csv"
        assert default_output_path("alarms", "json") == "alarms.json"
