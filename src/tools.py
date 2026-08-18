"""Strands tools the agent calls: resource lookup, the private DM, and a
public comment acknowledgment.

Instagram delivery is stubbed behind DRY_RUN (default true) since the Meta
app / webhook setup hasn't happened yet — see README "Instagram/Meta setup"
for what's needed before flipping it off.

send_instagram_dm sends a *private reply to a comment*, not a DM to an
arbitrary user ID — Instagram's messaging API only allows this scoped to the
comment_id, and only within 7 days of the comment, one message per commenter
per comment. See
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/private-replies

post_public_comment_reply is a separate, publicly-visible reply under the
comment (POST /{comment_id}/replies) — different endpoint, different
visibility. Never put resource details in it.
"""

from __future__ import annotations

import json
import os
import sys

import requests
from strands import tool

from resource_config import find_resource_by_keyword

GRAPH_API_VERSION = "v21.0"
# graph.instagram.com for the Instagram API with Instagram Login path (no linked
# Facebook Page). If you're on the older Facebook Login path instead, this needs
# to be graph.facebook.com.
GRAPH_API_HOST = os.environ.get("GRAPH_API_HOST", "graph.instagram.com")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

_instagram_credentials: dict | None = None


def _get_instagram_credentials() -> dict:
    """Instagram token + business account ID.

    Deployed runtime sets INSTAGRAM_SECRET_ID (the secret's name, not its ARN
    — GetSecretValue accepts either, and the name avoids baking the AWS
    account ID into agentcore.json, which is git-tracked). Local dev falls
    back to plain env vars from .env.
    """
    global _instagram_credentials
    if _instagram_credentials is not None:
        return _instagram_credentials

    secret_id = os.environ.get("INSTAGRAM_SECRET_ID")
    if secret_id:
        import boto3

        client = boto3.client("secretsmanager")
        _instagram_credentials = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    else:
        _instagram_credentials = {
            "INSTAGRAM_ACCESS_TOKEN": os.environ["INSTAGRAM_ACCESS_TOKEN"],
            "INSTAGRAM_BUSINESS_ACCOUNT_ID": os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"],
        }
    return _instagram_credentials


@tool
def pick_resource(keyword: str) -> dict:
    """Look up the resource (guide/repo/blog link) tied to a detected keyword.

    Args:
        keyword: The keyword the commenter used, e.g. "AGENTIC" or "MCP".
    """
    resource = find_resource_by_keyword(keyword)
    if resource is None:
        return {
            "found": False,
            "message": f"No configured resource for keyword '{keyword}'.",
        }
    return {"found": True, **resource}


@tool
def send_instagram_dm(comment_id: str, message: str) -> dict:
    """Send a private reply to the comment that triggered this agent run.

    This is Instagram's "private reply" mechanism, not a general-purpose DM —
    it can only be sent within 7 days of the comment, and only once per
    commenter per comment (no follow-ups unless they reply back first).

    Args:
        comment_id: The ID of the comment to privately reply to (from the
            webhook payload's `comment_id` field — NOT a user ID).
        message: The final DM text to send, already personalized.
    """
    print(f"\n--- send_instagram_dm called ---\ncomment_id: {comment_id}\nmessage: {message}\n---\n", file=sys.stderr)

    if DRY_RUN:
        return {
            "sent": False,
            "dry_run": True,
            "comment_id": comment_id,
            "message": message,
            "note": "DRY_RUN is on — no request was sent. Set DRY_RUN=false once IG credentials are configured.",
        }

    credentials = _get_instagram_credentials()
    access_token = credentials["INSTAGRAM_ACCESS_TOKEN"]
    ig_user_id = credentials["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
    url = f"https://{GRAPH_API_HOST}/{GRAPH_API_VERSION}/{ig_user_id}/messages"

    try:
        response = requests.post(
            url,
            params={"access_token": access_token},
            json={"recipient": {"comment_id": comment_id}, "message": {"text": message}},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        detail = e.response.text if e.response is not None else str(e)
        print(f"\n--- send_instagram_dm FAILED ---\n{detail}\n---\n", file=sys.stderr)
        return {"sent": False, "dry_run": False, "error": detail}

    return {"sent": True, "dry_run": False, "response": response.json()}


@tool
def post_public_comment_reply(comment_id: str, message: str) -> dict:
    """Post a short, PUBLIC reply visible under the original comment.

    Distinct from send_instagram_dm — this is not private. Use it only for a
    brief acknowledgment (e.g. "Sent you a DM!"), never the resource link or
    details, since anyone can see it.

    Args:
        comment_id: The ID of the comment to publicly reply to.
        message: The final public reply text, already varied/personalized.
    """
    print(f"\n--- post_public_comment_reply called ---\ncomment_id: {comment_id}\nmessage: {message}\n---\n", file=sys.stderr)

    if DRY_RUN:
        return {
            "sent": False,
            "dry_run": True,
            "comment_id": comment_id,
            "message": message,
            "note": "DRY_RUN is on — no request was sent. Set DRY_RUN=false once IG credentials are configured.",
        }

    access_token = _get_instagram_credentials()["INSTAGRAM_ACCESS_TOKEN"]
    url = f"https://{GRAPH_API_HOST}/{GRAPH_API_VERSION}/{comment_id}/replies"

    try:
        response = requests.post(
            url,
            params={"access_token": access_token},
            json={"message": message},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        detail = e.response.text if e.response is not None else str(e)
        print(f"\n--- post_public_comment_reply FAILED ---\n{detail}\n---\n", file=sys.stderr)
        return {"sent": False, "dry_run": False, "error": detail}

    return {"sent": True, "dry_run": False, "response": response.json()}
