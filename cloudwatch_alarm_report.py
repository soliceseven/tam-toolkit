#!/usr/bin/env python3
"""
CloudWatch Alarm Report — pull all alarms across regions, flag ALARM state.

Usage:
    python cloudwatch_alarm_report.py [--profile NAME] [--output alarms.csv]
"""

import argparse
import boto3
import csv
import sys
from datetime import datetime


def get_all_regions(session):
    ec2 = session.client("ec2", region_name="us-east-1")
    return [r["RegionName"] for r in ec2.describe_regions()["Regions"]]


def collect_alarms(session, regions):
    rows = []
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


def main():
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

    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["region", "name", "state", "metric", "namespace", "reason"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["state"] != "ALARM", r["region"], r["name"])))

    print(f"Wrote {args.output} at {datetime.utcnow().isoformat()}Z")
    if in_alarm:
        print("\nAlarms currently firing:")
        for r in in_alarm:
            print(f"  [{r['region']}] {r['name']} — {r['reason']}")


if __name__ == "__main__":
    main()
