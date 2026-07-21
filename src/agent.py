"""AgentCore entrypoint for the Instagram reel-comment DM agent.

AgentCore Runtime owns the HTTP surface, auth, and tracing (see README) — this
file is just the agent logic: detect the keyword in the comment, pick the
matching resource, draft a reply in the account's voice, send the DM.

Local run:  python src/agent.py           (serves on :8080, see README)
Deploy:     agentcore configure && agentcore launch   (bedrock-agentcore-starter-toolkit)
"""

from __future__ import annotations

import os
import random

from dotenv import load_dotenv

# Must run before importing tools (it reads DRY_RUN/GRAPH_API_HOST from the
# environment at module load time) and before reading MODEL_ID/AWS_REGION below.
load_dotenv()

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402
from strands import Agent  # noqa: E402
from strands.models import BedrockModel  # noqa: E402

from resource_config import detect_keyword_in_text  # noqa: E402
from tools import pick_resource, post_public_comment_reply, send_instagram_dm  # noqa: E402

# Randomly injected per request so the DM and public reply don't come out
# structurally identical across different commenters — Instagram can flag
# accounts that send near-identical messages to many people as spammy.
# Prompt-level variation is more reliable here than relying on sampling
# temperature alone, since a short templated reply can converge to the same
# phrasing even with randomness turned up.
DM_STYLE_HINTS = [
    "Open by directly referencing something specific from their comment text, not just the reel topic in general.",
    "Keep this one especially tight — two sentences, no wasted words.",
    "Lead with a quick, genuine reaction to the reel before mentioning the resource.",
    "Avoid opening with 'Glad' or 'Thanks' — start the sentence a different way this time.",
    "Mention one small specific detail about the resource itself, not just its title.",
    "Use a different low-pressure sign-off than a typical 'let me know if you get stuck.'",
]

PUBLIC_REPLY_STYLE_HINTS = [
    "Keep it to 3-5 words.",
    "Use a slightly different phrasing than 'Sent you a DM' — vary the wording.",
    "It's fine to use at most one emoji, but don't force one if it doesn't fit.",
    "Make it sound like a quick aside, not a template.",
]

# Strands' BedrockModel calls the bedrock-runtime Converse/ConverseStream API,
# which requires the full dated+versioned model ID — NOT the bare
# "anthropic.claude-haiku-4-5" form (that's only valid on the separate
# bedrock-mantle/Messages-API endpoint). It also needs the "us." cross-region
# inference profile prefix — the plain regional ID isn't enabled for on-demand
# throughput on this model. Must match a profile that covers AWS_REGION below
# (us. covers us-east-1/us-east-2/us-west-2 — see the model's Bedrock model card
# for other regions/geos).
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

SYSTEM_PROMPT = """You are the Instagram assistant for a tech/software-development
and agentic-AI content account. Someone commented a keyword on one of the
account's reels; your job is to reply to them with a private DM AND a short
public acknowledgment under their comment.

For every request:
1. You will be given the commenter's raw comment text and the reel's topic.
2. Call `pick_resource` with the keyword you find in the comment text
   (it will already be identified for you in the prompt — pass it exactly).
3. If no resource is found, do NOT call `send_instagram_dm` or
   `post_public_comment_reply` — just say so.
4. Draft a short private DM (2-4 sentences) that:
   - Opens with a one-line acknowledgment tied to the specific reel topic
     (never a generic "Thanks for commenting!").
   - Shares the resource link with one sentence on what it is.
   - Ends with a low-pressure, non-salesy next step (e.g. inviting them to
     reply if they get stuck).
   - Matches a friendly, knowledgeable, slightly casual tech-creator voice.
     No emoji spam, no hype language, no exclamation-mark stacking.
   - Genuinely varies its wording, sentence structure, and opening from a
     generic template — a request-specific style note may be included in the
     prompt; follow it. Never reuse the exact same sentence you've used
     before, even for the same keyword — different commenters should get
     differently-phrased replies.
5. Call `send_instagram_dm` with the drafted message and the given comment ID
   — this sends a private reply to that comment, NOT a DM to a user ID.
6. Draft a SHORT public reply (a few words, e.g. "Sent you a DM!") —
   generic-but-varied, no resource details or links (it's visible to
   everyone). Follow any public-reply style note included in the prompt, and
   vary the wording from previous replies the same way as the DM.
7. Call `post_public_comment_reply` with that text and the same comment ID.
8. Reply to the caller with a one-line summary of both things you sent.

Never invent a resource or URL that `pick_resource` did not return.
"""

app = BedrockAgentCoreApp()

model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION)

agent = Agent(
    model=model,
    tools=[pick_resource, send_instagram_dm, post_public_comment_reply],
    system_prompt=SYSTEM_PROMPT,
)


@app.entrypoint
def invoke(payload: dict) -> dict:
    """Entry point AgentCore Runtime calls for each invocation.

    Expected payload shape (produced by the webhook-intake layer upstream —
    see README "Architecture" for what sits in front of this agent). Note
    `comment_id`, not a user ID — Instagram's private-reply API is scoped to
    the comment, not the commenter:
        {
            "comment_text": "this is awesome! AGENTIC",
            "comment_id": "17900000000000001",      # the comment to reply to
            "commenter_username": "example_user",   # for personalizing the reply
            "media_id": "17900000000000000",
            "reel_topic": "What 'agentic AI' actually means"
        }
    """
    comment_text = payload.get("comment_text", "")
    comment_id = payload.get("comment_id", "")
    reel_topic = payload.get("reel_topic", "")

    keyword = detect_keyword_in_text(comment_text)
    if keyword is None:
        return {
            "handled": False,
            "reason": "no configured keyword found in comment_text",
        }

    prompt = (
        f"Detected keyword: {keyword}\n"
        f"Comment text: {comment_text}\n"
        f"Reel topic: {reel_topic}\n"
        f"Comment ID to reply to: {comment_id}\n"
        f"Style note for the private DM: {random.choice(DM_STYLE_HINTS)}\n"
        f"Style note for the public reply: {random.choice(PUBLIC_REPLY_STYLE_HINTS)}\n\n"
        "Follow your instructions: look up the resource, draft the DM, send it, "
        "then draft and post the public acknowledgment reply."
    )
    result = agent(prompt)
    return {"handled": True, "keyword": keyword, "result": result.message}


if __name__ == "__main__":
    app.run()
