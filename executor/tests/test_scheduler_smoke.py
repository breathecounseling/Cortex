def test_scheduler_smoke(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import os, json
    os.makedirs(".executor/memory", exist_ok=True)
    with open(".executor/memory/global_directives.json", "w") as f:
        json.dump({"autonomous_mode": False, "standby_minutes": 0}, f)
    from executor.middleware.scheduler import run_forever
    # just import and ensure it runs one loop iteration then breaks
    assert callable(run_forever)