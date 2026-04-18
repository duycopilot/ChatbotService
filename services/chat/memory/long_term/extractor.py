"""LLM-backed extraction of durable long-term memories."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from services.chat.memory import MemoryTurn
from services.chat.memory.long_term.models import LongTermMemoryCandidate


logger = logging.getLogger(__name__)


_MUTABLE_FACT_ATTRIBUTE_KEYS = {
    "blood_pressure",
    "heart_rate",
    "respiratory_rate",
    "temperature",
    "spo2",
    "oxygen_saturation",
    "blood_sugar",
    "glucose_level",
    "weight",
    "weight_change",
    "bmi",
    "pain_score",
}

_LANGUAGE_CANONICAL_MAP = {
    "vi": "vi",
    "vietnamese": "vi",
    "tieng viet": "vi",
    "tiếng việt": "vi",
    "en": "en",
    "english": "en",
    "tieng anh": "en",
    "tiếng anh": "en",
}

_MUTABLE_NUMERIC_ATTRIBUTE_UNITS = {
    "blood_pressure": "mmHg",
    "heart_rate": "bpm",
    "respiratory_rate": "breaths/min",
    "temperature": "°C",
    "spo2": "%",
    "oxygen_saturation": "%",
    "blood_sugar": "mg/dL",
    "glucose_level": "mg/dL",
    "weight": "kg",
    "weight_change": "kg",
    "bmi": "kg/m²",
    "pain_score": None,
}


def _normalize_canonical_for_attribute(attribute_key: str, canonical_value: str) -> str:
    if attribute_key in _MUTABLE_FACT_ATTRIBUTE_KEYS:
        return "__latest__"

    if attribute_key == "communication_preference":
        normalized_lang = _normalize_text_value(canonical_value).casefold()
        normalized_lang = normalized_lang.replace("_", " ")
        return _LANGUAGE_CANONICAL_MAP.get(normalized_lang, normalized_lang or "unknown")

    normalized = _normalize_text_value(canonical_value)
    return normalized or "unknown"


def _normalize_language_text(text: str | None) -> str | None:
    normalized = _normalize_text_value(text)
    if not normalized:
        return None
    key = normalized.casefold().replace("_", " ")
    canonical = _LANGUAGE_CANONICAL_MAP.get(key)
    if canonical == "vi":
        return "tiếng Việt"
    if canonical == "en":
        return "English"
    return normalized


def _extract_bp_from_text(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None

    bp_pair = re.search(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b", text)
    if bp_pair:
        return int(bp_pair.group(1)), int(bp_pair.group(2))

    # e.g. "systolic 160" or "huyết áp tâm thu 160"
    systolic_match = re.search(r"(?:systolic|tâm thu)\D{0,8}(\d{2,3})", text, re.IGNORECASE)
    diastolic_match = re.search(r"(?:diastolic|tâm trương)\D{0,8}(\d{2,3})", text, re.IGNORECASE)
    systolic = int(systolic_match.group(1)) if systolic_match else None
    diastolic = int(diastolic_match.group(1)) if diastolic_match else None
    return systolic, diastolic


def _extract_mutable_numeric_value(attribute_key: str, text: str | None) -> tuple[float | None, str | None, dict | None]:
    if not text:
        return None, None, None

    lowered = text.casefold()
    patterns: list[tuple[str, str | None]] = []

    if attribute_key == "bmi":
        patterns = [
            (r"\b(?:bmi|body mass index)\b\s*(?:is|was|=|:)?\s*(\d{1,2}(?:\.\d+)?)", "kg/m²"),
            (r"\b(?:bmi|body mass index)\b\s*(\d{1,2}(?:\.\d+)?)", "kg/m²"),
        ]
    elif attribute_key == "weight":
        patterns = [
            (r"\bweight\b\s*(?:is|was|=|:)?\s*(\d{1,3}(?:\.\d+)?)\s*(kg|kgs|kilograms?|lb|lbs|pounds?)?\b", None),
            (r"\b(?:kg|kgs|kilograms?|lb|lbs|pounds?)\b\s*(\d{1,3}(?:\.\d+)?)", None),
        ]
    elif attribute_key == "weight_change":
        patterns = [
            (r"\b(?:weight\s*change|changed?|change in weight|tăng|giảm)\b\D{0,16}([+-]?\d{1,3}(?:\.\d+)?)\s*(kg|kgs|kilograms?)?\b", "kg"),
            (r"\b([+-]\d{1,3}(?:\.\d+)?)\s*(kg|kgs|kilograms?)\b", "kg"),
        ]
    elif attribute_key in {"blood_sugar", "glucose_level"}:
        patterns = [
            (r"\b(?:blood sugar|glucose)\b\s*(?:is|was|=|:)?\s*(\d{1,3}(?:\.\d+)?)\s*(mg/dl|mmol/l)?\b", "mg/dL"),
        ]
    elif attribute_key == "heart_rate":
        patterns = [(r"\b(?:heart rate|pulse)\b\s*(?:is|was|=|:)?\s*(\d{2,3})\s*(bpm)?\b", "bpm")]
    elif attribute_key == "respiratory_rate":
        patterns = [(r"\b(?:respiratory rate|rr|resp rate)\b\s*(?:is|was|=|:)?\s*(\d{1,2})\s*(breaths?/min|rpm)?\b", "breaths/min")]
    elif attribute_key == "temperature":
        patterns = [(r"\b(?:temperature|temp)\b\s*(?:is|was|=|:)?\s*(\d{2}(?:\.\d)?)\s*(°?c|c|f|°?f)?\b", "°C")]
    elif attribute_key in {"spo2", "oxygen_saturation"}:
        patterns = [(r"\b(?:spo2|oxygen saturation|o2 sat)\b\s*(?:is|was|=|:)?\s*(\d{2,3})\s*(%|percent)?\b", "%")]
    elif attribute_key == "pain_score":
        patterns = [(r"\b(?:pain score|pain)\b\s*(?:is|was|=|:)?\s*(\d(?:\.\d)?)\b", None)]

    for pattern, default_unit in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if not match:
            continue

        numeric_raw = match.group(1)
        try:
            numeric = float(numeric_raw)
        except (TypeError, ValueError):
            continue

        unit = default_unit
        if attribute_key in {"weight", "weight_change"} and len(match.groups()) >= 2:
            raw_unit = match.group(2)
            if raw_unit:
                if attribute_key == "weight":
                    unit = "lb" if raw_unit.casefold().startswith("l") else "kg"
                else:
                    unit = "kg"

        if attribute_key == "temperature" and len(match.groups()) >= 2:
            raw_unit = match.group(2)
            if raw_unit and raw_unit.casefold().replace("°", "") in {"f"}:
                unit = "°F"
            else:
                unit = "°C"

        if attribute_key in {"spo2", "oxygen_saturation"}:
            unit = "%"

        if attribute_key == "bmi":
            unit = "kg/m²"

        value_text = str(int(numeric)) if numeric.is_integer() else str(numeric)
        value_json = {"value": numeric}
        return numeric, unit, value_json

    return None, None, None


def _normalize_blood_pressure(
    *,
    value_text: str | None,
    value_json: dict | list | None,
    content: str,
) -> tuple[str | None, dict | None, str, str | None]:
    systolic: int | None = None
    diastolic: int | None = None

    if isinstance(value_json, dict):
        raw_sys = value_json.get("systolic")
        raw_dia = value_json.get("diastolic")
        try:
            systolic = int(raw_sys) if raw_sys is not None else None
        except (TypeError, ValueError):
            systolic = None
        try:
            diastolic = int(raw_dia) if raw_dia is not None else None
        except (TypeError, ValueError):
            diastolic = None

    parsed_from_value = _extract_bp_from_text(value_text)
    parsed_from_content = _extract_bp_from_text(content)

    # value_text has highest priority, then content, then raw value_json
    if parsed_from_value != (None, None):
        systolic, diastolic = parsed_from_value
    elif parsed_from_content != (None, None):
        systolic, diastolic = parsed_from_content

    normalized_json = None
    normalized_text = value_text
    if systolic is not None or diastolic is not None:
        normalized_json = {"systolic": systolic, "diastolic": diastolic}
        if systolic is not None and diastolic is not None:
            normalized_text = f"{systolic}/{diastolic} mmHg"
        elif systolic is not None:
            normalized_text = f"{systolic} mmHg"

    return normalized_text, normalized_json, "__latest__", "mmHg"


def _normalize_mutable_measurement(
    *,
    attribute_key: str,
    value_text: str | None,
    value_json: dict | list | None,
    content: str,
    unit: str | None,
) -> tuple[str | None, dict | list | None, str, str | None]:
    extracted_text = value_text or content
    numeric, extracted_unit, extracted_json = _extract_mutable_numeric_value(attribute_key, extracted_text)

    normalized_unit = unit or extracted_unit or _MUTABLE_NUMERIC_ATTRIBUTE_UNITS.get(attribute_key)
    normalized_json = value_json if isinstance(value_json, (dict, list)) else extracted_json
    normalized_text = value_text

    if numeric is not None:
        normalized_json = {"value": numeric}
        normalized_text = str(int(numeric)) if float(numeric).is_integer() else str(numeric)

    if attribute_key in {"weight", "weight_change"} and normalized_unit:
        normalized_text = f"{normalized_text} {normalized_unit}" if normalized_text else None
    elif attribute_key == "bmi":
        normalized_text = normalized_text or None
    elif attribute_key in {"blood_sugar", "glucose_level", "heart_rate", "respiratory_rate", "temperature", "spo2", "oxygen_saturation", "pain_score"}:
        normalized_text = normalized_text or None

    return normalized_text, normalized_json, "__latest__", normalized_unit


def _candidate_quality(candidate: LongTermMemoryCandidate) -> float:
    score = float(candidate.confidence)
    if candidate.attribute_key == "blood_pressure":
        if isinstance(candidate.value_json, dict):
            if candidate.value_json.get("systolic") is not None:
                score += 0.2
            if candidate.value_json.get("diastolic") is not None:
                score += 0.2
        if re.search(r"\b\d{2,3}\s*/\s*\d{2,3}\b", candidate.value_text or ""):
            score += 0.15
    if candidate.attribute_key == "communication_preference" and candidate.canonical_value in {"vi", "en"}:
        score += 0.1
    return score


def _strip_code_fences(text: str) -> str:
    """Extract JSON array or object from text, ignoring preamble."""
    cleaned = text.strip()
    
    # Remove code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    
    cleaned = cleaned.strip()
    
    # Try to find JSON array [...] FIRST
    json_start = cleaned.find('[')
    if json_start >= 0:
        json_end = cleaned.rfind(']')
        if json_end > json_start:
            logger.debug(f"Found JSON array at [{json_start}:{json_end+1}]")
            return cleaned[json_start:json_end+1]
    
    # Try to find JSON object {...}
    json_start = cleaned.find('{')
    if json_start >= 0:
        json_end = cleaned.rfind('}')
        if json_end > json_start:
            logger.debug(f"Found JSON object at {{{json_start}:{json_end+1}}}, but array would be better")
            return cleaned[json_start:json_end+1]
    
    # Return as-is and let _parse_candidates handle the error
    logger.debug(f"No JSON structure found, returning as-is (first 100 chars): {cleaned[:100]}")
    return cleaned


def _response_to_text(content: object) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for chunk in content:
            if isinstance(chunk, str):
                parts.append(chunk)
                continue
            if isinstance(chunk, dict):
                text = chunk.get("text") or chunk.get("output_text") or chunk.get("content")
                if text:
                    parts.append(str(text))
                continue
            text = getattr(chunk, "text", None) or getattr(chunk, "content", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts).strip()

    if content is None:
        return ""
    return str(content)


def _extract_balanced_json(text: str, opener: str, closer: str) -> str | None:
    depth = 0
    start = -1
    in_string = False
    escape = False

    for index, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == opener:
            if depth == 0:
                start = index
            depth += 1
            continue

        if ch == closer and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : index + 1]

    return None


def _sanitize_json(candidate: str) -> str:
    sanitized = candidate
    sanitized = sanitized.replace("\u201c", '"').replace("\u201d", '"')
    sanitized = sanitized.replace("\u2018", "'").replace("\u2019", "'")
    sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized)
    return sanitized.strip()


def _candidate_json_payloads(raw_text: str) -> list[str]:
    base = _strip_code_fences(raw_text)
    candidates: list[str] = []

    if base:
        candidates.append(base)

    array_json = _extract_balanced_json(base, "[", "]")
    if array_json:
        candidates.append(array_json)

    object_json = _extract_balanced_json(base, "{", "}")
    if object_json:
        candidates.append(object_json)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _clamp_confidence(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, numeric))


def _normalize_key(value: object, default: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or default


def _normalize_text_value(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _canonicalize_value(value_text: str | None, value_json: object) -> str:
    if value_json is not None:
        try:
            return json.dumps(value_json, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        except TypeError:
            pass
    return _normalize_key(value_text, "unknown")


def _parse_observed_at(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _build_content(
    *,
    attribute_key: str,
    value_text: str | None,
    value_json: dict | list | None,
    unit: str | None,
    fallback_content: str,
) -> str:
    if fallback_content.strip():
        return fallback_content.strip()

    if attribute_key == "allergy" and value_text:
        return f"Patient is allergic to {value_text}."
    if attribute_key == "medication_name" and value_text:
        return f"Patient takes {value_text}."
    if attribute_key == "chronic_condition" and value_text:
        return f"Patient has {value_text}."
    if attribute_key == "communication_preference" and value_text:
        return f"Patient prefers {value_text}."
    if attribute_key == "preferred_name" and value_text:
        return f"Patient prefers to be called {value_text}."
    if attribute_key == "blood_pressure" and isinstance(value_json, dict):
        systolic = value_json.get("systolic")
        diastolic = value_json.get("diastolic")
        if systolic and diastolic:
            suffix = f" {unit}" if unit else ""
            return f"Patient blood pressure was {systolic}/{diastolic}{suffix}."

    if attribute_key == "bmi" and value_text:
        suffix = f" {unit}" if unit else ""
        return f"Patient BMI was {value_text}{suffix}.".replace(f"{suffix}{suffix}", suffix)
    if attribute_key == "weight" and value_text:
        suffix = f" {unit}" if unit else ""
        return f"Patient weight was {value_text}{suffix}.".replace(f"{suffix}{suffix}", suffix)
    if attribute_key == "weight_change" and value_text:
        suffix = f" {unit}" if unit else ""
        return f"Patient weight changed by {value_text}{suffix}.".replace(f"{suffix}{suffix}", suffix)
    if attribute_key in {"blood_sugar", "glucose_level"} and value_text:
        suffix = f" {unit}" if unit else ""
        return f"Patient blood sugar was {value_text}{suffix}.".replace(f"{suffix}{suffix}", suffix)
    if attribute_key == "heart_rate" and value_text:
        suffix = f" {unit}" if unit else ""
        return f"Patient heart rate was {value_text}{suffix}.".replace(f"{suffix}{suffix}", suffix)
    if attribute_key == "respiratory_rate" and value_text:
        suffix = f" {unit}" if unit else ""
        return f"Patient respiratory rate was {value_text}{suffix}.".replace(f"{suffix}{suffix}", suffix)
    if attribute_key == "temperature" and value_text:
        suffix = f" {unit}" if unit else ""
        return f"Patient temperature was {value_text}{suffix}.".replace(f"{suffix}{suffix}", suffix)
    if attribute_key in {"spo2", "oxygen_saturation"} and value_text:
        suffix = f" {unit}" if unit else ""
        return f"Patient oxygen saturation was {value_text}{suffix}.".replace(f"{suffix}{suffix}", suffix)
    if attribute_key == "pain_score" and value_text:
        return f"Patient pain score was {value_text}."

    if value_text:
        label = attribute_key.replace("_", " ")
        return f"Patient {label}: {value_text}."
    return ""


class LongTermMemoryExtractor:
    def __init__(
        self,
        *,
        llm,
        prompt_template: str,
        max_items: int,
        min_confidence: float,
        max_content_chars: int,
    ) -> None:
        self.llm = llm
        self.prompt_template = prompt_template
        self.max_items = max(1, max_items)
        self.min_confidence = max(0.0, min(1.0, min_confidence))
        self.max_content_chars = max(64, max_content_chars)

    async def extract(
        self,
        *,
        user_message: str,
        assistant_message: str,
        recent_turns: list[MemoryTurn] | None = None,
    ) -> list[LongTermMemoryCandidate]:
        llm_candidates = await self._extract_with_llm(
            user_message=user_message,
            assistant_message=assistant_message,
            recent_turns=recent_turns or [],
        )
        fallback_candidates = self._fallback_extract(user_message)

        by_identity: dict[str, LongTermMemoryCandidate] = {}
        for candidate in [*llm_candidates, *fallback_candidates]:
            identity = "|".join(
                [
                    candidate.entity_type,
                    candidate.entity_key.casefold(),
                    candidate.attribute_key,
                    candidate.canonical_value.casefold(),
                ]
            )
            existing = by_identity.get(identity)
            if existing is None or _candidate_quality(candidate) > _candidate_quality(existing):
                by_identity[identity] = candidate

        merged = sorted(by_identity.values(), key=_candidate_quality, reverse=True)[: self.max_items]

        logger.debug(
            "Extracted long-term candidates: llm=%s fallback=%s merged=%s",
            len(llm_candidates),
            len(fallback_candidates),
            len(merged),
        )
        return merged

    async def _extract_with_llm(
        self,
        *,
        user_message: str,
        assistant_message: str,
        recent_turns: list[MemoryTurn],
    ) -> list[LongTermMemoryCandidate]:
        if self.llm is None:
            return []

        history_text = self._format_history(recent_turns)
        prompt = self.prompt_template.format(
            history_text=history_text,
            user_message=user_message,
            assistant_message=assistant_message,
            max_items=self.max_items,
        )
        try:
            response = await self.llm.ainvoke(
                [
                    SystemMessage(content="You are a JSON extraction assistant. You MUST respond with ONLY a valid JSON array. No explanations, no text before or after. Just the JSON."),
                    HumanMessage(content=prompt),
                ]
            )
        except Exception as e:
            logger.warning(f"LLM extraction failed, fallback to regex: {e}")
            return []

        response_text = _response_to_text(getattr(response, "content", ""))
        logger.debug("LLM raw response (first 250 chars): %r", response_text[:250])
        logger.debug("LLM response total length: %s", len(response_text))

        return self._parse_candidates(response_text)

    def _parse_candidates(self, raw_text: str) -> list[LongTermMemoryCandidate]:
        cleaned_raw = _response_to_text(raw_text)
        if not cleaned_raw:
            logger.debug(f"LLM response empty after strip")
            return []

        payload = None
        parse_error: Exception | None = None
        for candidate_text in _candidate_json_payloads(cleaned_raw):
            for variant in (candidate_text, _sanitize_json(candidate_text)):
                try:
                    payload = json.loads(variant)
                    break
                except json.JSONDecodeError as e:
                    parse_error = e
            if payload is not None:
                break

        if payload is None:
            logger.warning("LLM response JSON parse failed: %s", parse_error)
            logger.debug("Raw text (first 300 chars): %s", cleaned_raw[:300])
            return []

        if isinstance(payload, dict):
            payload = payload.get("memories", [])
        if not isinstance(payload, list):
            return []

        candidates: list[LongTermMemoryCandidate] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue

            entity_type = _normalize_key(item.get("entity_type", "patient"), "patient")
            entity_key = _normalize_text_value(item.get("entity_key", "self")) or "self"
            attribute_key = _normalize_key(item.get("attribute_key") or item.get("attribute"), "general_fact")
            value_text = _normalize_text_value(item.get("value_text")) or None
            raw_value_json = item.get("value_json")
            value_json = raw_value_json if isinstance(raw_value_json, (dict, list)) else None
            canonical_value = _normalize_text_value(item.get("canonical_value")) or _canonicalize_value(value_text, value_json)
            content = _build_content(
                attribute_key=attribute_key,
                value_text=value_text,
                value_json=value_json,
                unit=_normalize_text_value(item.get("unit")) or None,
                fallback_content=str(item.get("content", "")),
            )

            if attribute_key == "communication_preference":
                value_text = _normalize_language_text(value_text)
                canonical_value = _normalize_canonical_for_attribute(
                    attribute_key,
                    canonical_value or (value_text or ""),
                )

            if attribute_key == "blood_pressure":
                value_text, value_json, canonical_value, normalized_unit = _normalize_blood_pressure(
                    value_text=value_text,
                    value_json=value_json,
                    content=content,
                )
                unit = normalized_unit
            elif attribute_key in _MUTABLE_FACT_ATTRIBUTE_KEYS:
                value_text, value_json, canonical_value, normalized_unit = _normalize_mutable_measurement(
                    attribute_key=attribute_key,
                    value_text=value_text,
                    value_json=value_json,
                    content=content,
                    unit=_normalize_text_value(item.get("unit")) or None,
                )
                unit = normalized_unit
            else:
                canonical_value = _normalize_canonical_for_attribute(attribute_key, canonical_value)
                unit = _normalize_text_value(item.get("unit")) or None

            content = _build_content(
                attribute_key=attribute_key,
                value_text=value_text,
                value_json=value_json,
                unit=unit,
                fallback_content=str(item.get("content", "")),
            )
            if not content:
                continue
            if len(content) > self.max_content_chars:
                continue

            normalized = "|".join([entity_type, entity_key.casefold(), attribute_key, canonical_value.casefold()])
            if normalized in seen:
                continue

            confidence = _clamp_confidence(item.get("confidence", 0.5))
            if confidence < self.min_confidence:
                continue

            category = str(item.get("category", "general")).strip().lower() or "general"
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            seen.add(normalized)
            candidates.append(
                LongTermMemoryCandidate(
                    entity_type=entity_type,
                    entity_key=entity_key,
                    attribute_key=attribute_key,
                    value_text=value_text,
                    value_json=value_json,
                    canonical_value=canonical_value,
                    unit=unit,
                    content=content,
                    category=category,
                    clinical_status=_normalize_key(item.get("clinical_status"), "") or None,
                    verification_status=_normalize_key(item.get("verification_status", "self_reported"), "self_reported"),
                    confidence=confidence,
                    observed_at=_parse_observed_at(item.get("observed_at")),
                    metadata=metadata,
                )
            )

        return candidates

    def _fallback_extract(self, user_message: str) -> list[LongTermMemoryCandidate]:
        text = user_message.strip()
        lowered = text.casefold()
        patterns = [
            (r"\bcall me\s+([A-Za-z][A-Za-z\s'-]{1,40})", "preferred_name", "profile", "Patient prefers to be called {value}."),
            (r"\bi prefer\s+(.{3,80})", "communication_preference", "preference", "Patient prefers {value}."),
            (r"\bi am allergic to\s+(.{3,80})", "allergy", "allergy", "Patient is allergic to {value}."),
            (r"\bi'm allergic to\s+(.{3,80})", "allergy", "allergy", "Patient is allergic to {value}."),
            (r"\bi take\s+(.{3,80})", "medication_name", "medication", "Patient takes {value}."),
            (r"\bi am taking\s+(.{3,80})", "medication_name", "medication", "Patient takes {value}."),
            (r"\bi have\s+(.{3,80})", "chronic_condition", "condition", "Patient has {value}."),
            (r"\bi was diagnosed with\s+(.{3,80})", "chronic_condition", "condition", "Patient has {value}."),
        ]

        candidates: list[LongTermMemoryCandidate] = []
        blood_pressure_match = re.search(r"\b(?:blood pressure|bp)\s*(?:is|was)?\s*(\d{2,3})\s*/\s*(\d{2,3})", lowered, re.IGNORECASE)
        if blood_pressure_match:
            systolic = int(blood_pressure_match.group(1))
            diastolic = int(blood_pressure_match.group(2))
            candidates.append(
                LongTermMemoryCandidate(
                    attribute_key="blood_pressure",
                    value_json={"systolic": systolic, "diastolic": diastolic},
                    canonical_value="__latest__",
                    unit="mmHg",
                    category="vital_sign",
                    clinical_status="reported",
                    verification_status="self_reported",
                    content=f"Patient blood pressure was {systolic}/{diastolic} mmHg.",
                    confidence=0.76,
                )
            )

        numeric_patterns = [
            ("bmi", r"\b(?:bmi|body mass index)\b\s*(?:is|was|=|:)\s*(\d{1,2}(?:\.\d+)?)", "metric", "Patient BMI was {value}.", "kg/m²"),
            ("weight", r"\bweight\b\s*(?:is|was|=|:)\s*(\d{1,3}(?:\.\d+)?)\s*(kg|kgs|kilograms?|lb|lbs|pounds?)?\b", "metric", "Patient weight was {value}{unit}.", None),
            ("weight_change", r"\b(?:weight\s*change|changed?|change in weight|tăng|giảm)\b\D{0,16}([+-]?\d{1,3}(?:\.\d+)?)\s*(kg|kgs|kilograms?)?\b", "body_metric", "Patient weight changed by {value}{unit}.", "kg"),
            ("blood_sugar", r"\b(?:blood sugar|glucose)\b\s*(?:is|was|=|:)\s*(\d{1,3}(?:\.\d+)?)\s*(mg/dl|mmol/l)?\b", "metric", "Patient blood sugar was {value}{unit}.", "mg/dL"),
            ("heart_rate", r"\b(?:heart rate|pulse)\b\s*(?:is|was|=|:)\s*(\d{2,3})\s*(bpm)?\b", "metric", "Patient heart rate was {value} bpm.", "bpm"),
            ("respiratory_rate", r"\b(?:respiratory rate|rr|resp rate)\b\s*(?:is|was|=|:)\s*(\d{1,2})\s*(breaths?/min|rpm)?\b", "metric", "Patient respiratory rate was {value} breaths/min.", "breaths/min"),
            ("temperature", r"\b(?:temperature|temp)\b\s*(?:is|was|=|:)\s*(\d{2}(?:\.\d)?)\s*(°?c|c|f|°?f)?\b", "metric", "Patient temperature was {value}{unit}.", "°C"),
            ("spo2", r"\b(?:spo2|oxygen saturation|o2 sat)\b\s*(?:is|was|=|:)\s*(\d{2,3})\s*(%|percent)?\b", "metric", "Patient oxygen saturation was {value}%.", "%"),
            ("pain_score", r"\b(?:pain score|pain)\b\s*(?:is|was|=|:)\s*(\d(?:\.\d)?)\b", "metric", "Patient pain score was {value}.", None),
        ]

        for attribute_key, pattern, category, template, default_unit in numeric_patterns:
            match = re.search(pattern, lowered, re.IGNORECASE)
            if not match:
                continue

            raw_value = match.group(1)
            try:
                numeric = float(raw_value)
            except (TypeError, ValueError):
                continue

            unit = default_unit
            if attribute_key in {"weight", "weight_change"} and len(match.groups()) >= 2:
                raw_unit = match.group(2)
                if raw_unit:
                    if attribute_key == "weight":
                        unit = "lb" if raw_unit.casefold().startswith("l") else "kg"
                    else:
                        unit = "kg"
            elif attribute_key == "temperature" and len(match.groups()) >= 2:
                raw_unit = match.group(2)
                if raw_unit and raw_unit.casefold().replace("°", "") == "f":
                    unit = "°F"
                else:
                    unit = "°C"

            value_text = str(int(numeric)) if numeric.is_integer() else str(numeric)
            if attribute_key in {"weight", "weight_change"} and unit:
                value_text = f"{value_text} {unit}"

            candidates.append(
                LongTermMemoryCandidate(
                    attribute_key=attribute_key,
                    value_text=value_text,
                    value_json={"value": numeric},
                    canonical_value="__latest__",
                    unit=unit,
                    category=category,
                    clinical_status="reported",
                    verification_status="self_reported",
                    content=template.format(value=value_text if attribute_key not in {"weight", "weight_change"} else value_text.replace(f" {unit}", ""), unit=f" {unit}" if unit and attribute_key not in {"weight", "weight_change"} else (f" {unit}" if unit else "")),
                    confidence=0.74,
                )
            )

        for pattern, attribute_key, category, template in patterns:
            match = re.search(pattern, lowered, re.IGNORECASE)
            if not match:
                continue

            start, end = match.span(1)
            value = text[start:end].strip(" .,!?")
            if not value:
                continue

            candidates.append(
                LongTermMemoryCandidate(
                    attribute_key=attribute_key,
                    value_text=value,
                    canonical_value=_canonicalize_value(value, None),
                    content=template.format(value=value),
                    category=category,
                    clinical_status="reported",
                    verification_status="self_reported",
                    confidence=0.72,
                )
            )

        return candidates

    @staticmethod
    def _format_history(recent_turns: list[MemoryTurn]) -> str:
        if not recent_turns:
            return ""

        lines: list[str] = []
        for turn in recent_turns[-6:]:
            content = str(turn.content).strip()
            if not content:
                continue
            role = str(turn.role).strip().lower() or "unknown"
            lines.append(f"{role}: {content}")
        return "\n".join(lines)