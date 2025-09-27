Cortex Executor

Vision

Cortex Executor is a self-evolving executive-functioning manager. It takes natural language input and produces structured, tested, and functional code. It builds new modules on demand and routes future requests to those modules.

Core Principles

Chat-first at every interaction (powered by ChatGPT).

Parser always returns strict JSON contract.

Executor never scaffolds placeholders; all code must pass tests.

Every new module has a specialist with can_handle, handle, and describe_capabilities.

Registry auto-discovers specialists and updates routing.


Contracts

Router JSON Contract

{
  "assistant_message": "string",
  "mode": "brainstorming|clarification|execution",
  "questions": [{"id":"q1","scope":"fitness","question":"..."}],
  "ideas": ["..."],
  "facts_to_save": [{"key":"k","value":"v"}],
  "tasks_to_add": [{"title":"...", "priority":"normal|high"}],
  "actions": [
    {"plugin":"string","goal":"string","status":"pending|ready","args":{}}
  ],
  "directive_updates": {}
}

Specialist Template

def can_handle(intent: dict) -> bool: ...
def handle(intent: dict) -> dict: ...
def describe_capabilities() -> list[str]: ...

Plugin Manifest

{
  "name": "plugin_name",
  "description": "description",
  "capabilities": ["cap1","cap2"],
  "specialist": "executor.plugins.plugin_name.specialist"
}

Development Rules

No placeholders or stubs (unless explicitly requested).

All code changes must include tests and pass them.

On success, update manifest and refresh registry.

Flow must always follow: Brainstorm → Clarify → Plan → Build → Dispatch.


🧪 Test Suite Guide

The test suite is organized into three levels:

1. Unit tests (executor/tests/test_*.py)
Validate single modules in isolation. Examples:

test_manifests.py → all plugins have valid manifests + specialists.

test_dispatcher.py → Dispatcher calls specialists correctly.

test_task_planner.py → Task planner returns subtasks.



2. Integration tests (executor/tests/test_integration.py)
Validate foreground REPL loop with stubs. Examples:

test_chat_roundtrip → OpenAIClient call works.

test_repl_router_dispatcher_flow → REPL → Router → Dispatcher executes action.

test_full_cycle_repl_and_scheduler → foreground + background loops cooperate.



3. Scheduler tests (executor/tests/test_scheduler_smoke.py)
Validate background loop behavior. Examples:

Smoke tests for idle/brainstormed/worked.

Brainstorm test → Router produces ideas + actions, Dispatcher executes them.




📌 When adding new features

If you add a new core module (router, registry, dispatcher): put unit tests in a new file (test_router.py, test_registry.py, etc.).

If you add a new plugin type: ensure manifest + specialist tests pass (test_manifests.py).

If you extend REPL behavior: add or update a flow test in test_integration.py.

If you extend Scheduler autonomy: add or update a test in test_scheduler_smoke.py.


This ensures Executor always knows where to put new tests and how to keep coverage consistent.

References

See Executor Master Plan document for the full blueprint.
