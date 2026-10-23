#!/usr/bin/env python3
"""
CloudWatch Alarm Report — pull all alarms across regions, flag ALARM state.

Usage:
    python cloudwatch_alarm_report.py [--profile NAME] [--output alarms.csv]
"""

import argparse
import boto3
import sys
from datetime import datetime, timezone

from common import get_all_regions, write_csv


def collect_alarms(session: boto3.Session, regions: list[str]) -> list[dict[str, str]]:
    """Collect metric and composite CloudWatch alarms across the given regions.

    Args:
        session: An authenticated boto3 Session used to create a per-region
            CloudWatch client.
        regions: AWS region names to scan for alarms.

    Returns:
        One row per alarm, each with region, name, state, metric, namespace,
        and a state reason truncated to 120 characters. A region that raises
        an error is skipped and reported to stderr rather than aborting the
        whole scan.
    """
    rows: list[dict[str, str]] = []
    for region in regions:
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


def main() -> None:
    """Parse CLI arguments, scan all regions for alarms, and write a CSV report."""
    p = argparse.ArgumentParser(description="CloudWatch alarm report across regions")
    p.add_argument("--profile", default=None, help="AWS CLI profile name")
    p.add_argument("--output", default="alarms.csv", help="CSV output path")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile)
    regions = get_all_regions(session)
    print(f"Scanning {len(regions)} regions...")

    rows = collect_alarms(session, regions)
    in_alarm = [r for r in rows if r["state"] == "ALARM"]
    print(f"Found {len(rows)} alarms, {len(in_alarm)} in ALARM state.")

    write_csv(
        args.output,
        sorted(rows, key=lambda r: (r["state"] != "ALARM", r["region"], r["name"])),
        fieldnames=["region", "name", "state", "metric", "namespace", "reason"],
    )

    print(f"Wrote {args.output} at {datetime.now(timezone.utc).isoformat()}")
    if in_alarm:
        print("\nAlarms currently firing:")
        for r in in_alarm:
            print(f"  [{r['region']}] {r['name']} — {r['reason']}")


if __name__ == "__main__":
    main()
