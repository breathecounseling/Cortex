"""
Cortex Self-Healer package.

Provides the Supervisor loop that runs pytest, parses failures,
consults the Executor/LLM for fixes, applies patches, and retries until green.
"""