# Skill: decision-tree

## Context
Branching logic maps with condition coverage. Use when routing decisions, choosing architectures, or building rule engines.

## Instructions
1. Start with the root question
2. Map every branch: if X then Y, if A then B
3. Ensure all branches terminate — no infinite loops
4. Label each leaf node with the action to take
5. Present as ASCII tree or nested markdown

## Constraints
- Every branch must have a condition
- Every leaf must have an action
- No branch should be "else do nothing" — make the default explicit

## Examples
**Input:** "How do I choose a proxy?"
**Output:** Tree: Need unlimited? → Yes → Anti-bot critical? → Yes → Mobile proxy. No → Budget? → Yes → Datacenter. No → ISP.
