"""
bedrock_client.py
AWS Bedrock client wrapper for Claude 4.6 Sonnet.
Handles invocation, retry logic, and response parsing.
"""

import json
import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

MODEL_ID = "us.anthropic.claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_REGION = "us-east-1"


class BedrockClient:
    """
    Thin wrapper around AWS Bedrock runtime for Claude 4.6 Sonnet.
    Handles retries, structured JSON responses, and prompt templating.
    """

    def __init__(self, region: str = DEFAULT_REGION, max_retries: int = 3):
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.max_retries = max_retries

    def invoke(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
    ) -> str:
        """
        Invoke Claude 4.6 Sonnet and return the response text.

        Args:
            prompt: User message
            system_prompt: Optional system context
            max_tokens: Max tokens in response
            temperature: 0.0 for deterministic IaC output

        Returns:
            Response text from the model
        """
        messages = [{"role": "user", "content": prompt}]

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        if system_prompt:
            body["system"] = system_prompt

        for attempt in range(self.max_retries):
            try:
                response = self.client.invoke_model(
                    modelId=MODEL_ID,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
                result = json.loads(response["body"].read())
                return result["content"][0]["text"]

            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if (
                    error_code == "ThrottlingException"
                    and attempt < self.max_retries - 1
                ):
                    wait = 2**attempt
                    logger.warning(f"Throttled by Bedrock, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"Bedrock invocation failed: {e}")
                    raise

        raise RuntimeError("Max retries exceeded calling Bedrock")

    def invoke_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict:
        """
        Invoke Bedrock and parse the response as JSON.
        Strips markdown code fences if present.

        Returns:
            Parsed dict from model response
        """
        json_system = (system_prompt or "") + (
            "\n\nIMPORTANT: Respond with valid JSON only. "
            "No markdown, no explanation, no code fences. Raw JSON only."
        )

        raw = self.invoke(prompt, system_prompt=json_system, max_tokens=max_tokens)

        # Strip any markdown fences the model may include despite instructions
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Bedrock JSON response: {e}\nRaw: {raw}")
            raise ValueError(f"Model returned invalid JSON: {e}") from e
