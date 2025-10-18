def due_within_days(session_id: str, within_days: int=3) -> List[Dict]:
    """Filter goals due within N days. If within_days == 0, match only today's date."""
    import datetime, dateutil.parser as dp
    res = []
    today = datetime.date.today()
    for g in get_open_goals(session_id):
        d = (g.get("deadline") or "").strip()
        if not d:
            continue
        try:
            dt = dp.parse(d, fuzzy=True)
            delta = (dt.date() - today).days
            if within_days == 0:
                if dt.date() == today:
                    res.append(g)
            elif 0 <= delta <= within_days:
                res.append(g)
        except Exception:
            continue
    return res