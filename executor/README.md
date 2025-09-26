# Cortex Executor

## Vision
Cortex Executor is a self-evolving executive-functioning manager. It takes natural language input and produces structured, tested, and functional code. It builds new modules on demand and routes future requests to those modules.

## Core Principles
- Chat-first at every interaction (powered by ChatGPT).
- Parser always returns strict JSON contract.
- Executor never scaffolds placeholders; all code must pass tests.
- Every new module has a **specialist** with `can_handle`, `handle`, `describe_capabilities`.
- Registry auto-discovers specialists and updates routing.

## Contracts

### Router JSON Contract
```json
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
