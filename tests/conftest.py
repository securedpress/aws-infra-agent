"""
conftest.py
Shared pytest configuration.
Sets dummy AWS env vars so boto3 doesn't attempt real credential
resolution during unit tests.
"""

import pytest


@pytest.fixture(autouse=True)
def mock_aws_env(monkeypatch):
    """
    Inject dummy AWS credentials for all tests.
    Prevents boto3 from hitting real AWS endpoints or
    prompting for credentials during unit test runs.
    """
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "test-session-token")
