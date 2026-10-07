"""
JQ DSL Grammar and Code Sanitization Module.

Sanitizes raw LLM generation strings, strips code blocks,
and verifies static syntactical well-formedness.
"""

from __future__ import annotations
import re
from typing import Tuple, Optional
import jq


def sanitize_jq_code(raw_code: str) -> str:
    """
    Cleans raw LLM outputs: strips markdown fences, preamble, and explanatory commentary.
    """
    cleaned = raw_code.strip()
    # Strip markdown fences ```jq ... ``` or ``` ... ```
    if "```" in cleaned:
        match = re.search(r"```(?:jq)?\s*\n([\s\S]*?)\n```", cleaned, re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
        else:
            # Fallback: remove all lines starting with ```
            lines = [line for line in cleaned.splitlines() if not line.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
    return cleaned


def validate_jq_syntax(jq_source: str) -> Tuple[bool, Optional[str]]:
    """
    Checks if JQ string compiles under libjq parser.
    """
    try:
        jq.compile(jq_source)
        return True, None
    except Exception as e:
        return False, str(e)
