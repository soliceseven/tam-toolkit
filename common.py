"""Shared helpers for the TAM toolkit scripts."""

from __future__ import annotations

import csv
import json
import sys
from typing import Any

import boto3
from botocore.exceptions import ProfileNotFound


def get_all_regions(session: boto3.Session) -> list[str]:
    """Return the names of all AWS regions enabled for this account."""
    ec2 = session.client("ec2", region_name="us-east-1")
    return [r["RegionName"] for r in ec2.describe_regions()["Regions"]]


def resolve_regions(session: boto3.Session, region_arg: str | None) -> list[str]:
    """Return the regions to scan.

    Args:
        session: An authenticated boto3 Session, used to discover all enabled
            regions when ``region_arg`` is not given.
        region_arg: A comma-separated ``--region`` value, or None to scan
            every enabled region.

    Returns:
        The explicit region list from ``region_arg`` if provided, otherwise
        every region enabled for this account.
    """
    if region_arg:
        return [r.strip() for r in region_arg.split(",") if r.strip()]
    return get_all_regions(session)


def validate_session(session: boto3.Session) -> None:
    """Fail fast with a clear message if the session has no usable credentials.

    Without this, an invalid --profile or missing credentials would only
    surface as a raw botocore stack trace from the first API call.
    """
    try:
        if session.get_credentials() is None:
            print(
                "Error: no AWS credentials found. Run 'aws configure' or pass --profile.",
                file=sys.stderr,
            )
            sys.exit(1)
    except ProfileNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def write_rows(path: str, rows: list[dict[str, Any]], fieldnames: list[str], fmt: str = "csv") -> None:
    """Write rows to path as CSV or JSON.

    Args:
        path: Output file path.
        rows: The records to write, in the given column order for CSV.
        fieldnames: Column order (CSV only; ignored for JSON).
        fmt: "csv" (default) or "json".
    """
    if fmt == "json":
        with open(path, "w") as f:
            json.dump(rows, f, indent=2, default=str)
            f.write("\n")
    else:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)


def default_output_path(base_name: str, fmt: str) -> str:
    """Return the default output path for base_name under the given format.

    Args:
        base_name: File stem, e.g. "alarms".
        fmt: "csv" or "json".

    Returns:
        "{base_name}.{fmt}".
    """
    return f"{base_name}.{fmt}"
