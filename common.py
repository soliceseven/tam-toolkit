"""Shared helpers used by the TAM Toolkit scripts."""

from __future__ import annotations

import csv
import json
import sys
from typing import Any

import boto3
from botocore.exceptions import ProfileNotFound


def get_all_regions(session: boto3.Session) -> list[str]:
    """Return the names of every AWS region enabled for the account."""
    ec2 = session.client("ec2", region_name="us-east-1")
    return [r["RegionName"] for r in ec2.describe_regions()["Regions"]]


def resolve_regions(session: boto3.Session, region_arg: str | None) -> list[str]:
    """Choose the regions to scan.

    Args:
        session: An authenticated boto3 Session. Use it to discover all
            enabled regions when ``region_arg`` is not given.
        region_arg: A comma-separated ``--region`` value, or None to scan
            every enabled region.

    Returns:
        The regions in ``region_arg`` if provided; otherwise, every region
        enabled for this account.
    """
    if region_arg:
        return [r.strip() for r in region_arg.split(",") if r.strip()]
    return get_all_regions(session)


def validate_session(session: boto3.Session) -> None:
    """Exit with a clear message if the session has no usable credentials.

    Otherwise, an invalid --profile or missing credentials would surface as
    a raw botocore stack trace on the first API call.
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


def spreadsheet_safe(value: Any) -> Any:
    """Prefix formula-leading CSV text so spreadsheets treat it as literal content."""
    if isinstance(value, str):
        leading = value.lstrip("".join(chr(i) for i in range(33)))
        if leading.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
    return value


def write_rows(path: str, rows: list[dict[str, Any]], fieldnames: list[str], fmt: str = "csv") -> None:
    """Write rows to ``path`` as CSV or JSON.

    Args:
        path: Output file path.
        rows: Records to write, in the given column order for CSV.
        fieldnames: CSV column order; ignored for JSON.
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
            w.writerows({key: spreadsheet_safe(value) for key, value in row.items()} for row in rows)


def default_output_path(base_name: str, fmt: str) -> str:
    """Build the default output path from ``base_name`` and ``fmt``.

    Args:
        base_name: File stem, e.g. "alarms".
        fmt: "csv" or "json".

    Returns:
        The path ``"{base_name}.{fmt}"``.
    """
    return f"{base_name}.{fmt}"
