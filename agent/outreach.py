"""Draft a personalized outreach SMS for a lead with Claude Sonnet.

The prompt includes the matched loan programs (from ``agent.rag``) so the
message can name the specific programs the lead likely qualifies for.
"""
import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = (
    "You are a friendly, compliant mortgage loan officer writing a first-touch "
    "outreach SMS to a prospective borrower. Requirements:\n"
    "- Under 320 characters (two SMS segments).\n"
    "- Greet the lead by first name if available.\n"
    "- Mention 1-2 specific loan programs by name that fit their situation.\n"
    "- Warm and helpful, not pushy. Invite a quick reply or call.\n"
    "- No guarantees of approval, rates, or terms (compliance).\n"
    "Return only the message text, with no preamble or quotation marks."
)


def write_outreach(
    lead: dict,
    matched_programs: list[dict],
    client: anthropic.Anthropic | None = None,
) -> str:
    """Return a personalized outreach SMS string for a lead."""
    client = client or anthropic.Anthropic()

    program_names = sorted({p.get("program", "") for p in matched_programs if p.get("program")})
    program_context = "\n\n".join(
        f"## {p.get('program', 'program')}\n{p.get('content', '')}" for p in matched_programs
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Write the outreach SMS for this lead.\n\n"
                    f"Lead data (JSON):\n{json.dumps(lead, indent=2, default=str)}\n\n"
                    f"Matching loan programs to reference: {', '.join(program_names) or 'none'}\n\n"
                    f"Program details for context:\n{program_context}"
                ),
            }
        ],
    )

    message = "".join(b.text for b in response.content if b.type == "text").strip()
    return message
