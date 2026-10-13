#!/usr/bin/env python3
"""
EC2 Inventory — instance list with tags, state, and type across all regions.

Usage:
    python ec2_inventory.py [--profile NAME] [--output ec2_inventory.csv] [--state running]
"""

import argparse
import boto3
import csv
import sys


def main():
    p = argparse.ArgumentParser(description="EC2 inventory across regions")
    p.add_argument("--profile", default=None)
    p.add_argument("--output", default="ec2_inventory.csv")
    p.add_argument("--state", default=None, help="Filter by state, e.g. running")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile)
    ec2_global = session.client("ec2", region_name="us-east-1")
    regions = [r["RegionName"] for r in ec2_global.describe_regions()["Regions"]]

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

    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["region", "instance_id", "state", "type", "az", "name", "owner", "launch_time"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["region"], r["state"], r["instance_id"])))

    running = sum(1 for r in rows if r["state"] == "running")
    print(f"Wrote {args.output}: {len(rows)} instances ({running} running)")


if __name__ == "__main__":
    main()
