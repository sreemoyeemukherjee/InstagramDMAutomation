"""Offline sanity checks — no AWS credentials or network calls required.

Exercises the keyword-matching and resource-lookup logic plus the DM tool in
DRY_RUN mode. Does NOT invoke the Bedrock model; for that, run the agent
locally (see README "Local testing") and POST to it.

Run: python tests/test_local.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("DRY_RUN", "true")

from resource_config import detect_keyword_in_text, find_resource_by_keyword  # noqa: E402
from tools import pick_resource, post_public_comment_reply, send_instagram_dm  # noqa: E402


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(1)


def main():
    keyword = detect_keyword_in_text("this is so cool! AGENTIC")
    check("detects known keyword in comment text", keyword == "AGENTIC")

    keyword_none = detect_keyword_in_text("this has no keyword in it")
    check("returns None when no keyword present", keyword_none is None)

    resource = find_resource_by_keyword("agentic")
    check("keyword lookup is case-insensitive", resource is not None and resource["keyword"] == "AGENTIC")

    tool_result = pick_resource("AGENTIC")
    check("pick_resource tool finds the resource", tool_result["found"] is True)

    missing = pick_resource("NOTAREALKEYWORD")
    check("pick_resource reports missing resource cleanly", missing["found"] is False)

    dm_result = send_instagram_dm(comment_id="17900000000000000", message="hello")
    check("send_instagram_dm respects DRY_RUN", dm_result["dry_run"] is True and dm_result["sent"] is False)

    reply_result = post_public_comment_reply(comment_id="17900000000000000", message="Sent you a DM!")
    check("post_public_comment_reply respects DRY_RUN", reply_result["dry_run"] is True and reply_result["sent"] is False)

    print("\nAll offline checks passed.")


if __name__ == "__main__":
    main()
