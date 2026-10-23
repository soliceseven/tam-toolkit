#!/usr/bin/env python3
"""
CloudWatch Alarm Report — collect alarms across regions and flag ALARM states.

Usage:
    python cloudwatch_alarm_report.py [--profile NAME] [--output alarms.csv]
                                      [--region us-east-1,eu-west-1] [--format csv|json]
"""

import argparse
import boto3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial

from botocore.exceptions import ProfileNotFound

from common import default_output_path, resolve_regions, validate_session, write_rows


def _collect_region_alarms(session: boto3.Session, region: str) -> list[dict[str, str]]:
    """Collect metric and composite CloudWatch alarms for a single region.

    If this region fails, report the error to stderr and return no rows
    without aborting the full scan.
    """
    rows: list[dict[str, str]] = []
    try:
        cw = session.client("cloudwatch", region_name=region)
        paginator = cw.get_paginator("describe_alarms")
        for page in paginator.paginate():
            for alarm in page.get("MetricAlarms", []):
                rows.append({
                    "region": region,
                    "name": alarm["AlarmName"],
                    "state": alarm["StateValue"],
                    "metric": alarm.get("MetricName", "composite"),
                    "namespace": alarm.get("Namespace", ""),
                    "reason": alarm.get("StateReason", "")[:120],
                })
            for alarm in page.get("CompositeAlarms", []):
                rows.append({
                    "region": region,
                    "name": alarm["AlarmName"],
                    "state": alarm["StateValue"],
                    "metric": "composite",
                    "namespace": "",
                    "reason": alarm.get("StateReason", "")[:120],
                })
    except Exception as e:
        print(f"  [{region}] skipped: {e}", file=sys.stderr)
    return rows


def collect_alarms(session: boto3.Session, regions: list[str]) -> list[dict[str, str]]:
    """Collect metric and composite CloudWatch alarms in the given regions.

    Scan regions concurrently because each API call is independent and
    I/O-bound.

    Args:
        session: An authenticated boto3 Session for creating a CloudWatch
            client in each region.
        regions: AWS region names to scan for alarms.

    Returns:
        One row per alarm with its region, name, state, metric, namespace,
        and state reason truncated to 120 characters. If a region raises an
        error, skip it and report the error to stderr; continue the scan.
    """
    if not regions:
        return []
    rows: list[dict[str, str]] = []
    worker = partial(_collect_region_alarms, session)
    with ThreadPoolExecutor(max_workers=min(8, len(regions))) as pool:
        for region_rows in pool.map(worker, regions):
            rows.extend(region_rows)
    return rows


def main() -> None:
    """Parse CLI arguments, scan regions for alarms, and write a report."""
    p = argparse.ArgumentParser(description="CloudWatch alarm report across regions")
    p.add_argument("--profile", default=None, help="AWS CLI profile name")
    p.add_argument("--output", default=None, help="Output path (default: alarms.csv/.json)")
    p.add_argument("--region", default=None, help="Comma-separated regions to scan (default: all enabled regions)")
    p.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format")
    args = p.parse_args()
    output = args.output or default_output_path("alarms", args.format)

    try:
        session = boto3.Session(profile_name=args.profile)
    except ProfileNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    validate_session(session)
    regions = resolve_regions(session, args.region)
    print(f"Scanning {len(regions)} regions...")

    rows = collect_alarms(session, regions)
    in_alarm = [r for r in rows if r["state"] == "ALARM"]
    print(f"Found {len(rows)} alarms, {len(in_alarm)} in ALARM state.")

    write_rows(
        output,
        sorted(rows, key=lambda r: (r["state"] != "ALARM", r["region"], r["name"])),
        fieldnames=["region", "name", "state", "metric", "namespace", "reason"],
        fmt=args.format,
    )

    print(f"Wrote {output} at {datetime.now(timezone.utc).isoformat()}")
    if in_alarm:
        print("\nAlarms currently firing:")
        for r in in_alarm:
            print(f"  [{r['region']}] {r['name']} - {r['reason']}")


if __name__ == "__main__":
    main()
