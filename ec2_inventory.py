#!/usr/bin/env python3
"""
EC2 Inventory — instance list with tags, state, and type across all regions.

Usage:
    python ec2_inventory.py [--profile NAME] [--output ec2_inventory.csv] [--state running]
"""

import argparse
import boto3
import sys

from common import get_all_regions, write_csv


def main() -> None:
    """Parse CLI arguments, inventory EC2 instances across all regions, and write a CSV report."""
    p = argparse.ArgumentParser(description="EC2 inventory across regions")
    p.add_argument("--profile", default=None)
    p.add_argument("--output", default="ec2_inventory.csv")
    p.add_argument("--state", default=None, help="Filter by state, e.g. running")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile)
    regions = get_all_regions(session)

    rows = []
    for region in regions:
        try:
            ec2 = session.client("ec2", region_name=region)
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for res in page["Reservations"]:
                    for inst in res["Instances"]:
                        state = inst["State"]["Name"]
                        if args.state and state != args.state:
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

    write_csv(
        args.output,
        sorted(rows, key=lambda r: (r["region"], r["state"], r["instance_id"])),
        fieldnames=["region", "instance_id", "state", "type", "az", "name", "owner", "launch_time"],
    )

    running = sum(1 for r in rows if r["state"] == "running")
    print(f"Wrote {args.output}: {len(rows)} instances ({running} running)")


if __name__ == "__main__":
    main()
