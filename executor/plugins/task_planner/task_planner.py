"""
Task Planner plugin
Accepts a goal string and returns a list of subtasks (stub).
"""

def plan(goal: str) -> dict:
    """Simple starter plan — Extender will improve this."""
    g = (goal or "").strip()
    return {
        "goal": g,
        "subtasks": [
            {"id": 1, "title": f"Research: {g}"},
            {"id": 2, "title": f"Draft: {g}"},
            {"id": 3, "title": f"Review & refine: {g}"},
        ],
    }

def run():
    return {"status": "ok", "plugin": "task_planner", "purpose": "Break goals into subtasks (stub)."}
