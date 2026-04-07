"""
terraform_generator.py
Generates Terraform HCL from a structured InfraIntent.
Uses Bedrock to produce module calls referencing the
securedpress/aws-terraform-modules public repo.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from agent.bedrock_client import BedrockClient
from agent.intent_parser import InfraIntent

logger = logging.getLogger(__name__)

GENERATED_DIR = Path("terraform/generated")

SYSTEM_PROMPT = """
You are a senior Terraform engineer. Generate production-quality Terraform HCL
using the SecuredPress public Terraform module library.

Available modules (use these exact source URLs):
- github.com/securedpress/aws-terraform-modules//modules/ecs-fargate?ref=v1.1.0
  inputs: service_name, image, cpu, memory, min_tasks, max_tasks, environment, vpc_id, private_subnets, public_subnets
- github.com/securedpress/aws-terraform-modules//modules/rds-postgres?ref=v1.1.0
  inputs: identifier, instance_class, engine_version, multi_az, environment, vpc_id, private_subnets, allowed_security_group_ids, database_name
- github.com/securedpress/aws-terraform-modules//modules/cloudwatch-alarms?ref=v1.1.0
  inputs: service_name, ecs_cluster_name, db_instance_id, environment, enable_remediation

Rules:
- Always use the exact GitHub module source URLs above, never local paths
- Include terraform {} block with required_version = ">= 1.7"
- Include provider "aws" block with region variable
- Use locals for common values (environment, region, tags)
- Add standard tags: Project = "infra-agent", ManagedBy = "terraform", Environment
- Include vpc_id, private_subnets, public_subnets as input variables
- Output: service_url (ALB DNS), db_endpoint if database is included
- No hardcoded account IDs or regions — use variables

Return ONLY valid Terraform HCL. No markdown, no explanation.
"""


class TerraformGenerator:
    """
    Generates Terraform HCL from InfraIntent via Bedrock,
    writes to terraform/generated/, and validates syntax.
    """

    def __init__(
        self,
        bedrock_client: BedrockClient = None,
        output_dir: Path = GENERATED_DIR,
    ):
        self.bedrock = bedrock_client or BedrockClient()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, intent: InfraIntent, service_name: str) -> Path:
        """
        Generate a complete Terraform configuration for the given intent.

        Args:
            intent: Parsed InfraIntent from IntentParser
            service_name: Slug used for resource naming (e.g. "my-api")

        Returns:
            Path to the generated .tf file
        """
        prompt = self._build_prompt(intent, service_name)
        logger.info(f"Generating Terraform for service '{service_name}'...")

        hcl = self.bedrock.invoke(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.0,
        )

        # Strip markdown fences if present
        hcl = hcl.strip()
        if hcl.startswith("```"):
            lines = hcl.split("\n")
            hcl = "\n".join(lines[1:-1])

        output_path = self.output_dir / f"{service_name}.tf"
        output_path.write_text(hcl)
        logger.info(f"Terraform written to {output_path}")

        # Validate syntax
        self._validate(output_path)

        return output_path

    def _build_prompt(self, intent: InfraIntent, service_name: str) -> str:
        parts = [
            f"Generate a complete Terraform configuration for: {intent.raw_prompt}",
            "",
            f"Service name: {service_name}",
            f"Environment: {intent.environment}",
        ]

        if intent.service_type == "ecs-fargate":
            parts += [
                f"ECS Fargate: cpu={intent.cpu}, memory={intent.memory}",
                f"Autoscaling: min={intent.min_tasks}, max={intent.max_tasks}",
                f"ALB: {intent.enable_alb}",
            ]

        if intent.database_type:
            parts += [
                f"Database: {intent.database_type}",
                f"Instance class: {intent.instance_class}",
                f"Multi-AZ: {intent.multi_az}",
            ]

        if intent.enable_cloudwatch_alarms:
            parts.append("Include CloudWatch alarms module")

        return "\n".join(parts)

    def _validate(self, tf_path: Path) -> None:
        """
        Run terraform init + validate on the generated file.
        Logs a warning if Terraform is not installed — does not raise.
        """
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_tf = Path(tmpdir) / "main.tf"
                tmp_tf.write_text(tf_path.read_text())

                # Init first to download GitHub modules
                init_result = subprocess.run(
                    ["terraform", "init", "-no-color"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if init_result.returncode != 0:
                    logger.warning(
                        f"Terraform init warnings:\n{init_result.stderr or init_result.stdout}"
                    )
                    return

                # Validate after init
                result = subprocess.run(
                    ["terraform", "validate", "-no-color"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode != 0:
                    logger.warning(
                        f"Terraform validation warnings:\n{result.stderr or result.stdout}"
                    )
                else:
                    logger.info("Terraform validation passed")

        except FileNotFoundError:
            logger.warning("terraform binary not found — skipping validation")
        except subprocess.TimeoutExpired:
            logger.warning("terraform validate timed out")