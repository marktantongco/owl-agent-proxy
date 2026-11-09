---
name: explain-analyzer
description: SQL EXPLAIN ANALYZE interpretation and bottleneck diagnosis. Use when a query is slow: read actual timing not estimates, find the dominant node, map it to a fix, then re-run EXPLAIN and record the delta.
source: owl-agent-proxy (migrated from a flat prompt file)
pipeline_stage: VERIFY
---

# explain-analyzer

## Context
SQL EXPLAIN ANALYZE interpretation and bottleneck diagnosis. Use when database queries are slow or need optimization.

## Instructions
1. Read Execution Time, Planning Time, Buffers
2. Identify the node with highest actual time (not estimated)
3. Check: Seq Scan? Nested Loop? High buffer I/O?
4. Map to fix: index, rewrite join, partition, cache tuning
5. Re-run EXPLAIN after fix. Document delta.

## Constraints
- Never optimize without EXPLAIN ANALYZE output
- If actual rows ≠ planned rows → run ANALYZE on table first
- If the fix doesn't work, the bottleneck was elsewhere. Admit it.

## Examples
**Input:** EXPLAIN ANALYZE showing Seq Scan on 10M row table
**Output:** Add partial index on WHERE column. Re-run. If no improvement, check for lock contention or connection pool exhaustion.
