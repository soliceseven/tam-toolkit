#!/usr/bin/env python3
"""
Trusted Advisor Cost Optimization — surface savings opportunities.

Requires Business or Enterprise Support (Trusted Advisor full checks).
Usage:
    python trusted_advisor_cost.py [--profile NAME] [--output ta_cost.csv]
"""

import argparse
import boto3
import sys

from common import write_csv


COST_CHECK_NAMES = {
    "Low Utilization Amazon EC2 Instances",
    "Idle Load Balancers",
    "Underutilized Amazon EBS Volumes",
    "Unassociated Elastic IP Addresses",
    "Amazon RDS Idle DB Instances",
    "Low Utilization Amazon Redshift Clusters",
}


def main() -> None:
    """Parse CLI arguments, evaluate Trusted Advisor cost checks, and write a CSV of findings.

    Requires Business or Enterprise Support, since full Trusted Advisor
    checks are not available on Basic/Developer support plans.
    """
    p = argparse.ArgumentParser(description="Trusted Advisor cost optimization report")
    p.add_argument("--profile", default=None)
    p.add_argument("--output", default="ta_cost.csv")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile)
    ta = session.client("support", region_name="us-east-1")

    try:
        checks = ta.describe_trusted_advisor_checks(language="en")["checks"]
    except Exception as e:
        print(f"Cannot reach Trusted Advisor: {e}", file=sys.stderr)
        print("Note: full Trusted Advisor checks require Business or Enterprise Support.", file=sys.stderr)
        sys.exit(1)

    cost_checks = [c for c in checks if c["name"] in COST_CHECK_NAMES or "cost" in c["category"].lower()]
    print(f"Evaluating {len(cost_checks)} cost-related checks...")

    rows = []
    total_savings = 0.0
    for check in cost_checks:
        try:
            result = ta.describe_trusted_advisor_check_result(checkId=check["id"], language="en")["result"]
        except Exception as e:
            print(f"  [{check['name']}] skipped: {e}", file=sys.stderr)
            continue
        flagged = result.get("resourcesSummary", {}).get("resourcesFlagged", 0)
        for res in result.get("flaggedResources", []):
            # Metadata fields are unlabeled and vary by check, so we take the largest
            # dollar figure present as a best-effort savings estimate.
            savings = 0.0
            for meta in res.get("metadata", []):
                cleaned = meta.replace("$", "").replace(",", "").strip()
                try:
                    val = float(cleaned)
                    if val > savings:
                        savings = val
                except ValueError:
                    pass
            total_savings += savings
            rows.append({
                "check": check["name"],
                "resource": res.get("resourceId", ""),
                "region": res.get("region", ""),
                "estimated_monthly_savings": f"{savings:.2f}" if savings else "",
            })
        print(f"  [{check['name']}] {flagged} flagged")

    write_csv(args.output, rows, fieldnames=["check", "resource", "region", "estimated_monthly_savings"])

    print(f"\nWrote {args.output}: {len(rows)} findings, ~${total_savings:,.2f}/mo estimated savings")


if __name__ == "__main__":
    main()
