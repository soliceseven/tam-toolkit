"""Tests for cloudwatch_alarm_report module."""

import boto3
from botocore.stub import Stubber

import cloudwatch_alarm_report as script


class FakeSession:
    """Stand-in for boto3.Session returning a pre-built cloudwatch client per region."""

    def __init__(self, clients_by_region):
        self._clients_by_region = clients_by_region

    def client(self, service_name, region_name=None):
        assert service_name == "cloudwatch"
        return self._clients_by_region[region_name]


def _stubbed_cloudwatch(response):
    cw = boto3.client("cloudwatch", region_name="us-east-1")
    stubber = Stubber(cw)
    stubber.add_response("describe_alarms", response)
    stubber.activate()
    return cw


class TestCollectAlarms:
    """Tests for collect_alarms."""

    def test_builds_rows_from_metric_and_composite_alarms(self):
        """Metric and composite alarms are both turned into rows, composite without a metric."""
        cw = _stubbed_cloudwatch({
            "MetricAlarms": [{
                "AlarmName": "high-cpu",
                "StateValue": "ALARM",
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/EC2",
                "StateReason": "Threshold crossed",
            }],
            "CompositeAlarms": [{
                "AlarmName": "composite-1",
                "StateValue": "OK",
                "StateReason": "ok",
            }],
        })

        rows = script.collect_alarms(FakeSession({"us-east-1": cw}), ["us-east-1"])

        assert rows == [
            {
                "region": "us-east-1",
                "name": "high-cpu",
                "state": "ALARM",
                "metric": "CPUUtilization",
                "namespace": "AWS/EC2",
                "reason": "Threshold crossed",
            },
            {
                "region": "us-east-1",
                "name": "composite-1",
                "state": "OK",
                "metric": "composite",
                "namespace": "",
                "reason": "ok",
            },
        ]

    def test_truncates_state_reason_to_120_chars(self):
        """A long StateReason is truncated to 120 characters."""
        cw = _stubbed_cloudwatch({
            "MetricAlarms": [{"AlarmName": "a", "StateValue": "OK", "StateReason": "x" * 200}],
        })

        rows = script.collect_alarms(FakeSession({"us-east-1": cw}), ["us-east-1"])

        assert len(rows[0]["reason"]) == 120

    def test_skips_region_on_error_and_continues(self, capsys):
        """A failure in one region is reported but does not stop collection in others."""
        good_cw = _stubbed_cloudwatch({
            "MetricAlarms": [{"AlarmName": "ok-alarm", "StateValue": "OK", "StateReason": ""}],
        })

        class FailingThenGoodSession:
            def client(self, service_name, region_name=None):
                if region_name == "us-west-2":
                    raise RuntimeError("access denied")
                return good_cw

        rows = script.collect_alarms(FailingThenGoodSession(), ["us-west-2", "us-east-1"])

        assert rows == [{
            "region": "us-east-1",
            "name": "ok-alarm",
            "state": "OK",
            "metric": "composite",
            "namespace": "",
            "reason": "",
        }]
        assert "us-west-2" in capsys.readouterr().err


class TestMain:
    """Tests for main() end to end, with boto3 and region discovery mocked out."""

    def test_writes_csv_and_reports_firing_alarms(self, tmp_path, monkeypatch, capsys):
        """main() writes a CSV sorted with ALARM-state rows first and prints firing alarms."""
        cw = _stubbed_cloudwatch({
            "MetricAlarms": [
                {"AlarmName": "ok-alarm", "StateValue": "OK", "MetricName": "M1",
                 "Namespace": "NS", "StateReason": ""},
                {"AlarmName": "bad-alarm", "StateValue": "ALARM", "MetricName": "M2",
                 "Namespace": "NS", "StateReason": "too high"},
            ],
        })
        output = tmp_path / "alarms.csv"

        monkeypatch.setattr(script, "get_all_regions", lambda session: ["us-east-1"])
        monkeypatch.setattr(
            script.boto3, "Session",
            lambda profile_name=None: FakeSession({"us-east-1": cw}),
        )
        monkeypatch.setattr("sys.argv", ["prog", "--output", str(output)])

        script.main()

        rows = output.read_text().splitlines()
        assert rows[1].startswith("us-east-1,bad-alarm,ALARM")
        assert rows[2].startswith("us-east-1,ok-alarm,OK")

        out = capsys.readouterr().out
        assert "Found 2 alarms, 1 in ALARM state." in out
        assert "[us-east-1] bad-alarm — too high" in out
