"""Data structures for long-term memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class LongTermMemoryCandidate:
    content: str
    entity_type: str = "patient"
    entity_key: str = "self"
    attribute_key: str = "general_fact"
    value_text: str | None = None
    value_json: dict[str, Any] | list[Any] | None = None
    canonical_value: str = ""
    unit: str | None = None
    category: str = "general"
    clinical_status: str | None = None
    verification_status: str = "self_reported"
    confidence: float = 0.5
    observed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LongTermMemoryRecord:
    id: str
    user_id: str
    conversation_id: str | None
    source_message_id: str | None
    entity_type: str
    entity_key: str
    attribute_key: str
    value_text: str | None
    value_json: dict[str, Any] | list[Any] | None
    canonical_value: str
    unit: str | None
    vector_id: str
    category: str
    clinical_status: str | None
    verification_status: str
    content: str
    confidence: float
    observed_at: datetime | None = None
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_accessed_at: datetime | None = None