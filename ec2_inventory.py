#!/usr/bin/env python3
"""
EC2 Inventory — list instances, tags, state, and type across regions.

Usage:
    python ec2_inventory.py [--profile NAME] [--output ec2_inventory.csv] [--state running]
                            [--region us-east-1,eu-west-1] [--format csv|json]
"""

import argparse
import boto3
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from botocore.exceptions import ProfileNotFound

from common import default_output_path, resolve_regions, validate_session, write_rows


def _collect_region_instances(session: boto3.Session, state_filter: str | None, region: str) -> list[dict[str, str]]:
    """Collect EC2 instances for a single region, optionally filtered by state.

    If this region fails, report the error to stderr and return no rows
    without aborting the full scan.
    """
    rows: list[dict[str, str]] = []
    try:
        ec2 = session.client("ec2", region_name=region)
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate():
            for res in page["Reservations"]:
                for inst in res["Instances"]:
                    state = inst["State"]["Name"]
                    if state_filter and state != state_filter:
                        continue
                    tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                    rows.append({
                        "region": region,
                        "instance_id": inst["InstanceId"],
                        "state": state,
                        "type": inst["InstanceType"],
                        "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
                        "name": tags.get("Name", ""),
                        "owner": tags.get("Owner", tags.get("owner", "")),
                        "launch_time": inst["LaunchTime"].isoformat(),
                    })
    except Exception as e:
        print(f"  [{region}] skipped: {e}", file=sys.stderr)
    return rows


def main() -> None:
    """Parse CLI arguments, inventory EC2 instances across regions, and write a report."""
    p = argparse.ArgumentParser(description="EC2 inventory across regions")
    p.add_argument("--profile", default=None)
    p.add_argument("--output", default=None, help="Output path (default: ec2_inventory.csv/.json)")
    p.add_argument("--state", default=None, help="Filter by state, e.g. running")
    p.add_argument("--region", default=None, help="Comma-separated regions to scan (default: all enabled regions)")
    p.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format")
    args = p.parse_args()
    output = args.output or default_output_path("ec2_inventory", args.format)

    try:
        session = boto3.Session(profile_name=args.profile)
    except ProfileNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    validate_session(session)
    regions = resolve_regions(session, args.region)

    rows: list[dict[str, str]] = []
    if regions:
        worker = partial(_collect_region_instances, session, args.state)
        with ThreadPoolExecutor(max_workers=min(8, len(regions))) as pool:
            for region_rows in pool.map(worker, regions):
                rows.extend(region_rows)

    write_rows(
        output,
        sorted(rows, key=lambda r: (r["region"], r["state"], r["instance_id"])),
        fieldnames=["region", "instance_id", "state", "type", "az", "name", "owner", "launch_time"],
        fmt=args.format,
    )

    running = sum(1 for r in rows if r["state"] == "running")
    print(f"Wrote {output}: {len(rows)} instances ({running} running)")


if __name__ == "__main__":
    main()
