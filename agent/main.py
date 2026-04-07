"""
main.py
CLI entry point for aws-infra-agent.

Usage:
    python -m agent.main --prompt "deploy an ECS Fargate API with RDS PostgreSQL in staging"
    python -m agent.main --prompt "..." --env production --region us-east-1 --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

from agent.bedrock_client import BedrockClient
from agent.intent_parser import IntentParser
from agent.terraform_generator import TerraformGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="aws-infra-agent — AI-powered AWS infrastructure automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m agent.main --prompt "deploy an ECS Fargate API with RDS PostgreSQL in staging"
  python -m agent.main --prompt "production ECS service, autoscaling 2-10 tasks" --env production
  python -m agent.main --prompt "staging API service" --dry-run
        """,
    )

    parser.add_argument(
        "--prompt",
        required=True,
        help="Natural language description of the infrastructure to provision",
    )
    parser.add_argument(
        "--service-name",
        default=None,
        help="Slug for resource naming (e.g. 'my-api'). Auto-generated from prompt if not provided.",
    )
    parser.add_argument(
        "--env",
        default="staging",
        choices=["dev", "staging", "production"],
        help="Target environment (default: staging)",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse intent and generate Terraform but do not apply",
    )
    parser.add_argument(
        "--output-dir",
        default="terraform/generated",
        help="Directory to write generated Terraform (default: terraform/generated)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def slugify(text: str) -> str:
    """Convert a prompt into a safe resource name slug."""
    import re
    words = text.lower().split()
    # Take first 3 meaningful words, strip non-alphanumeric
    slug = "-".join(re.sub(r"[^a-z0-9]", "", w) for w in words[:3] if len(w) > 2)
    return slug or "infra-agent-service"


def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    print("\n" + "═" * 60)
    print("  aws-infra-agent · Powered by AWS Bedrock Claude Sonnet 4.6")
    print("═" * 60)
    print(f"  Prompt   : {args.prompt}")
    print(f"  Env      : {args.env}")
    print(f"  Region   : {args.region}")
    print(f"  Dry run  : {args.dry_run}")
    print("═" * 60 + "\n")

    # ── Step 1: Parse intent ──────────────────────────────────────
    print("Step 1/3 — Parsing infrastructure intent via Bedrock...")

    bedrock = BedrockClient(region=args.region)
    parser = IntentParser(bedrock_client=bedrock)

    try:
        intent = parser.parse(args.prompt)
    except Exception as e:
        logger.error(f"Failed to parse intent: {e}")
        sys.exit(1)

    print("\n  Detected:")
    print(f"    Service type : {intent.service_type or 'not specified'}")
    print(f"    Database     : {intent.database_type or 'none'}")
    print(f"    Environment  : {intent.environment}")
    print(f"    Tasks        : {intent.min_tasks} – {intent.max_tasks}")
    print(f"    CPU/Memory   : {intent.cpu} / {intent.memory}")
    print(f"    Multi-AZ     : {intent.multi_az}")

    # Override environment from CLI flag if explicitly set
    if args.env != "staging":
        intent.environment = args.env

    # ── Step 2: Generate Terraform ────────────────────────────────
    print("\nStep 2/3 — Generating Terraform configuration...")

    service_name = args.service_name or slugify(args.prompt)
    output_dir = Path(args.output_dir)

    generator = TerraformGenerator(
        bedrock_client=bedrock,
        output_dir=output_dir,
    )

    try:
        tf_path = generator.generate(intent=intent, service_name=service_name)
    except Exception as e:
        logger.error(f"Failed to generate Terraform: {e}")
        sys.exit(1)

    print(f"\n  Generated : {tf_path}")
    print(f"  Size      : {tf_path.stat().st_size} bytes")

    # ── Step 3: Show output ───────────────────────────────────────
    print("\nStep 3/3 — Generated Terraform preview:\n")
    print("─" * 60)

    content = tf_path.read_text()
    # Show first 50 lines
    lines = content.split("\n")
    preview_lines = lines[:50]
    print("\n".join(preview_lines))
    if len(lines) > 50:
        print(f"\n  ... ({len(lines) - 50} more lines) — see {tf_path}")
    print("─" * 60)

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "═" * 60)
    if args.dry_run:
        print("  Dry run complete. Review the generated Terraform above.")
        print(f"  File saved to: {tf_path}")
        print("\n  To apply, commit this file and push to main branch.")
        print("  GitHub Actions OIDC will plan and apply automatically.")
    else:
        print("  Generation complete.")
        print(f"  Next step: git add {tf_path} && git commit -m 'feat: {service_name}'")
        print("  Push to main → GitHub Actions OIDC applies automatically.")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()
