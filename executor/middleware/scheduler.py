"""
Scheduler module
Would manage task queueing, retries, and scheduling.
For now, just runs router once.
"""

from executor.middleware import router

def run_once(task: str):
    plugin = router.handle_task(task)
    print(f"[Scheduler] Task '{task}' routed to: {plugin}")

if __name__ == "__main__":
    run_once("Generate a bizops report")
