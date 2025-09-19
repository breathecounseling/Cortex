"""
Plugin: calendar
Purpose: Sync Google Calendar
"""

from datetime import datetime, date, timezone
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple


def run():
    print("[calendar] Running placeholder task.")
    return {"status": "ok", "plugin": "calendar", "purpose": "Sync Google Calendar"}


def list_upcoming_events(
    events: Optional[Iterable[Dict[str, Any]]] = None,
    limit: int = 10,
    now: Optional[datetime] = None,
    include_ongoing: bool = True,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List upcoming events, sorted by start time ascending.

    Parameters:
      - events: Optional iterable of Google Calendar-like event dicts. If None, attempts
                to load from a JSON file (see 'source' or CALENDAR_EVENTS_PATH).
      - limit: Maximum number of events to return (default 10). Use <= 0 for no limit.
      - now: Reference datetime (UTC). Defaults to current UTC time.
      - include_ongoing: If True, includes events that have already started but not ended
                         (strictly now < end). If an event has started and has no end,
                         it is treated as ongoing.
      - source: Optional path to a JSON file containing an array of events. If not provided,
                uses CALENDAR_EVENTS_PATH env var or 'calendar_events.json' if present.

    Returns:
      A list of event dicts filtered to upcoming (and optionally ongoing) events.
      The returned dicts are the original event objects (not modified).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if events is None:
        events = _load_events_from_cache(source)

    prepared: List[Tuple[Dict[str, Any], Optional[datetime], Optional[datetime]]] = []
    for ev in events or []:
        # Skip cancelled events
        if isinstance(ev, dict) and ev.get("status") == "cancelled":
            continue
        start_dt = _extract_event_datetime(ev, key="start")
        end_dt = _extract_event_datetime(ev, key="end")
        prepared.append((ev, start_dt, end_dt))

    def is_upcoming(start: Optional[datetime], end: Optional[datetime]) -> bool:
        if start is None and end is None:
            return False
        if include_ongoing:
            # Upcoming if:
            # - Starts in the future
            if start is not None and start >= now:
                return True
            # - Already started and not yet ended (strict end)
            if start is not None and start <= now and (end is None or now < end):
                return True
            # - No start but has an end in the future (treat as ongoing/upcoming)
            if start is None and end is not None and now < end:
                return True
            return False
        else:
            # Only those starting at or after now
            return start is not None and start >= now

    filtered = [(ev, s, e) for (ev, s, e) in prepared if is_upcoming(s, e)]

    # Sort by start time (None goes last)
    filtered.sort(key=lambda item: (item[1] is None, item[1] or datetime.max.replace(tzinfo=timezone.utc)))

    # Apply limit
    if limit and limit > 0:
        filtered = filtered[:limit]

    return [ev for (ev, _, __) in filtered]


def _load_events_from_cache(source: Optional[str]) -> List[Dict[str, Any]]:
    """
    Load events from a JSON file. Returns an empty list if not found or invalid.

    Resolution order:
      1) Explicit 'source' argument
      2) Environment variable CALENDAR_EVENTS_PATH
      3) 'calendar_events.json' in current working directory (if exists)
    """
    path = source or os.environ.get("CALENDAR_EVENTS_PATH")
    if not path:
        default_path = os.path.join(os.getcwd(), "calendar_events.json")
        if os.path.isfile(default_path):
            path = default_path

    if not path:
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # Ensure each item is a dict
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    return []


def _extract_event_datetime(event: Dict[str, Any], key: str = "start") -> Optional[datetime]:
    """
    Extract and normalize an event start/end datetime to aware UTC datetime.

    Supports Google Calendar event shapes:
      - event[key] may be a dict with 'dateTime' (ISO8601) or 'date' (YYYY-MM-DD)
      - event[key] may be a string (ISO8601 or YYYY-MM-DD)
      - event[key] may be a datetime/date object
    """
    value: Any = event.get(key)
    if isinstance(value, dict):
        # Prefer dateTime, fallback to all-day 'date'
        if "dateTime" in value:
            return _parse_to_utc_datetime(value.get("dateTime"))
        if "date" in value:
            return _parse_to_utc_datetime(value.get("date"))
        # Some APIs may embed under 'time' or similar
        for alt in ("time", "startTime", "endTime", "value"):
            if alt in value:
                return _parse_to_utc_datetime(value.get(alt))
        return None
    return _parse_to_utc_datetime(value)


def _parse_to_utc_datetime(value: Any) -> Optional[datetime]:
    """
    Convert a variety of inputs to a timezone-aware UTC datetime.
    - str: ISO8601 (supports 'Z'), or 'YYYY-MM-DD' as all-day at 00:00 UTC
    - datetime: naive assumed UTC; aware converted to UTC
    - date: treated as 00:00 UTC of that date
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    if isinstance(value, date):
        # Treat all-day dates as midnight UTC
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Handle basic date-only strings
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            try:
                y, m, d = s.split("-")
                return datetime(int(y), int(m), int(d), tzinfo=timezone.utc)
            except Exception:
                return None
        # Normalize 'Z' suffix to +00:00 for fromisoformat
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            # Try common fallback formats
            for fmt in (
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(s, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.astimezone(timezone.utc)
                except Exception:
                    continue
    # Unknown type
    return None