"""Version-controlled Gemini prompt templates, with a changelog for each revision.

The prompt is code, not a magic string buried in a call site. It is versioned,
reviewed and recorded on every generated report, so any report can be traced back
to the exact instructions that produced it — which matters when the output informs
a permit decision.

CHANGELOG
---------
v1  Initial prompt. Constrains the model to the supplied breakdown only, forbids
    inventing figures, and fixes the structure so reports are comparable to each
    other rather than varying in shape run to run.
"""

from __future__ import annotations

import json
from typing import Any, Final

PROMPT_VERSION: Final[str] = "v1"

# The model is explicitly forbidden from introducing numbers. Everything
# quantitative must come from the breakdown, because a plausible-sounding invented
# figure is the most dangerous possible failure for this product.
_SYSTEM_INSTRUCTION: Final[
    str
] = """\
You are writing a plain-English climate risk summary for a building site, for a \
reader who is a homeowner or a small builder — not an engineer.

Absolute rules:
1. Use ONLY the figures in the DATA block. Never introduce a number, year, cost, \
material or place name that is not present there.
2. If a value is null or absent, say it is not available. Never estimate it.
3. Do not give legal, financial or insurance advice, and do not promise outcomes.
4. State the uncertainty. The crossing year is an estimate with a range, and the \
report must read that way.
5. Plain language. No jargon without a short explanation. British or Indian \
English spelling, no American spelling.

Structure your reply as exactly these four sections, using these headings:

## What we found
Two or three sentences: the headline year, what it means, and the confidence.

## Why
The main hazards driving the result, referring to the component breakdown. Name \
which part of the building is the weak point.

## What would help
The recommended material changes and the difference they make. If there are no \
recommendations, say the current specification is already well suited.

## What this does not tell you
The honest limits: this is a projection under one climate scenario, it is not a \
survey of the actual building, and it is not an insurance decision.

Keep the whole report under 400 words.\
"""


def build_report_prompt(breakdown: dict[str, Any]) -> str:
    """Build the report prompt for one score.

    Args:
        breakdown: The score payload — crossing year, confidence, component
            decomposition, materials and recommendations. Serialised verbatim so
            the model cannot be given a figure the API did not compute.

    Returns:
        The full prompt text.
    """
    data = json.dumps(breakdown, indent=2, sort_keys=True, default=str)
    return f"{_SYSTEM_INSTRUCTION}\n\nDATA:\n```json\n{data}\n```\n"
