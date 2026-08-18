# Adding a new reel + keyword

Checklist for shipping a new reel with a working keyword-triggered DM. The
webhook layer (`webhook/lambda_handler.py`, API Gateway) never needs to
change for this — it just forwards whatever comment text it receives to the
agent, which does the keyword lookup itself.

## 1. Add the keyword to `src/config/keywords.yaml`

This file is the single source of truth — the deployed agent reads from it,
and the content plan is meant to stay in sync with it. Add a new block:

```yaml
  - keyword: YOURKEYWORD
    resource_type: guide   # guide | github | blog | waitlist | link
    title: "Human-readable resource name"
    url: "https://..."
    reel_topic: "Short description of the reel this keyword is tied to"
    dm_intro: "A seed phrase for the DM's opening line"
```

Field notes:

- **keyword** — one word, ALL CAPS, no hyphens/underscores (easy to type on
  mobile). Matching is case-insensitive but whole-word only, so pick
  something a viewer would naturally type after watching, not a generic
  "LINK" or "INFO".
- **resource_type** — one of `guide`, `github`, `blog`, `waitlist`, `link`.
- **url** — must be a real, live link *before* the reel goes up. A viewer
  commenting into a broken link is the fastest way to lose trust.
- **dm_intro** — not sent verbatim. It's a fragment the agent draws on when
  drafting the DM; the agent still varies tone/wording per commenter (see
  `DM_STYLE_HINTS` in [`src/agent.py`](../src/agent.py)) so replies don't
  look copy-pasted.

## 2. Redeploy the agent

`src/config/keywords.yaml` lives inside `src/`, which is exactly what
AgentCore's CodeZip build packages and deploys — a local edit alone doesn't
reach production. Redeploy:

```bash
agentcore deploy --yes
```

## 3. Test before publishing

Pick one:

- **Local dry run**: `python src/agent.py`, then POST a payload containing
  the new keyword to `http://localhost:8080/invocations` (see main
  [README](../README.md#local-testing) for the exact command).
- **Against the deployed runtime**: invoke it directly with a fake
  `comment_text` containing the new keyword and confirm `pick_resource`
  finds it and the DM drafts correctly, e.g.:

  ```bash
  aws bedrock-agentcore invoke-agent-runtime \
    --agent-runtime-arn "<runtime-arn>" \
    --runtime-session-id "test-session-$(date +%s)-0000000000000000" \
    --payload "$(printf '{"comment_text": "testing YOURKEYWORD", "comment_id": "0", "reel_topic": ""}' | base64 -w0)" \
    --content-type "application/json" \
    ./response.json && cat ./response.json
  ```

  A fake `comment_id` is safe here — Instagram's API will reject it (nothing
  real gets sent), but you'll still see the drafted DM/reply text in the
  response.

## 4. Update the content plan tracker

Add a row to the calendar table in `content/reel_content_plan.md` (local
only, gitignored) so the tracker stays accurate.

## 5. Post the reel

Only once steps 1–4 are done — don't publish a reel whose keyword the bot
can't handle yet.
