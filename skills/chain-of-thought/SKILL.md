---
name: chain-of-thought
description: Step-by-step reasoning process that breaks down complex problems into sequential logical steps, showing work before concluding. Supports zero-shot, few-shot, self-consistency, and tree-of-thought variants with optional self-verification.
source: Multiple implementations (lobehub, Wei 2022 framework, WebCOT)
pipeline_stage: PLAN
---

# chain-of-thought

**Pipeline Stage:** PLAN (Stage 2 – Plan & Architect)

**Purpose:** Apply explicit, step-by-step reasoning to complex problems during architectural design. Show the logical chain from premise to conclusion, enabling verification at each step before committing to implementation.

**When to use:** During the PLAN stage for architecture decisions, trade-off analysis, security reviews, and complex design reasoning. Especially useful in pipelines #2 (Feature Development), #9 (Architecture Review), and #10 (Full Product Delivery).

**Process:**
1. State the problem and known constraints
2. Break into sequential reasoning steps
3. Work through each step, showing evidence and logic
4. Identify assumptions and uncertainties at each step
5. Conclude with confidence level and reasoning trace

**CoT variants:**
| Variant | Description | Best For |
|---------|-------------|----------|
| Zero-shot | "Let's think step by step" | Simple planning decisions |
| Few-shot | Examples with reasoning | Complex architectural patterns |
| Self-consistency | Multiple paths, majority vote | High-stakes design decisions |
| Tree-of-Thought | Branch and evaluate | Exploring multiple architecture options |

**Handoff contract:**
- Input: Problem statement + constraints + design options
- Output: Reasoning trace + conclusion + confidence level
- Handoff to: BUILD stage (writing-plans → executing-plans)

**Install:** Custom skill — create at `skills/chain-of-thought/SKILL.md`
Reference: https://lobehub.com/skills/pluginagentmarketplace-custom-plugin-prompt-engineering-chain-of-thought

**Pipeline integration:** Used in pipelines #2, #5, #7, #9, #10 during PLAN for design reasoning.
