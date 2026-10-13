#!/usr/bin/env python3
"""
Support Case Summary — recent AWS Support cases by severity and status.

Usage:
    python support_case_summary.py [--profile NAME] [--days 30]
"""

import argparse
import boto3
import sys
from datetime import datetime, timedelta, timezone


def main():
    p = argparse.ArgumentParser(description="Summarize recent AWS Support cases")
    p.add_argument("--profile", default=None)
    p.add_argument("--days", type=int, default=30, help="Lookback window in days")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile)
    support = session.client("support", region_name="us-east-1")

    after = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    try:
        cases = support.describe_cases(
            includeResolvedCases=True,
            includeCommunications=False,
            afterTime=after,
        )["cases"]
    except Exception as e:
        print(f"Cannot reach AWS Support API: {e}", file=sys.stderr)
        sys.exit(1)

    if not cases:
        print(f"No cases in the last {args.days} days.")
        return

    by_severity, by_status = {}, {}
    for c in cases:
        by_severity[c.get("severityCode", "?")] = by_severity.get(c.get("severityCode", "?"), 0) + 1
        by_status[c.get("status", "?")] = by_status.get(c.get("status", "?"), 0) + 1

    print(f"\n{len(cases)} cases in the last {args.days} days\n")
    print("By severity:")
    for sev, n in sorted(by_severity.items()):
        print(f"  {sev:12s} {n}")
    print("\nBy status:")
    for st, n in sorted(by_status.items()):
        print(f"  {st:12s} {n}")

    open_cases = [c for c in cases if c.get("status") not in ("resolved", "closed")]
    if open_cases:
        print(f"\n{len(open_cases)} still open:")
        for c in sorted(open_cases, key=lambda x: x.get("timeCreated", ""), reverse=True)[:10]:
            print(f"  [{c.get('severityCode')}] {c.get('caseId')} — {c.get('subject','')[:70]}")


if __name__ == "__main__":
    main()
