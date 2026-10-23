#!/usr/bin/env python3
"""
S3 Bucket Audit — encryption, versioning, and public-access posture.

Usage:
    python s3_bucket_audit.py [--profile NAME] [--output s3_audit.csv]
"""

import argparse
import boto3
import sys

from common import write_csv


def main():
    p = argparse.ArgumentParser(description="S3 bucket security audit")
    p.add_argument("--profile", default=None)
    p.add_argument("--output", default="s3_audit.csv")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile)
    s3 = session.client("s3")

    buckets = s3.list_buckets()["Buckets"]
    print(f"Auditing {len(buckets)} buckets...")
    rows = []

    for b in buckets:
        name = b["Name"]
        row = {"bucket": name, "created": b["CreationDate"].isoformat(),
               "encryption": "UNKNOWN", "versioning": "UNKNOWN", "pab": "UNKNOWN", "issues": ""}

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

        issues = []
        if row["encryption"] == "DISABLED":
            issues.append("no-encryption")
        if row["versioning"] not in ("Enabled",):
            issues.append("versioning-off")
        if row["pab"] in ("NONE", "PARTIAL"):
            issues.append("public-access-risk")
        row["issues"] = ";".join(issues)

        rows.append(row)

    write_csv(
        args.output,
        sorted(rows, key=lambda r: (bool(r["issues"]), r["bucket"]), reverse=True),
        fieldnames=["bucket", "region", "created", "encryption", "versioning", "pab", "issues"],
    )

    risky = sum(1 for r in rows if r["issues"])
    print(f"Wrote {args.output}: {len(rows)} buckets, {risky} with findings")


if __name__ == "__main__":
    main()
