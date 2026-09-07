"""Configuration access (NFR Q7): env vars for stack Parameters, SSM for shared dev
values, Secrets Manager for secrets (never plaintext env). Reference convention —
copied per service by the scaffold generator (FQ1).
"""
from __future__ import annotations

import os
from functools import lru_cache

import boto3


def env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


@lru_cache(maxsize=64)
def ssm_param(name: str, *, decrypt: bool = False) -> str:
    """Read a shared value from SSM Parameter Store (dev convenience; customer install
    passes values as CFN Parameters -> env vars instead)."""
    client = boto3.client("ssm")
    resp = client.get_parameter(Name=name, WithDecryption=decrypt)
    return resp["Parameter"]["Value"]


@lru_cache(maxsize=32)
def secret(secret_id: str) -> str:
    """Read a secret from AWS Secrets Manager. Never store secrets in env vars."""
    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_id)
    return resp.get("SecretString") or ""


def semantic_search_enabled() -> bool:
    """Runtime resolution of the EnableSemanticSearch capability (Q10)."""
    return env("ENABLE_SEMANTIC_SEARCH", "false").lower() == "true"
