#!/usr/bin/env python3
"""
Cost Anomaly Check — flag unusual daily spend via Cost Explorer.

Usage:
    python cost_anomaly_check.py [--profile NAME] [--days 14] [--threshold 1.5]
"""

import argparse
import boto3
import sys
from datetime import date, timedelta

from botocore.exceptions import ProfileNotFound

from common import validate_session


def main() -> None:
    """Parse CLI arguments, pull daily Cost Explorer spend, and flag anomalous days.

    Compares each day's spend against the trailing average of all prior days
    in the window and prints any day whose spend is at least
    ``--threshold`` times that average.
    """
    p = argparse.ArgumentParser(description="Flag unusual AWS daily spend")
    p.add_argument("--profile", default=None)
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--threshold", type=float, default=1.5,
                   help="Flag days spending >= threshold x trailing average")
    args = p.parse_args()

    try:
        session = boto3.Session(profile_name=args.profile)
    except ProfileNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    validate_session(session)
    ce = session.client("ce", region_name="us-east-1")

    end = date.today().isoformat()
    start = (date.today() - timedelta(days=args.days)).isoformat()

    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
        )
    except Exception as e:
        print(f"Cannot reach Cost Explorer: {e}", file=sys.stderr)
        sys.exit(1)

    daily = []
    for r in resp["ResultsByTime"]:
        amt = float(r["Total"]["UnblendedCost"]["Amount"])
        daily.append((r["TimePeriod"]["Start"], amt))

    if len(daily) < 3:
        print("Not enough data.")
        return

    baseline = sum(a for _, a in daily[:-1]) / (len(daily) - 1)
    print(f"Trailing {len(daily)-1}-day average: ${baseline:,.2f}/day\n")

    flagged = [(d, a) for d, a in daily if baseline > 0 and a >= baseline * args.threshold]
    if not flagged:
        print("No anomalies detected.")
        return

    print("Flagged days:")
    for d, a in flagged:
        pct = (a / baseline - 1) * 100
        print(f"  {d}  ${a:,.2f}  (+{pct:.0f}% vs average)")


if __name__ == "__main__":
    main()
