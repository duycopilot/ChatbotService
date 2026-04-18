"""
Purpose: Format LLM output before returning to the client
"""


def format_reply(raw: str) -> str:
    """
    Clean and normalise LLM output.
    """
    return raw.strip()
