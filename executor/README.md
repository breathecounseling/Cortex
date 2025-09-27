Cortex Executor — Assistant Guidance

Project Purpose

Cortex Executor is a self-evolving executive-functioning manager.
It runs locally and in the cloud, interprets natural language, builds or extends modular plugins, routes requests to specialists, and self-improves over time.

You (the assistant) act as the reasoning layer — every human-machine interaction must use ChatGPT for interpretation, not simple rules.


---

Key Roles

Butler: Conversational partner. Always chat-first, asks clarifying questions.

Parser / Router: Enforces schema. Must output strict JSON contract (no free text actions).

Executor: Builds/extends plugins. Runs tests, self-repairs until success. Updates manifests + registry.

Specialists: Domain brains for each module. Must expose can_handle, handle, describe_capabilities.

Registry: Maps intents to specialists. Auto-refreshes when plugins are built/extended.

Dispatcher: Calls the appropriate specialist to fulfill an action.



---

Lifecycle

Every request must follow:
Big Idea → Clarification → Planning → Execution → Routing

1. Brainstorming: collect questions/ideas until scope is clear.


2. Clarification: save facts, mark action ready.


3. Planning: use Task Planner to break into subtasks.


4. Execution: extend_plugin ensures tested code + specialist exist.


5. Routing: future requests dispatched to specialist.




---

Development Guardrails

No stub code — every plugin must include tests and pass them.

Parser never guesses — always ask clarifying questions until intent is clear.

Executor must repair failed builds before merging.

Facts persist across sessions (conversation_manager).

All new modules must include a specialist + manifest entry.



---

Repo Integration

executor/core/ → router, registry, dispatcher (core orchestration).

executor/connectors/repl.py → REPL loop (foreground chat).

executor/middleware/scheduler.py → background loop (autonomous brainstorms).

executor/plugins/builder/ → builder + extender (plugin creation and extension).

executor/plugins/conversation_manager/ → turn and fact persistence.

executor/plugins/repo_analyzer/ → scans repo for manifests + symbols.

executor/plugins/task_planner/ → breaks high-level goals into subtasks.



---

🧪 Test Suite Guide

Tests are organized into three levels:

1. Unit tests (executor/tests/test_*.py)
Validate modules in isolation. Examples:

test_manifests.py → manifests + specialists valid.

test_dispatcher.py → Dispatcher contract.

test_task_planner.py → subtask breakdown.



2. Integration tests (executor/tests/test_integration.py)
Validate REPL flow. Examples:

test_chat_roundtrip → OpenAIClient call.

test_repl_router_dispatcher_flow → REPL → Router → Dispatcher executes.

test_full_cycle_repl_and_scheduler → foreground + background loops cooperate.



3. Scheduler tests (executor/tests/test_scheduler_smoke.py)
Validate background loop. Examples:

Smoke test for idle/brainstormed/worked.

Brainstorm test → Router returns ideas + Dispatcher executes them.




📌 When self-developing new features

New core module → add tests in new file (test_router.py, test_registry.py).

New plugin → ensure specialist + manifest present, tests in test_manifests.py.

New REPL flow → extend test_integration.py.

New Scheduler autonomy → extend test_scheduler_smoke.py.


Always add unit + integration coverage for new functionality.


---

Reasoning Reminders

Always interpret user input conversationally (Butler voice).

Always output structured JSON (Router contract) behind the scenes.

Never allow placeholders/stubs unless explicitly requested.

Always create or update tests alongside code changes.

Always update plugin manifests to include new capabilities + specialist path.



---

Router Output Examples

These are golden reference JSON responses you should use when reasoning about Router behavior.

Brainstorming Example

{
  "assistant_message": "Got it. When you say fitness tracker, should it track workouts only, or also nutrition and bodyweight?",
  "mode": "brainstorming",
  "questions": [
    {"id": "q1", "scope": "fitness_tracker", "question": "Should this track workouts, nutrition, or bodyweight?"}
  ],
  "ideas": ["Workouts", "Nutrition", "Bodyweight"],
  "facts_to_save": [],
  "tasks_to_add": [],
  "directive_updates": {},
  "actions": []
}

Clarification Example

{
  "assistant_message": "Great — I'll set this up to track workouts and bodyweight.",
  "mode": "clarification",
  "questions": [],
  "ideas": ["Workout logging", "Bodyweight tracking"],
  "facts_to_save": [
    {"key": "fitness_tracker_features", "value": "workouts + bodyweight"}
  ],
  "tasks_to_add": [],
  "directive_updates": {},
  "actions": [
    {"plugin": "fitness_tracker", "goal": "log workouts and bodyweight", "status": "pending", "args": {}}
  ]
}

Execution Example

{
  "assistant_message": "I'll scaffold the fitness tracker with workout + bodyweight logging now.",
  "mode": "execution",
  "questions": [],
  "ideas": [],
  "facts_to_save": [],
  "tasks_to_add": [],
  "directive_updates": {},
  "actions": [
    {"plugin": "fitness_tracker", "goal": "log workouts and bodyweight", "status": "ready", "args": {}}
  ]
}
