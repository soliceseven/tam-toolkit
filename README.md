# TAM Toolkit

Practical Python/Boto3 scripts for AWS Technical Account Managers. Built from real Enterprise Support workflows — CloudWatch monitoring, Trusted Advisor cost optimization, S3 audits, and operational reporting.

## Scripts

| Script | What it does |
|--------|--------------|
| `cloudwatch_alarm_report.py` | Pulls all CloudWatch alarms across regions, flags ALARM state, exports CSV |
| `trusted_advisor_cost.py` | Checks Trusted Advisor for cost-optimization findings, estimates savings |
| `ec2_inventory.py` | EC2 inventory with tags, state, and type across all regions |
| `s3_bucket_audit.py` | S3 security audit — encryption, versioning, public access blocks |
| `support_case_summary.py` | Summarizes recent AWS Support cases by severity and status |
| `cost_anomaly_check.py` | Flags unusual spend using Cost Explorer |

## Setup

```bash
pip install boto3
aws configure  # or use IAM role
```

Each script accepts `--profile` and `--output` flags. Run with `--help` for options.

## Why this exists

As a TAM, you're the customer's operational conscience. These scripts turn hours of console-clicking into minutes of automated reporting — the kind of proactive work that prevents Sev-1s instead of reacting to them.
