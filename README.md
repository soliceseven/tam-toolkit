# TAM Toolkit

Practical Python/boto3 scripts that turn routine AWS account-health checks into one-command CSV reports, for AWS Technical Account Managers and anyone else running Enterprise Support-style reviews.

## Overview

Each script wraps a handful of boto3 calls (scanning all regions, pulling Cost Explorer or Trusted Advisor data, auditing S3 posture) into a single CLI command that prints a summary and writes a CSV you can drop into a review doc. There's no framework, no config file, and no shared state between scripts: pick the one you need and run it against a profile.

## Scripts

| Script | What it does |
|--------|--------------|
| `cloudwatch_alarm_report.py` | Pulls all CloudWatch alarms across regions (scanned in parallel), flags `ALARM` state |
| `trusted_advisor_cost.py` | Checks Trusted Advisor for cost-optimization findings; falls back to Cost Explorer rightsizing recommendations on support plans without full Trusted Advisor checks |
| `ec2_inventory.py` | EC2 inventory with tags, state, and type across all regions (scanned in parallel) |
| `s3_bucket_audit.py` | S3 security audit: encryption, versioning, public access (via both the public-access-block config and the authoritative bucket policy status) |
| `support_case_summary.py` | Summarizes recent AWS Support cases by severity and status |
| `cost_anomaly_check.py` | Flags unusual daily spend using Cost Explorer |

## Installation

### Prerequisites

- Python 3.9 or higher
- boto3 1.34 or higher
- AWS credentials configured, via `aws configure` or an IAM role

### Quick Install

```bash
git clone https://github.com/soliceseven/tam-toolkit.git
cd tam-toolkit
pip install boto3
```

### Verification

```bash
python3 ec2_inventory.py --help
# Expected output:
# usage: ec2_inventory.py [-h] [--profile PROFILE] [--output OUTPUT]
#                         [--state STATE] [--region REGION]
#                         [--format {csv,json}]
```

## Quick Start

```bash
# Inventory every running EC2 instance across all regions
python3 ec2_inventory.py --profile my-aws-profile --state running

# Wrote ec2_inventory.csv: 42 instances (42 running)
```

Open `ec2_inventory.csv` to see instance ID, region, type, tags, and launch time for every match.

## Usage

### Common flags

- `--profile NAME`: AWS CLI profile to use (all scripts; omit to use the default credential chain). An invalid profile or missing credentials fails fast with a clear message instead of a raw stack trace.
- `--output PATH`: output file path (`cloudwatch_alarm_report.py`, `ec2_inventory.py`, `s3_bucket_audit.py`, `trusted_advisor_cost.py`). Defaults to `<name>.csv` or `<name>.json` depending on `--format`.
- `--format {csv,json}`: output format for the same four scripts (default `csv`).
- `--region R1,R2`: comma-separated regions to scan (`cloudwatch_alarm_report.py`, `ec2_inventory.py`). Omit to scan every region enabled for the account; regions are scanned in parallel either way.

`cost_anomaly_check.py` and `support_case_summary.py` print directly to the terminal and don't take `--output`/`--format`/`--region`. Run any script with `--help` for its full flag list.

### Examples

```bash
# Flag CloudWatch alarms currently firing, across every enabled region
python3 cloudwatch_alarm_report.py --profile my-aws-profile --output alarms.csv

# Same, but limited to two regions and as JSON
python3 cloudwatch_alarm_report.py --profile my-aws-profile --region us-east-1,eu-west-1 --format json

# Surface Trusted Advisor cost-optimization findings; falls back to Cost
# Explorer EC2 rightsizing recommendations on Basic/Developer support
python3 trusted_advisor_cost.py --profile my-aws-profile --output ta_cost.csv

# Audit S3 buckets for encryption, versioning, and public-access risk
python3 s3_bucket_audit.py --profile my-aws-profile --output s3_audit.csv

# Flag days where spend is 2x the trailing 30-day average
python3 cost_anomaly_check.py --profile my-aws-profile --days 30 --threshold 2.0

# Summarize AWS Support cases opened in the last 7 days
python3 support_case_summary.py --profile my-aws-profile --days 7
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The test suite stubs every AWS call with `botocore.stub.Stubber`, so it runs without real credentials or network access. It also runs on every push and pull request via GitHub Actions (`.github/workflows/tests.yml`), across Python 3.9, 3.11, and 3.13.

## Why this exists

As a TAM, you're the customer's operational conscience. These scripts turn hours of console-clicking into minutes of automated reporting, the kind of proactive work that prevents Sev-1s instead of reacting to them.
