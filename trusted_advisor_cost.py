#!/usr/bin/env python3
"""
Trusted Advisor Cost Optimization — report cost-saving opportunities.

Full Trusted Advisor checks require Business or Enterprise Support. On other
support plans, the script uses Cost Explorer's EC2 rightsizing
recommendations, which work on every support tier.

Usage:
    python trusted_advisor_cost.py [--profile NAME] [--output ta_cost.csv] [--format csv|json]
"""

import argparse
import boto3
import sys

from botocore.exceptions import ProfileNotFound

from common import default_output_path, validate_session, write_rows


COST_CHECK_NAMES = {
    "Low Utilization Amazon EC2 Instances",
    "Idle Load Balancers",
    "Underutilized Amazon EBS Volumes",
    "Unassociated Elastic IP Addresses",
    "Amazon RDS Idle DB Instances",
    "Low Utilization Amazon Redshift Clusters",
}


def _rightsizing_fallback(session: boto3.Session) -> list[dict[str, str]]:
    """Fetch EC2 rightsizing recommendations from Cost Explorer.

    Use this when the full Trusted Advisor check set is unavailable (Basic
    or Developer support). Cost Explorer's rightsizing recommendations cover
    EC2 only, unlike Trusted Advisor's broader check set, and require no
    special support tier.

    Returns:
        One row per flagged instance, shaped like a Trusted Advisor row
        (check/resource/region/estimated_monthly_savings).
    """
    ce = session.client("ce", region_name="us-east-1")
    rows: list[dict[str, str]] = []
    next_token = None
    while True:
        kwargs = {
            "Service": "AmazonEC2",
            "Configuration": {"BenefitsConsidered": False, "RecommendationTarget": "SAME_INSTANCE_FAMILY"},
        }
        if next_token:
            kwargs["NextPageToken"] = next_token
        resp = ce.get_rightsizing_recommendation(**kwargs)
        for rec in resp.get("RightsizingRecommendations", []):
            resource_id = rec.get("CurrentInstance", {}).get("ResourceId", "")
            if rec.get("RightsizingType") == "Terminate":
                savings = rec.get("TerminateRecommendationDetail", {}).get("EstimatedMonthlySavings", "")
            else:
                targets = rec.get("ModifyRecommendationDetail", {}).get("TargetInstances", [])
                default = next((t for t in targets if t.get("DefaultTargetInstance")), targets[0] if targets else {})
                savings = default.get("EstimatedMonthlySavings", "")
            rows.append({
                "check": "Cost Explorer Rightsizing (EC2)",
                "resource": resource_id,
                "region": "",
                "estimated_monthly_savings": savings,
            })
        next_token = resp.get("NextPageToken")
        if not next_token:
            break
    return rows


def main() -> None:
    """Parse CLI arguments, evaluate Trusted Advisor cost checks, and write a report.

    Use Cost Explorer rightsizing recommendations when the account's support
    plan does not include Trusted Advisor's full checks.
    """
    p = argparse.ArgumentParser(description="Trusted Advisor cost optimization report")
    p.add_argument("--profile", default=None)
    p.add_argument("--output", default=None, help="Output path (default: ta_cost.csv/.json)")
    p.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format")
    args = p.parse_args()
    output = args.output or default_output_path("ta_cost", args.format)

    try:
        session = boto3.Session(profile_name=args.profile)
    except ProfileNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    validate_session(session)
    ta = session.client("support", region_name="us-east-1")

    try:
        checks = ta.describe_trusted_advisor_checks(language="en")["checks"]
    except Exception as e:
        print(f"Cannot reach Trusted Advisor: {e}", file=sys.stderr)
        print("Falling back to Cost Explorer EC2 rightsizing recommendations...", file=sys.stderr)
        try:
            rows = _rightsizing_fallback(session)
        except Exception as fallback_error:
            print(f"Cost Explorer fallback also failed: {fallback_error}", file=sys.stderr)
            sys.exit(1)
        write_rows(output, rows, fieldnames=["check", "resource", "region", "estimated_monthly_savings"], fmt=args.format)
        print(f"Wrote {output}: {len(rows)} findings (Cost Explorer fallback, EC2 only)")
        return

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
            # Metadata fields have no labels and vary by check, so use the
            # largest dollar amount as a best-effort savings estimate.
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

    write_rows(output, rows, fieldnames=["check", "resource", "region", "estimated_monthly_savings"], fmt=args.format)

    print(f"\nWrote {output}: {len(rows)} findings, ~${total_savings:,.2f}/mo estimated savings")


if __name__ == "__main__":
    main()
