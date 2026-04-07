"""
remediation_handler.py
AWS Lambda function for auto-remediation of CloudWatch alarms.
Triggered by EventBridge rules wired to CloudWatch alarm state changes.

Supported remediation actions:
  - ECS service scale-out (CPU high / task count low)
  - ECS force new deployment (task failures)
  - SNS notification (RDS connection saturation)
  - CloudWatch custom metric logging
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ecs = boto3.client("ecs")
sns = boto3.client("sns")
cw = boto3.client("cloudwatch")

SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
ECS_CLUSTER = os.environ.get("ECS_CLUSTER_NAME", "infra-agent-cluster")


def handler(event: dict, context: Any) -> dict:
    """
    Main Lambda handler. Receives EventBridge events from CloudWatch alarms.

    Event structure:
        {
          "detail-type": "CloudWatch Alarm State Change",
          "detail": {
            "alarmName": "ecs-cpu-high-my-api-staging",
            "state": { "value": "ALARM" },
            "configuration": { ... }
          }
        }
    """
    logger.info(f"Received event: {json.dumps(event)}")

    detail = event.get("detail", {})
    alarm_name: str = detail.get("alarmName", "")
    state: str = detail.get("state", {}).get("value", "")

    if state != "ALARM":
        logger.info(f"Alarm {alarm_name} state is {state} — no action needed")
        return {"status": "skipped", "reason": f"state={state}"}

    remediation_rules = {
        "ecs-cpu-high": _scale_out,
        "ecs-task-count-low": _force_redeploy,
        "ecs-memory-high": _scale_out,
        "rds-connections-high": _notify_only,
    }

    action_fn = None
    matched_rule = None
    for rule_prefix, fn in remediation_rules.items():
        if alarm_name.startswith(rule_prefix):
            action_fn = fn
            matched_rule = rule_prefix
            break

    if not action_fn:
        logger.warning(f"No remediation rule matched for alarm: {alarm_name}")
        return {"status": "no_match", "alarm": alarm_name}

    parts = alarm_name.split("-")
    rule_parts = matched_rule.split("-")
    service_name = parts[len(rule_parts)] if len(parts) > len(rule_parts) else "unknown"

    logger.info(f"Executing remediation '{matched_rule}' for service '{service_name}'")

    try:
        result = action_fn(alarm_name=alarm_name, service_name=service_name)
        _log_remediation_metric(alarm_name, matched_rule, success=True)
        _notify_only(alarm_name=alarm_name, service_name=service_name)
        return {"status": "remediated", "action": matched_rule, "result": result}

    except Exception as e:
        logger.error(f"Remediation failed for {alarm_name}: {e}")
        _log_remediation_metric(alarm_name, matched_rule, success=False)
        raise


def _scale_out(alarm_name: str, service_name: str) -> dict:
    """Scale ECS service out by 2 tasks, up to max_tasks."""
    response = ecs.describe_services(
        cluster=ECS_CLUSTER,
        services=[service_name],
    )

    if not response["services"]:
        raise ValueError(
            f"ECS service '{service_name}' not found in cluster '{ECS_CLUSTER}'"
        )

    service = response["services"][0]
    current = service["desiredCount"]
    new_count = min(current + 2, int(os.environ.get("MAX_TASKS", "10")))

    if new_count == current:
        logger.info(f"Service {service_name} already at max tasks ({current})")
        return {"action": "scale_out", "skipped": True, "reason": "already_at_max"}

    ecs.update_service(
        cluster=ECS_CLUSTER,
        service=service_name,
        desiredCount=new_count,
    )

    logger.info(f"Scaled {service_name}: {current} → {new_count} tasks")
    return {"action": "scale_out", "previous": current, "new": new_count}


def _force_redeploy(alarm_name: str, service_name: str) -> dict:
    """Force a new ECS deployment to replace unhealthy tasks."""
    ecs.update_service(
        cluster=ECS_CLUSTER,
        service=service_name,
        forceNewDeployment=True,
    )
    logger.info(f"Forced new deployment for {service_name}")
    return {"action": "force_redeploy", "service": service_name}


def _notify_only(alarm_name: str, service_name: str) -> dict:
    """Send SNS notification without modifying infrastructure."""
    if not SNS_TOPIC_ARN:
        logger.warning("SNS_TOPIC_ARN not configured — skipping notification")
        return {"action": "notify", "skipped": True}

    message = {
        "alarm": alarm_name,
        "service": service_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": f"Alarm {alarm_name} triggered for {service_name}. Manual review required.",
    }

    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"[infra-agent] Alarm: {alarm_name}",
        Message=json.dumps(message, indent=2),
    )

    logger.info(f"SNS notification sent for {alarm_name}")
    return {"action": "notify", "topic": SNS_TOPIC_ARN}


def _log_remediation_metric(alarm_name: str, action: str, success: bool) -> None:
    """Publish a custom CloudWatch metric for remediation tracking."""
    try:
        cw.put_metric_data(
            Namespace="InfraAgent/Remediation",
            MetricData=[
                {
                    "MetricName": "RemediationAttempt",
                    "Dimensions": [
                        {"Name": "AlarmName", "Value": alarm_name},
                        {"Name": "Action", "Value": action},
                        {"Name": "Success", "Value": str(success)},
                    ],
                    "Value": 1,
                    "Unit": "Count",
                    "Timestamp": datetime.now(timezone.utc),
                }
            ],
        )
    except Exception as e:
        logger.warning(f"Failed to publish remediation metric: {e}")
