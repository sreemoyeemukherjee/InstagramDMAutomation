"""Loads config/keywords.yaml — the shared keyword -> resource mapping.

Kept separate from tools.py so both the agent's tool layer and any offline
script (e.g. validating the content plan) can reuse the same loader.

Lives under src/config/ (not a project-root config/) so it's included in the
self-contained src/ bundle AgentCore's CodeZip build packages and deploys —
anything outside codeLocation ("src/" per agentcore.json) never reaches the
deployed runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "keywords.yaml"


def load_resources() -> list[dict]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("resources", [])


def find_resource_by_keyword(keyword: str) -> Optional[dict]:
    """Case-insensitive exact match on the configured keyword."""
    target = keyword.strip().upper()
    for resource in load_resources():
        if resource["keyword"].upper() == target:
            return resource
    return None


def detect_keyword_in_text(comment_text: str) -> Optional[str]:
    """Scan free-form comment text for the first configured keyword it contains.

    Matches whole words only (case-insensitive) so "AGENTIC" matches but
    "AGENTICALLY" does not.
    """
    words = {w.strip(".,!?:;\"'()").upper() for w in comment_text.split()}
    for resource in load_resources():
        if resource["keyword"].upper() in words:
            return resource["keyword"]
    return None
