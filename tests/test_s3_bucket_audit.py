"""Tests for s3_bucket_audit module."""

from datetime import datetime

import boto3
from botocore.stub import Stubber

import s3_bucket_audit as script


class FakeSession:
    """Stand-in for boto3.Session returning a pre-built s3 client."""

    def __init__(self, client):
        self._client = client

    def client(self, service_name, region_name=None):
        assert service_name == "s3"
        return self._client


def _bucket(name="my-bucket"):
    return {"Name": name, "CreationDate": datetime(2024, 1, 1)}


def _stub_happy_bucket(stubber, encryption=True, versioning="Enabled", pab_blocked=True):
    stubber.add_response("get_bucket_location", {"LocationConstraint": "eu-west-1"})
    if encryption:
        stubber.add_response("get_bucket_encryption", {
            "ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
        })
    else:
        stubber.add_client_error(
            "get_bucket_encryption",
            service_error_code="ServerSideEncryptionConfigurationNotFound",
        )
    stubber.add_response("get_bucket_versioning", {"Status": versioning})
    stubber.add_response("get_public_access_block", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": pab_blocked,
            "IgnorePublicAcls": pab_blocked,
            "BlockPublicPolicy": pab_blocked,
            "RestrictPublicBuckets": pab_blocked,
        },
    })


def _run_main(tmp_path, monkeypatch, s3_client, buckets):
    output = tmp_path / "s3_audit.csv"
    monkeypatch.setattr(s3_client, "list_buckets", lambda: {"Buckets": buckets})
    monkeypatch.setattr(script.boto3, "Session", lambda profile_name=None: FakeSession(s3_client))
    monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])
    script.main()
    return output


class TestMain:
    """Tests for main() end to end, with the S3 client stubbed via botocore.Stubber."""

    def test_clean_bucket_has_no_issues(self, tmp_path, monkeypatch):
        """A bucket with encryption, versioning, and full public-access block has no issues."""
        s3 = boto3.client("s3", region_name="us-east-1")
        stubber = Stubber(s3)
        _stub_happy_bucket(stubber)
        stubber.activate()

        output = _run_main(tmp_path, monkeypatch, s3, [_bucket("clean-bucket")])

        row = output.read_text().splitlines()[1]
        assert row == "clean-bucket,eu-west-1,2024-01-01T00:00:00,ENABLED,Enabled,FULL,"

    def test_risky_bucket_flags_all_issues(self, tmp_path, monkeypatch):
        """No encryption, no versioning, and no public-access block all surface as issues."""
        s3 = boto3.client("s3", region_name="us-east-1")
        stubber = Stubber(s3)
        stubber.add_response("get_bucket_location", {"LocationConstraint": ""})
        stubber.add_client_error(
            "get_bucket_encryption",
            service_error_code="ServerSideEncryptionConfigurationNotFound",
        )
        stubber.add_response("get_bucket_versioning", {})
        stubber.add_client_error("get_public_access_block", service_error_code="NoSuchPublicAccessBlockConfiguration")
        stubber.activate()

        output = _run_main(tmp_path, monkeypatch, s3, [_bucket("risky-bucket")])

        row = output.read_text().splitlines()[1]
        assert row.startswith("risky-bucket,us-east-1,2024-01-01T00:00:00,DISABLED,Suspended,NONE,")
        assert "no-encryption" in row
        assert "versioning-off" in row
        assert "public-access-risk" in row

    def test_unexpected_client_error_leaves_encryption_unknown(self, tmp_path, monkeypatch, capsys):
        """An error other than 'not found' is reported and does not look like 'disabled'."""
        s3 = boto3.client("s3", region_name="us-east-1")
        stubber = Stubber(s3)
        stubber.add_response("get_bucket_location", {"LocationConstraint": "eu-west-1"})
        stubber.add_client_error("get_bucket_encryption", service_error_code="AccessDenied")
        stubber.add_response("get_bucket_versioning", {"Status": "Enabled"})
        stubber.add_response("get_public_access_block", {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        })
        stubber.activate()

        output = _run_main(tmp_path, monkeypatch, s3, [_bucket("mystery-bucket")])

        row = output.read_text().splitlines()[1]
        assert ",UNKNOWN," in row
        assert "no-encryption" not in row
        assert "encryption check failed: AccessDenied" in capsys.readouterr().err

    def test_partial_public_access_block_flags_risk(self, tmp_path, monkeypatch):
        """A partially-configured public access block is flagged as a risk, not 'FULL'."""
        s3 = boto3.client("s3", region_name="us-east-1")
        stubber = Stubber(s3)
        stubber.add_response("get_bucket_location", {"LocationConstraint": "eu-west-1"})
        stubber.add_response("get_bucket_encryption", {
            "ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
        })
        stubber.add_response("get_bucket_versioning", {"Status": "Enabled"})
        stubber.add_response("get_public_access_block", {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": False,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        })
        stubber.activate()

        output = _run_main(tmp_path, monkeypatch, s3, [_bucket("partial-bucket")])

        row = output.read_text().splitlines()[1]
        assert ",PARTIAL," in row
        assert "public-access-risk" in row
