"""
Robust LLM JSON response parser.

Single responsibility: extract valid JSON from LLM responses
regardless of formatting (raw JSON, markdown fences, mixed text).

Used by:
  - app.agents.pipeline (LangGraph nodes)
  - app.tasks.document (Celery task)
  - Any future LLM call that returns JSON
"""
from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(response_text: str) -> dict[str, Any]:
    """
    Parse JSON from an LLM response robustly.

    Handles all common LLM output formats:
      1. Raw JSON:           {"clauses": [...]}
      2. Markdown fenced:   ```json\n{"clauses": [...]}\n```
      3. Mixed text + JSON: "Here are the clauses:\n```json\n{...}\n```"
      4. Fence without tag: ```\n{"clauses": [...]}\n```

    Returns:
        Parsed dict, or empty dict on failure (never raises).
    """
    if not response_text:
        return {}

    text = response_text.strip()

    # Method 1: ```json { } ``` or ``` { } ```
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # Method 2: outermost { } block — handles text before/after JSON
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass

    # Method 3: whole text as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    return {}


def parse_clauses(response_text: str) -> list[dict[str, Any]]:
    """
    Parse clause list from LLM response.
    Convenience wrapper — returns the 'clauses' array directly.

    Returns:
        List of clause dicts, or empty list on failure.
    """
    data = parse_llm_json(response_text)
    return data.get("clauses", []) if isinstance(data, dict) else []
