"""Score an enriched lead 1-10 with Claude Sonnet.

Uses structured outputs (``output_config.format``) so the model returns a
strict JSON object we can parse without regex.
"""
import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = (
    "You are a mortgage lead-qualification analyst. Given an enriched home-loan "
    "lead, rate how promising it is to pursue on a scale of 1 (poor) to 10 "
    "(excellent). Weigh creditworthiness, loan-to-income ratio, property and "
    "demographic context, and overall data completeness. Be calibrated: most "
    "leads fall in the 4-7 range."
)

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "enum": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "description": "Lead quality, 1 (poor) to 10 (excellent).",
        },
        "rationale": {
            "type": "string",
            "description": "One or two sentences explaining the score.",
        },
    },
    "required": ["score", "rationale"],
    "additionalProperties": False,
}


def score_lead(lead: dict, client: anthropic.Anthropic | None = None) -> dict:
    """Return ``{"score": int, "rationale": str}`` for an enriched lead."""
    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": (
                    "Score this lead and explain briefly.\n\n"
                    f"Lead data (JSON):\n{json.dumps(lead, indent=2, default=str)}"
                ),
            }
        ],
    )

    text = next((b.text for b in response.content if b.type == "text"), "{}")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Scorer returned non-JSON: %s", text[:200])
        return {"score": 0, "rationale": "Failed to parse model output."}

    # Clamp defensively in case the model ignores the enum.
    score = result.get("score", 0)
    result["score"] = max(1, min(10, int(score))) if isinstance(score, (int, float)) else 0
    result.setdefault("rationale", "")
    return result
