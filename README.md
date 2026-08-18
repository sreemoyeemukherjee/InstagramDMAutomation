# InstaDMAutomation

Instagram reel-comment → DM automation agent, built on **AWS Bedrock
AgentCore** (Runtime handles auth, tool-call orchestration, and tracing) with
**Strands Agents** for the agent logic itself, backed by Claude on Bedrock.

Flow: someone comments a keyword on a reel → the agent detects it → picks the
matching resource (guide / repo / blog link) → drafts a reply in the
account's voice → sends the DM.

See [`src/config/keywords.yaml`](src/config/keywords.yaml) for the keyword →
resource mapping the agent reads from — it lives inside `src/` (not a
project-root `config/`) so it's included in the self-contained bundle
AgentCore deploys; anything outside `src/` never reaches the deployed
runtime. (Reel calendar / content strategy docs are kept in a local
`content/` folder, gitignored — not part of this repo.)

## Architecture

```
Instagram comment on a reel
        │
        ▼
Meta webhook (comments field)
        │
        ▼
webhook/lambda_handler.py  ──  API Gateway (HTTP API) + Lambda
  - GET:  verify_token handshake
  - POST: verifies X-Hub-Signature-256, extracts comment_text/comment_id,
          calls bedrock-agentcore:InvokeAgentRuntime
        │
        ▼
AgentCore Runtime  ──▶  agent.py (this repo)
  - hosts the agent            - detects the keyword
  - handles AWS auth           - picks the resource (tools.py)
  - traces every tool call     - drafts the DM (Claude via Strands)
        │                      - sends the DM (tools.py)
        ▼
Instagram Graph API (send DM)
```

**This repo is the agent logic (`src/`) plus the webhook intake layer
(`webhook/`)** that connects real Instagram comment events to it — see
"Deploying the webhook intake layer" below.

## Project layout

```
src/config/keywords.yaml    # keyword -> resource mapping (shared source of truth)
src/agent.py                # AgentCore entrypoint + Strands agent
src/tools.py                 # pick_resource, send_instagram_dm, post_public_comment_reply
src/resource_config.py       # loads/queries src/config/keywords.yaml
tests/test_local.py          # offline sanity checks (no AWS/IG credentials needed)
agentcore/                   # AgentCore deployment config (agentcore.json, CDK infra)
webhook/lambda_handler.py    # webhook intake: verifies Meta's request, invokes the runtime
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

4. **Webhook subscription** for the `comments` field on your IG media — this
   is a manual step in the Meta App dashboard (Webhooks product → Instagram →
   Subscribe, field `comments`), pointing at the API Gateway URL from
   "Deploying the webhook intake layer" below, with the same verify token you
   generated when deploying it. Meta requires a real HTTPS cert (API Gateway
   provides this natively — no self-signed setup needed).

5. **Webhook intake layer** — `webhook/lambda_handler.py`, a Lambda behind an
   API Gateway HTTP API. It verifies `X-Hub-Signature-256`, handles the
   `GET` verify-token handshake, extracts `comment_text`/`comment_id` from
   the comment webhook payload, and invokes this agent's AgentCore Runtime
   endpoint with that payload. See "Deploying the webhook intake layer"
   below.

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

7. **Local dev**: once you have a real access token, set
   `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID`, and
   `DRY_RUN=false` in `.env`. `GRAPH_API_HOST` defaults to
   `graph.instagram.com` (the Instagram Login path); only change it to
   `graph.facebook.com` if you went with the Facebook Login path instead.
   **Deployed runtime**: credentials come from AWS Secrets Manager instead
   (see "Secrets" below) — `.env` is never read there.

## Secrets

Nothing secret lives in a git-tracked file. Two Secrets Manager secrets hold
the real values, referenced only by ARN from `agentcore.json` / the Lambda's
environment variables:

- `InstaDMAutomation/instagram-credentials` — `INSTAGRAM_ACCESS_TOKEN` +
  `INSTAGRAM_BUSINESS_ACCOUNT_ID`. Read by the AgentCore Runtime
  (`src/tools.py`) when `INSTAGRAM_SECRET_ID` is set; falls back to plain
  `.env` vars for local dev.
- `InstaDMAutomation/webhook-secrets` — the Meta App Secret (for
  `X-Hub-Signature-256` verification) + a verify token you generate yourself
  (for the webhook subscription handshake). Read by
  `webhook/lambda_handler.py` via `WEBHOOK_SECRET_ARN`.

Each execution role has a scoped inline policy granting
`secretsmanager:GetSecretValue` on only its one secret.

## Deploying the webhook intake layer

One-time setup (adjust names/region/account as needed):

```bash
# 1. Store the Meta App Secret + a verify token you generate
aws secretsmanager create-secret \
  --name "InstaDMAutomation/webhook-secrets" \
  --secret-string '{"VERIFY_TOKEN": "<random string you choose>", "APP_SECRET": "<Meta App Secret>"}'

# 2. Create the Lambda's execution role (trust policy: lambda.amazonaws.com),
#    attach AWSLambdaBasicExecutionRole, and an inline policy granting
#    secretsmanager:GetSecretValue on the secret above and
#    bedrock-agentcore:InvokeAgentRuntime on both:
#      arn:...:runtime/<runtime-id>
#      arn:...:runtime/<runtime-id>/runtime-endpoint/*   (InvokeAgentRuntime targets the endpoint sub-resource, not the bare runtime ARN)

# 3. Package and deploy the function
cd webhook
powershell -Command "Compress-Archive -Path lambda_handler.py -DestinationPath lambda.zip -Force"
aws lambda create-function \
  --function-name InstaDMAutomation-webhook-intake \
  --runtime python3.12 --handler lambda_handler.handler \
  --role <lambda-role-arn> --zip-file fileb://lambda.zip \
  --timeout 30 --memory-size 256 \
  --environment "Variables={WEBHOOK_SECRET_ARN=<secret-arn>,AGENT_RUNTIME_ARN=<runtime-arn>}"

# 4. Front it with an API Gateway HTTP API (quick-create wires the route,
#    but NOT the Lambda invoke permission — add that separately)
aws apigatewayv2 create-api --name InstaDMAutomation-webhook \
  --protocol-type HTTP --target <lambda-arn>
aws lambda add-permission \
  --function-name InstaDMAutomation-webhook-intake \
  --statement-id apigateway-invoke --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:<region>:<account>:<api-id>/*/*"
```

Redeploying after a code change is just steps 3's zip + `aws lambda
update-function-code --function-name InstaDMAutomation-webhook-intake
--zip-file fileb://lambda.zip`.

## Adding a new reel / keyword

See [`docs/adding-a-reel.md`](docs/adding-a-reel.md) for the full checklist
(keyword fields, redeploy, testing before publishing).
