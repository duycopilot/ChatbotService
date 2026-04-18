"""
Purpose: Validate extracted entities and required fields before executing an action
"""


async def validate_action(intent: str, message: str) -> tuple[bool, str]:
    """
    Validate that the required fields for an action are present and well-formed.
    Returns (is_valid, error_message).
    """
    # TODO: implement per-action validation rules
    return True, ""
