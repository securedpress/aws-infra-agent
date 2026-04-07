"""
test_intent_parser.py
Unit tests for the IntentParser.
Bedrock calls are mocked — no AWS credentials required.
"""

import pytest
from unittest.mock import MagicMock
from agent.intent_parser import IntentParser, InfraIntent

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_bedrock():
    """Returns a mocked BedrockClient."""
    client = MagicMock()
    return client


@pytest.fixture
def parser(mock_bedrock):
    return IntentParser(bedrock_client=mock_bedrock)


# ── IntentParser tests ────────────────────────────────────────────────────────


def test_parse_ecs_fargate_with_rds(parser, mock_bedrock):
    """Should correctly parse an ECS + RDS request."""
    mock_bedrock.invoke_json.return_value = {
        "service_type": "ecs-fargate",
        "database_type": "rds-postgres",
        "environment": "staging",
        "min_tasks": 1,
        "max_tasks": 4,
        "cpu": 512,
        "memory": 1024,
        "enable_alb": True,
        "enable_cloudwatch_alarms": True,
        "enable_autoscaling": True,
        "multi_az": False,
        "instance_class": "db.t3.micro",
        "additional_notes": "",
    }

    intent = parser.parse("deploy an ECS Fargate API with RDS PostgreSQL in staging")

    assert intent.service_type == "ecs-fargate"
    assert intent.database_type == "rds-postgres"
    assert intent.environment == "staging"
    assert intent.min_tasks == 1
    assert intent.max_tasks == 4
    assert intent.cpu == 512
    assert intent.memory == 1024
    assert intent.multi_az is False


def test_parse_production_sets_multi_az(parser, mock_bedrock):
    """Production environment should have multi_az True."""
    mock_bedrock.invoke_json.return_value = {
        "service_type": "ecs-fargate",
        "database_type": "rds-postgres",
        "environment": "production",
        "min_tasks": 2,
        "max_tasks": 10,
        "cpu": 1024,
        "memory": 2048,
        "enable_alb": True,
        "enable_cloudwatch_alarms": True,
        "enable_autoscaling": True,
        "multi_az": True,
        "instance_class": "db.t3.medium",
        "additional_notes": "",
    }

    intent = parser.parse("production ECS service autoscaling 2-10 tasks")

    assert intent.environment == "production"
    assert intent.multi_az is True
    assert intent.min_tasks == 2
    assert intent.max_tasks == 10


def test_parse_stores_raw_prompt(parser, mock_bedrock):
    """InfraIntent should store the original prompt."""
    mock_bedrock.invoke_json.return_value = {
        "service_type": "ecs-fargate",
        "database_type": None,
        "environment": "dev",
        "min_tasks": 1,
        "max_tasks": 2,
        "cpu": 256,
        "memory": 512,
        "enable_alb": True,
        "enable_cloudwatch_alarms": False,
        "enable_autoscaling": False,
        "multi_az": False,
        "instance_class": "db.t3.micro",
        "additional_notes": "",
    }

    prompt = "simple dev ECS service no database"
    intent = parser.parse(prompt)

    assert intent.raw_prompt == prompt


def test_parse_calls_bedrock_with_prompt(parser, mock_bedrock):
    """Parser should pass the prompt to Bedrock."""
    mock_bedrock.invoke_json.return_value = {
        "service_type": "ecs-fargate",
        "database_type": None,
        "environment": "staging",
        "min_tasks": 1,
        "max_tasks": 4,
        "cpu": 512,
        "memory": 1024,
        "enable_alb": True,
        "enable_cloudwatch_alarms": True,
        "enable_autoscaling": True,
        "multi_az": False,
        "instance_class": "db.t3.micro",
        "additional_notes": "",
    }

    prompt = "deploy a staging ECS service"
    parser.parse(prompt)

    mock_bedrock.invoke_json.assert_called_once()
    call_kwargs = mock_bedrock.invoke_json.call_args
    assert prompt in call_kwargs.kwargs.get("prompt", "") or prompt in str(call_kwargs)


# ── InfraIntent validation tests ──────────────────────────────────────────────


def test_infra_intent_valid():
    """A well-formed InfraIntent should have no validation errors."""
    intent = InfraIntent(
        service_type="ecs-fargate",
        database_type="rds-postgres",
        environment="staging",
        min_tasks=1,
        max_tasks=4,
        cpu=512,
        memory=1024,
    )
    assert intent.validate() == []


def test_infra_intent_invalid_cpu():
    """Invalid CPU value should return a validation error."""
    intent = InfraIntent(cpu=999)
    errors = intent.validate()
    assert any("CPU" in e or "cpu" in e.lower() for e in errors)


def test_infra_intent_invalid_task_count():
    """max_tasks < min_tasks should return a validation error."""
    intent = InfraIntent(min_tasks=5, max_tasks=2)
    errors = intent.validate()
    assert any("max_tasks" in e for e in errors)


def test_infra_intent_invalid_environment():
    """Unknown environment should return a validation error."""
    intent = InfraIntent(environment="production-west")
    errors = intent.validate()
    assert any("environment" in e.lower() for e in errors)


def test_infra_intent_from_dict():
    """from_dict should ignore unknown keys gracefully."""
    data = {
        "service_type": "ecs-fargate",
        "database_type": "rds-postgres",
        "environment": "staging",
        "min_tasks": 2,
        "max_tasks": 8,
        "cpu": 1024,
        "memory": 2048,
        "unknown_future_field": "should be ignored",
    }
    intent = InfraIntent.from_dict(data, raw_prompt="test")
    assert intent.service_type == "ecs-fargate"
    assert intent.min_tasks == 2
    assert intent.raw_prompt == "test"
