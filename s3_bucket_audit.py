#!/usr/bin/env python3
"""
S3 Bucket Audit — check encryption, versioning, and public access.

Usage:
    python s3_bucket_audit.py [--profile NAME] [--output s3_audit.csv] [--format csv|json]
"""

import argparse
import boto3
import sys

from botocore.exceptions import ProfileNotFound

from common import default_output_path, validate_session, write_rows


def main() -> None:
    """Parse CLI arguments, check each S3 bucket's security settings, and write a report.

    Report three findings per bucket: default encryption is disabled,
    versioning is not enabled, or the bucket has public-access risk. Flag
    public-access risk if the public-access-block configuration is not fully
    locked down or the authoritative bucket policy status
    (``get_bucket_policy_status``) reports that the bucket is public.
    """
    p = argparse.ArgumentParser(description="S3 bucket security audit")
    p.add_argument("--profile", default=None)
    p.add_argument("--output", default=None, help="Output path (default: s3_audit.csv/.json)")
    p.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format")
    args = p.parse_args()
    output = args.output or default_output_path("s3_audit", args.format)

    try:
        session = boto3.Session(profile_name=args.profile)
    except ProfileNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    validate_session(session)
    s3 = session.client("s3")

    buckets = s3.list_buckets()["Buckets"]
    print(f"Auditing {len(buckets)} buckets...")
    rows = []

    for b in buckets:
        name = b["Name"]
        row = {"bucket": name, "created": b["CreationDate"].isoformat(),
               "encryption": "UNKNOWN", "versioning": "UNKNOWN", "pab": "UNKNOWN",
               "public": "UNKNOWN", "issues": ""}

        try:
            loc = s3.get_bucket_location(Bucket=name)["LocationConstraint"] or "us-east-1"
            row["region"] = loc
        except Exception:
            row["region"] = "?"

        try:
            s3.get_bucket_encryption(Bucket=name)
            row["encryption"] = "ENABLED"
        except s3.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ServerSideEncryptionConfigurationNotFound":
                row["encryption"] = "DISABLED"
            else:
                print(f"  [{name}] encryption check failed: {code}", file=sys.stderr)

        try:
            v = s3.get_bucket_versioning(Bucket=name).get("Status", "Suspended")
            row["versioning"] = v
        except s3.exceptions.ClientError as e:
            print(f"  [{name}] versioning check failed: {e.response['Error']['Code']}", file=sys.stderr)

        try:
            pab = s3.get_public_access_block(Bucket=name)["PublicAccessBlockConfiguration"]
            blocked = all(pab.get(k) for k in ("BlockPublicAcls", "BlockPublicPolicy",
                                                "IgnorePublicAcls", "RestrictPublicBuckets"))
            row["pab"] = "FULL" if blocked else "PARTIAL"
        except s3.exceptions.ClientError:
            row["pab"] = "NONE"

        try:
            is_public = s3.get_bucket_policy_status(Bucket=name)["PolicyStatus"]["IsPublic"]
            row["public"] = "TRUE" if is_public else "FALSE"
        except s3.exceptions.ClientError as e:
            print(f"  [{name}] policy status check failed: {e.response['Error']['Code']}", file=sys.stderr)

        issues = []
        if row["encryption"] == "DISABLED":
            issues.append("no-encryption")
        if row["versioning"] not in ("Enabled",):
            issues.append("versioning-off")
        if row["public"] == "TRUE" or row["pab"] in ("NONE", "PARTIAL"):
            issues.append("public-access-risk")
        row["issues"] = ";".join(issues)

        rows.append(row)

    write_rows(
        output,
        sorted(rows, key=lambda r: (bool(r["issues"]), r["bucket"]), reverse=True),
        fieldnames=["bucket", "region", "created", "encryption", "versioning", "pab", "public", "issues"],
        fmt=args.format,
    )

    risky = sum(1 for r in rows if r["issues"])
    print(f"Wrote {output}: {len(rows)} buckets, {risky} with findings")


if __name__ == "__main__":
    main()
