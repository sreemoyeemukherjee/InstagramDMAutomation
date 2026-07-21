# InstaDMAutomation

Instagram reel-comment → DM automation agent, built on **AWS Bedrock
AgentCore** (Runtime handles auth, tool-call orchestration, and tracing) with
**Strands Agents** for the agent logic itself, backed by Claude on Bedrock.

Flow: someone comments a keyword on a reel → the agent detects it → picks the
matching resource (guide / repo / blog link) → drafts a reply in the
account's voice → sends the DM.

See [`content/reel_content_plan.md`](content/reel_content_plan.md) for the
reel calendar and keyword strategy, and
[`config/keywords.yaml`](config/keywords.yaml) for the keyword → resource
mapping both the content plan and the agent read from.

## Architecture

```
Instagram comment on a reel
        │
        ▼
Meta webhook (comment on media)  ──┐  NOT built yet — see "What's still needed"
        │                          │  below. This is plumbing outside AgentCore's
        ▼                          │  scope (Instagram's Graph API doesn't talk
Thin intake layer                  │  to AgentCore directly).
(normalizes the webhook payload   ─┘
 into the shape agent.py expects)
        │
        ▼
AgentCore Runtime  ──▶  agent.py (this repo)
  - hosts the agent            - detects the keyword
  - handles AWS auth           - picks the resource (tools.py)
  - traces every tool call     - drafts the DM (Claude via Strands)
        │                      - sends the DM (tools.py, stubbed for now)
        ▼
Instagram Graph API (send DM)
```

**This repo is the agent logic only** — `src/agent.py` is what you deploy to
AgentCore Runtime. The webhook intake layer (receiving Instagram's comment
webhook, verifying it, and calling this agent) is a separate, much smaller
piece of plumbing (e.g. a Lambda behind API Gateway) that isn't built yet —
see below.

## Project layout

```
config/keywords.yaml       # keyword -> resource mapping (shared source of truth)
content/reel_content_plan.md  # reel calendar + content strategy
src/agent.py                # AgentCore entrypoint + Strands agent
src/tools.py                 # pick_resource, send_instagram_dm (DRY_RUN-stubbed)
src/resource_config.py       # loads/queries config/keywords.yaml
tests/test_local.py          # offline sanity checks (no AWS/IG credentials needed)
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then fill in values
```

By default `DRY_RUN=true` — the agent will draft replies and log what it
*would* send without calling the Instagram API, so you can develop and test
before Meta/Instagram access is set up.

## Local testing

**Offline (no AWS credentials needed)** — checks keyword matching, resource
lookup, and the DM tool's dry-run behavior:

```bash
python tests/test_local.py
```

**Full agent locally** (needs AWS credentials with Bedrock access configured,
e.g. via `aws configure` or environment variables) — you can run the
entrypoint file directly since it calls `app.run()`:

```bash
python src/agent.py
```

This starts a local server on `:8080`. In another terminal:

```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
        "comment_text": "this is awesome! AGENTIC",
        "comment_id": "17900000000000001",
        "commenter_username": "example_user",
        "media_id": "17900000000000000",
        "reel_topic": "What agentic AI actually means"
      }'
```

## Deploying to AgentCore

AWS's tooling for AgentCore changed recently: the Python
`bedrock-agentcore-starter-toolkit` CLI is deprecated in favor of a
Node-based CLI. Use that for deployment:

```bash
npm install -g @aws/agentcore
agentcore --help          # see current commands — `create`/`deploy` and friends
```

Point it at `src/agent.py` as the entrypoint and follow its prompts (it
handles the IAM role, ECR image build, and AgentCore Runtime deployment).
Once deployed, invoke the agent via the `bedrock-agentcore` runtime API
(`InvokeAgentRuntime`) instead of the local `:8080` endpoint — the webhook
intake layer will call this.

*(The Python starter-toolkit's `agentcore dev` command — installable via
`pip install bedrock-agentcore-starter-toolkit` — still works as an
alternative local dev server with hot reload if you'd rather not run
`python src/agent.py` directly, but treat it as legacy.)*

## What's still needed (not in scope for this repo)

1. **Instagram Professional account** — Business or Creator, not personal.

2. **Meta App** at [developers.facebook.com](https://developers.facebook.com)
   — create it as **Business type**, add the **Instagram** product, and use
   the **Instagram API with Instagram Login** setup (not the older Facebook
   Login path) — it doesn't require linking a Facebook Page, which is the
   right fit for a personal creator account.

3. **Permissions/scopes** to request on the app:
   - `instagram_business_basic`
   - `instagram_business_manage_comments`
   - `instagram_business_manage_messages`

   You can test these against your own account without full App Review;
   App Review is only required to make this work for the general public.

4. **Webhook subscription** for the `comments` field on your IG media,
   pointing at your intake layer (not this repo — see Architecture above).
   Requirements: a real HTTPS cert (self-signed doesn't work), a `GET`
   handler that echoes `hub.challenge` after checking `hub.verify_token`,
   and a `POST` handler that verifies the `X-Hub-Signature-256` header.

5. **Webhook intake layer** — a small Lambda/API Gateway (or similar) that:
   verifies the webhook signature, extracts `comment_text` / `comment_id` /
   `media_id` from the comment webhook payload, looks up the reel's topic,
   and invokes this agent's AgentCore Runtime endpoint with that payload.

6. **How sending actually works — read this before wiring the intake
   layer.** Instagram doesn't let you DM an arbitrary user by ID. Replying
   to a comment is a **private reply keyed by `comment_id`**
   (`POST /{ig-user-id}/messages` with
   `{"recipient": {"comment_id": "..."}, "message": {"text": "..."}}`),
   which is exactly what `send_instagram_dm` in `tools.py` does. Two real
   constraints that follow from this:
   - You have **7 days** from the comment to send the private reply.
   - **Only one message per commenter per comment** — no follow-ups unless
     they reply back first (then a normal 24h messaging window applies).
   This means your webhook intake layer should invoke the agent close to
   real-time (don't queue comments for days), and the agent's one-shot
   design (detect → reply → done) already matches this constraint — don't
   add retry logic that re-sends on the same `comment_id`.

7. Once you have a real access token, set `INSTAGRAM_ACCESS_TOKEN`,
   `INSTAGRAM_BUSINESS_ACCOUNT_ID`, and `DRY_RUN=false` in `.env`.
   `GRAPH_API_HOST` defaults to `graph.instagram.com` (the Instagram Login
   path); only change it to `graph.facebook.com` if you went with the
   Facebook Login path instead.

## Adding a new reel / keyword

1. Add a block to `config/keywords.yaml`.
2. Add a row to the calendar in `content/reel_content_plan.md`.
3. Redeploy (`agentcore launch`) so the running agent picks up the new
   mapping.
