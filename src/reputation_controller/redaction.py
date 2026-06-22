"""Secret redaction helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Protocol


class SecretLike(Protocol):
    github_token: str
    llm_api_key: str


def redact_text(text: str, secrets: SecretLike) -> str:
    redacted = text
    if secrets.github_token:
        redacted = redacted.replace(secrets.github_token, "[REDACTED_GITHUB_TOKEN]")
    if secrets.llm_api_key:
        redacted = redacted.replace(secrets.llm_api_key, "[REDACTED_LLM_API_KEY]")
    return redacted


def redact_mapping(mapping: MutableMapping[str, str], secrets: SecretLike) -> None:
    for key, value in list(mapping.items()):
        mapping[key] = redact_text(value, secrets)
