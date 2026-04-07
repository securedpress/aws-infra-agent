"""
intent_parser.py
Parses natural language infrastructure requests into a structured
InfraIntent object using AWS Bedrock (Claude 4.6 Sonnet).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from agent.bedrock_client import BedrockClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an expert AWS infrastructure engineer. Your job is to parse
natural language infrastructure requests into structured JSON that describes
what AWS resources need to be provisioned.

Extract the following from the user's request and return as JSON:

{
  "service_type": "ecs-fargate" | "lambda" | "ec2" | null,
  "database_type": "rds-postgres" | "rds-mysql" | "dynamodb" | null,
  "environment": "staging" | "production" | "dev",
  "min_tasks": <int, default 1>,
  "max_tasks": <int, default 4>,
  "cpu": <int, valid: 256|512|1024|2048|4096, default 512>,
  "memory": <int, must be valid for chosen cpu, default 1024>,
  "enable_alb": <bool, default true>,
  "enable_cloudwatch_alarms": <bool, default true>,
  "enable_autoscaling": <bool, default true>,
  "multi_az": <bool, default false>,
  "instance_class": <string, e.g. "db.t3.medium", default "db.t3.micro">,
  "additional_notes": <string, any extra context>
}

Rules:
- If the user mentions "production" or "prod", set multi_az=true
- If the user mentions autoscaling, set appropriate min/max tasks
- Default environment to "staging" if not specified
- Return ONLY the JSON object, no explanation
"""


@dataclass
class InfraIntent:
    """Structured representation of a parsed infrastructure request."""

    service_type: Optional[str] = None
    database_type: Optional[str] = None
    environment: str = "staging"
    min_tasks: int = 1
    max_tasks: int = 4
    cpu: int = 512
    memory: int = 1024
    enable_alb: bool = True
    enable_cloudwatch_alarms: bool = True
    enable_autoscaling: bool = True
    multi_az: bool = False
    instance_class: str = "db.t3.micro"
    additional_notes: str = ""
    raw_prompt: str = ""

    @classmethod
    def from_dict(cls, data: dict, raw_prompt: str = "") -> "InfraIntent":
        valid_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered, raw_prompt=raw_prompt)

    def validate(self) -> list[str]:
        """Return a list of validation errors, empty if valid."""
        errors = []

        valid_cpu = {256, 512, 1024, 2048, 4096}
        if self.cpu not in valid_cpu:
            errors.append(f"Invalid CPU value {self.cpu}. Must be one of {valid_cpu}")

        if self.min_tasks < 1:
            errors.append("min_tasks must be >= 1")

        if self.max_tasks < self.min_tasks:
            errors.append("max_tasks must be >= min_tasks")

        if self.environment not in ("dev", "staging", "production"):
            errors.append(f"Unknown environment '{self.environment}'")

        return errors


class IntentParser:
    """
    Uses Bedrock to parse natural language infrastructure requests
    into structured InfraIntent objects.
    """

    def __init__(self, bedrock_client: Optional[BedrockClient] = None):
        self.bedrock = bedrock_client or BedrockClient()

    def parse(self, prompt: str) -> InfraIntent:
        """
        Parse a natural language prompt into an InfraIntent.

        Args:
            prompt: Natural language infrastructure request
                    e.g. "deploy an ECS Fargate API with RDS Postgres,
                          autoscaling 2-10 tasks, production"

        Returns:
            InfraIntent with extracted configuration

        Raises:
            ValueError: If the model returns unparseable output
        """
        logger.info(f"Parsing intent from prompt: {prompt[:100]}...")

        data = self.bedrock.invoke_json(
            prompt=f"Parse this infrastructure request:\n\n{prompt}",
            system_prompt=SYSTEM_PROMPT,
        )

        intent = InfraIntent.from_dict(data, raw_prompt=prompt)

        errors = intent.validate()
        if errors:
            logger.warning(f"Intent validation warnings: {errors}")

        logger.info(
            f"Parsed intent: service={intent.service_type}, "
            f"db={intent.database_type}, env={intent.environment}, "
            f"tasks={intent.min_tasks}-{intent.max_tasks}"
        )

        return intent
