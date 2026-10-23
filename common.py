"""Shared helpers for the TAM toolkit scripts."""

from __future__ import annotations

import csv
from typing import Any

import boto3


def get_all_regions(session: boto3.Session) -> list[str]:
    """Return the names of all AWS regions enabled for this account."""
    ec2 = session.client("ec2", region_name="us-east-1")
    return [r["RegionName"] for r in ec2.describe_regions()["Regions"]]


def write_csv(path: str, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """Write rows to a CSV file at path using the given column order."""
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
