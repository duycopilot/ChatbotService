"""
Purpose: Validate intent labels returned by LLM classification
"""


def validate_intent_label(label: str):
    """
    Validate and convert label string to Intent enum.
    Returns (is_valid, intent_or_none).
    Imports Intent inside to avoid circular import.
    """
    from services.chat.intent.classifier import Intent

    normalized_label = str(label).strip().lower()
    try:
        intent = Intent(normalized_label)
        return True, intent
    except ValueError:
        return False, None
