"""Purpose: normalize time data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
	from zoneinfo import ZoneInfo

	VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:  # pragma: no cover
	# Fallback for environments without IANA timezone database.
	VN_TZ = timezone(timedelta(hours=7), name="ICT")


def now_vn() -> datetime:
	"""Return current datetime in Vietnam timezone."""
	return datetime.now(VN_TZ)


def to_vn(dt: datetime) -> datetime:
	"""Convert a datetime to Vietnam timezone."""
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=timezone.utc)
	return dt.astimezone(VN_TZ)