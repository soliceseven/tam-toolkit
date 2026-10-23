"""Tests for the common module (shared region discovery and CSV helpers)."""

import boto3
from botocore.stub import Stubber

from common import get_all_regions, write_csv


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


def test_write_csv_writes_header_and_rows(tmp_path):
    """write_csv writes the header followed by each row in fieldnames order."""
    path = tmp_path / "out.csv"
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]

    write_csv(str(path), rows, fieldnames=["a", "b"])

    # read_text() applies universal-newline translation, so \r\n reads back as \n.
    assert path.read_text() == "a,b\n1,2\n3,4\n"


def test_write_csv_empty_rows_writes_only_header(tmp_path):
    """write_csv with no rows still produces a valid CSV header line."""
    path = tmp_path / "out.csv"

    write_csv(str(path), [], fieldnames=["a", "b"])

    assert path.read_text() == "a,b\n"
