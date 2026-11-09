---
name: code-generation
description: Production-grade code output with real tests and no placeholders. Use when implementing features, refactoring, or creating utilities: state the algorithm, name the trade-off, trace the happy path and one break case, then emit working code.
source: owl-agent-proxy (migrated from a flat prompt file)
pipeline_stage: BUILD
---

# code-generation

## Context
Production-grade code output with test coverage. Use when implementing features, refactoring, or creating utilities.

## Instructions
1. State the algorithm before the code
2. Explain the trade-off (speed vs. memory vs. readability)
3. Trace through an example (happy path + break case)
4. Output working code — no placeholders, no TODOs
5. Include inline tests or assertions where possible

## Constraints
- Never output pseudocode when the user asked for real code
- Never leave "[your code here]" or "insert here"
- Test logic mentally before presenting
- If a dependency is needed, state it explicitly

## Examples
**Input:** "Write a Python rate limiter"
**Output:** Full TokenBucket class with `acquire()`, `try_acquire()`, thread-safe implementation, unit tests, and usage example
