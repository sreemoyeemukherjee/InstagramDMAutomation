"""Webhook intake layer: receives Instagram's comment webhook (via API Gateway
HTTP API), verifies it, and invokes the AgentCore Runtime with a normalized
payload.

Two responsibilities Meta requires of any webhook endpoint:
  - GET:  the one-time subscription handshake (verify hub.verify_token, echo
    hub.challenge back).
  - POST: the actual event delivery, authenticated via the X-Hub-Signature-256
    header (HMAC-SHA256 of the raw body, keyed with the Meta App Secret) —
    this is what stops anyone else from posting fake comment events at this
    URL.

Secrets (App Secret, verify token) come from Secrets Manager, not env vars
directly, for the same reason the agent's Instagram token does: this project
is public on GitHub and nothing secret should ever need to touch a
git-tracked file.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid

import boto3

secrets_client = boto3.client("secretsmanager")
agentcore_client = boto3.client("bedrock-agentcore")

_webhook_secrets: dict | None = None


def _get_webhook_secrets() -> dict:
    global _webhook_secrets
    if _webhook_secrets is None:
        secret_arn = os.environ["WEBHOOK_SECRET_ARN"]
        _webhook_secrets = json.loads(secrets_client.get_secret_value(SecretId=secret_arn)["SecretString"])
    return _webhook_secrets


def handler(event: dict, context) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method == "GET":
        return _handle_verification(event)
    if method == "POST":
        return _handle_webhook(event)
    return {"statusCode": 405, "body": "Method not allowed"}


def _handle_verification(event: dict) -> dict:
    params = event.get("queryStringParameters") or {}
    verify_token = _get_webhook_secrets()["VERIFY_TOKEN"]
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return {"statusCode": 200, "body": params.get("hub.challenge", "")}
    return {"statusCode": 403, "body": "Verification failed"}


def _handle_webhook(event: dict) -> dict:
    raw_body = _get_raw_body(event)
    app_secret = _get_webhook_secrets()["APP_SECRET"]

    if not _signature_is_valid(raw_body, _get_header(event, "x-hub-signature-256"), app_secret):
        return {"statusCode": 403, "body": "Invalid signature"}

    payload = json.loads(raw_body)
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            _handle_comment(change.get("value", {}))

    # Always 200 once the signature checks out, even if nothing matched —
    # Meta retries (and eventually disables) webhooks that don't ack fast.
    return {"statusCode": 200, "body": "OK"}


def _handle_comment(value: dict) -> None:
    comment_text = value.get("text", "")
    comment_id = value.get("id", "")
    if not comment_text or not comment_id:
        return

    runtime_arn = os.environ["AGENT_RUNTIME_ARN"]
    request_payload = json.dumps(
        {
            "comment_text": comment_text,
            "comment_id": comment_id,
            # Not looked up here — pulling the reel's caption would mean an extra
            # Graph API round trip on every comment. The agent works fine without
            # it (only used as light context in the drafted reply).
            "reel_topic": "",
        }
    ).encode("utf-8")

    agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=f"webhook-{comment_id}-{uuid.uuid4().hex}",
        payload=request_payload,
        contentType="application/json",
    )


def _signature_is_valid(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


def _get_raw_body(event: dict) -> bytes:
    body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8")


def _get_header(event: dict, name: str) -> str | None:
    for key, value in (event.get("headers") or {}).items():
        if key.lower() == name:
            return value
    return None
