"""
Plugin: calendar_plugin
Purpose: Sync with Google Calendar
"""

from datetime import datetime, date, timedelta, timezone
from typing import Iterable, Mapping, Any, Optional, List, Tuple


def run():
    print("[calendar_plugin] Running placeholder task.")
    return {"status": "ok", "plugin": "calendar_plugin", "purpose": "Sync with Google Calendar"}


def _parse_iso_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    # Support missing timezone by treating as naive; will convert to UTC later
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # Fallback for formats without separators, best-effort
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            # As last resort, try date-only
            return datetime.combine(date.fromisoformat(value), datetime.min.time())


def _ensure_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        return _parse_iso_datetime(value)
    raise TypeError(f"Unsupported datetime value type: {type(value)!r}")


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_event_times(event: Mapping[str, Any]) -> Tuple[datetime, datetime, bool]:
    """
    Returns (start_dt_utc, end_dt_utc, is_all_day)
    Supports Google Calendar-like payloads and simplified formats.
    """
    start_raw = None
    end_raw = None
    all_day = False

    # Prefer Google Calendar shape if present
    if isinstance(event.get("start"), dict):
        s = event["start"]
        if "dateTime" in s:
            start_raw = s["dateTime"]
        elif "date" in s:
            # All-day event: date only
            all_day = True
            start_raw = s["date"]
    elif "start" in event:
        start_raw = event["start"]
    elif "start_time" in event:
        start_raw = event["start_time"]

    if isinstance(event.get("end"), dict):
        e = event["end"]
        if "dateTime" in e:
            end_raw = e["dateTime"]
        elif "date" in e:
            all_day = True
            end_raw = e["date"]
    elif "end" in event:
        end_raw = event["end"]
    elif "end_time" in event:
        end_raw = event["end_time"]

    if start_raw is None:
        raise ValueError("Event missing start time")

    start_dt = _ensure_datetime(start_raw)
    # All-day event end handling (Google Calendar end 'date' is exclusive)
    if end_raw is None:
        if all_day:
            # If only start date is known, assume 1-day all-day event
            end_dt = _ensure_datetime(start_dt.date() + timedelta(days=1))
        else:
            # Default 1 hour duration
            end_dt = start_dt + timedelta(hours=1)
    else:
        end_dt = _ensure_datetime(end_raw)
        if all_day and isinstance(end_raw, (str, date)) and not isinstance(end_raw, datetime):
            # Google Calendar all-day 'end' date is exclusive, leave as-is
            pass

    # Convert to UTC
    start_utc = _to_utc(start_dt)
    end_utc = _to_utc(end_dt)

    return start_utc, end_utc, all_day


def list_upcoming_events(
    events: Optional[Iterable[Mapping[str, Any]]] = None,
    limit: int = 10,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    include_ongoing: bool = True,
    now: Optional[Any] = None,
) -> List[Mapping[str, Any]]:
    """
    List upcoming events from a sequence of events.

    Parameters:
    - events: iterable of event dicts. Supports Google Calendar-like shape:
        {
          "summary": "...",
          "start": {"dateTime": "...", "timeZone": "..." } or {"date": "YYYY-MM-DD"},
          "end":   {"dateTime": "...", "timeZone": "..." } or {"date": "YYYY-MM-DD"}
        }
      Also supports simplified keys: "start", "end" as ISO strings or datetime objects.
      If None, returns an empty list.
    - limit: maximum number of events to return (default 10).
    - start: optional lower bound (datetime/date/ISO string). Defaults to 'now'.
    - end: optional upper bound (datetime/date/ISO string). If provided, events starting after this are excluded.
    - include_ongoing: if True, include events that have already started but not yet ended.
    - now: override current time for evaluation (datetime/date/ISO string).

    Returns:
    - A list of event dicts (original items) sorted by start time ascending.
    """
    if not events:
        return []

    # Determine anchor times
    if now is None:
        now_utc = datetime.now(timezone.utc)
    else:
        now_utc = _to_utc(_ensure_datetime(now))

    lower_bound_utc = _to_utc(_ensure_datetime(start)) if start is not None else now_utc
    upper_bound_utc = _to_utc(_ensure_datetime(end)) if end is not None else None

    prepared = []
    for ev in events:
        try:
            s_utc, e_utc, _ = _extract_event_times(ev)
        except Exception:
            # Skip malformed events
            continue

        # Determine inclusion:
        # - If include_ongoing: include if event ends at/after lower bound.
        # - Else: include only if event starts at/after lower bound.
        if include_ongoing:
            overlaps_lower = e_utc >= lower_bound_utc
        else:
            overlaps_lower = s_utc >= lower_bound_utc

        within_upper = True if upper_bound_utc is None else (s_utc <= upper_bound_utc)

        if overlaps_lower and within_upper:
            prepared.append((s_utc, ev))

    # Sort by start time
    prepared.sort(key=lambda x: x[0])

    # Apply limit
    if limit is not None and limit >= 0:
        prepared = prepared[:limit]

    # Return original event dicts
    return [ev for _, ev in prepared]
