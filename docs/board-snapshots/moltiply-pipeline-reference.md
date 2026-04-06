# Moltiply Pipeline Board — Reference Snapshot

**Date:** 2026-04-04
**Board ID:** `a30dd92a-f96f-45b3-add6-6294846dd2d4`
**Project ID:** `e84c28e4-3784-4122-ae5c-7871231de7ab`
**Purpose:** Reference architecture for A-Priori pipeline redesign

---

## Columns (8)

| # | Name | Type | WIP | ID | Goal | Prompt Doc |
|---|------|------|-----|----|------|------------|
| 1 | Epic Planning | start | - | `55f15969-f310-4d78-8fb3-42c853779cc9` | Analyze the game spec, codebase, and browser state to propose the next epic. Transform the seed ticket into a detailed epic and move to Decomposition. | Prompt: Epic Planning (`3454a36b`) |
| 2 | Decomposition | in_progress | - | `efc66e10-b138-407b-b4ad-aab0b201a007` | Break the epic into implementable tickets with dependency links. Create the next cycle's seed ticket. Archive the epic. | Prompt: Decomposition (`90853343`) |
| 3 | Implementation | in_progress | - | `ea93615c-ca2e-4c0b-995a-e0071bd6b0c2` | Implement the code changes, write tests, verify in the browser, commit to a feature branch, and move to Code Review. | Prompt: Implementation (`a496a9c4`) |
| 4 | Code Review | in_progress | - | `11e17c53-d458-44d5-bc8f-9785c8f5d19b` | Independently verify code quality, convention compliance, and browser behavior. Approve or reject with detailed feedback. | Prompt: Code Review (`18eb5370`) |
| 5 | Secondary Review | in_progress | - | `7706774e-1d84-41ce-950b-ab3ba3b11654` | Independent audit of code quality, convention compliance, and browser behavior. Approve to Merge or reject to Implementation. | Prompt: Secondary Review (`b2eb7ca8`) |
| 6 | Merge | in_progress | - | `a8d8c7a6-a5d7-48c4-bc77-86f0291d14f3` | Safely merge the feature branch into main with --no-ff. Run tests. Delete the branch. Move to Done. | Prompt: Merge (`fabd91cf`) |
| 7 | Done | done | - | `943d380c-6936-407e-b167-4dbca929227c` | - | - |
| 8 | Escalation | default | - | `323744c5-11dc-4d9f-b7e8-085880bb224c` | - | - |

## Transition Rules (12)

| From | To | Notes |
|------|----|-------|
| Epic Planning | Decomposition | Epic is ready for decomposition into implementation tickets. |
| Epic Planning | Escalation | Epic planning failed. |
| Decomposition | Escalation | Decomposition failed. |
| Implementation | Code Review | Implementation complete. Requires branch_name field. |
| Implementation | Escalation | Implementation failed after retries. |
| Code Review | Secondary Review | Code review passed. |
| Code Review | Escalation | Code review escalation. |
| Secondary Review | Merge | Approved by secondary reviewer. |
| Secondary Review | Implementation | Rejected — back to implementation for rework. |
| Secondary Review | Escalation | Secondary review escalation. |
| Merge | Done | Successfully merged. |
| Merge | Escalation | Merge failed. |

**Key pattern:** Every pipeline column can transition to Escalation. This is the safety valve.

## Transition Requirements (1)

| Target Column | Required Field | Notes |
|---------------|----------------|-------|
| Code Review | `branch_name` (`30146994`) | Must set the feature branch name before entering code review. |

## Custom Fields (2)

| Name | Type | ID |
|------|------|----|
| branch_name | short_text | `30146994-91bd-4b8a-8ed7-992bec97db5e` |
| epic_ref | short_text | `2aa64f78-27d4-476f-8f28-fc4013c9054e` |

## Dependency Requirements

None configured. Ordering enforced via ticket blocker links and firing constraints.

## Circuit Breaker

- **Threshold:** 2 backward transitions
- **Target:** Escalation column (`323744c5`)

After 2 backward moves (e.g., Secondary Review → Implementation), the entire pipeline freezes. Every column checks `board.circuit_breaker_count eq "0"` before firing.

## Firing Constraints (24)

### Per-Column "Minimum Tickets" (triggers agent when work arrives)

| Column | Constraint |
|--------|-----------|
| Epic Planning | `column.ticket_count gt 0` |
| Decomposition | `column.ticket_count gt 0` |
| Implementation | `column.ticket_count gt 0` |
| Code Review | `column.ticket_count gt 0` |
| Secondary Review | `column.ticket_count gt 0` |
| Merge | `column.ticket_count gt 0` |

### Circuit Breaker Checks (pipeline-wide kill switch)

| Column | Constraint |
|--------|-----------|
| Epic Planning | `board.circuit_breaker_count eq "0"` |
| Decomposition | `board.circuit_breaker_count eq "0"` |
| Implementation | `board.circuit_breaker_count eq "0"` |
| Code Review | `board.circuit_breaker_count eq "0"` |
| Secondary Review | `board.circuit_breaker_count eq "0"` |
| Merge | `board.circuit_breaker_count eq "0"` |

### Downstream-Empty Constraints (serialization)

**Epic Planning** will only fire when ALL of these are empty:
- Decomposition: `column.ticket_count ref:efc66e10 eq "0"`
- Implementation: `column.ticket_count ref:ea93615c eq "0"`
- Code Review: `column.ticket_count ref:11e17c53 eq "0"`
- Secondary Review: `column.ticket_count ref:7706774e eq "0"`
- Merge: `column.ticket_count ref:a8d8c7a6 eq "0"`
- Backlog: `backlog.ticket_count eq "0"`

**Decomposition** will only fire when:
- Implementation: `column.ticket_count ref:ea93615c eq "0"`
- Code Review: `column.ticket_count ref:11e17c53 eq "0"`
- Secondary Review: `column.ticket_count ref:7706774e eq "0"`
- Merge: `column.ticket_count ref:a8d8c7a6 eq "0"`

### Active-Loop Guards (concurrency control)

| Column | Constraint | Purpose |
|--------|-----------|---------|
| Implementation | `column.active_loops ref:efc66e10 eq "0"` | Don't implement while Decomposition agent is active |
| Merge | `column.active_loops ref:self eq "0"` | Only one merge at a time |

## Signals (12 board-level `stack:*` signals)

These are architectural rules injected into every agent's context via `get_composed_signals`:

| Signal | Summary |
|--------|---------|
| `stack:rendering-boundary` | PixiJS for gameplay rendering, HTML/CSS for UI. Strict separation. |
| `stack:fixed-timestep` | All gameplay logic uses fixed dt (1/60). Never use variable frame delta. |
| `stack:zod-first-types` | Use z.infer<typeof Schema> for all game data types. No manual interfaces. |
| `stack:yaml-data-pipeline` | All game content in YAML under data/. Zod validation at load time. |
| `stack:typed-event-bus` | Systems communicate via typed event bus only. No direct cross-system calls. |
| `stack:indexeddb-saves` | Game state in IndexedDB. localStorage for settings only. |
| `stack:design-resolution` | 960x288 design resolution. All coordinates authored against this. |
| `stack:asset-2x-authoring` | Sprites at 2x resolution. 16x16 base tile size. |
| `stack:dev-only-gating` | All debug tools behind import.meta.env.DEV. |
| `stack:error-boundaries` | Fatal errors trigger emergency autosave + recovery screen. |
| `stack:test-logic-not-rendering` | Test game logic, not PixiJS rendering. Vitest. |
| `stack:hybrid-rendering` | Hybrid rendering: PixiJS canvas + HTML/CSS UI. Strict boundary. |

## Prompt Documents (6)

| Document | ID | Purpose |
|----------|----|---------| 
| Prompt: Epic Planning | `3454a36b-64c4-4cf9-beb7-fbf4c13dfc1e` | Analyze spec/codebase, propose next epic |
| Prompt: Decomposition | `90853343-07a3-44bc-9791-fed949362397` | Break epic into implementable tickets with deps |
| Prompt: Implementation | `a496a9c4-2fc9-46c4-9f10-4741a4ac8336` | Implement code, write tests, verify in browser |
| Prompt: Code Review | `18eb5370-b474-447c-9b0c-6d3972ff3b42` | Review implementation, fix issues, approve/reject |
| Prompt: Secondary Review | `b2eb7ca8-1a71-412e-bf87-d94a949e8e91` | Independent audit, approve to Merge or reject |
| Prompt: Merge | `fabd91cf-9da1-44c7-a5b3-e613247a8a62` | Merge feature branch into main with --no-ff |

## Other Documents

| Document | ID | Purpose |
|----------|----|---------| 
| Spec.md | `14355c84-0c19-413f-a007-a1176e04fbb6` | Game specification |
| GAME_STACK | `14475e2a-9b85-40ce-bbc9-4142778c10ad` | Technology stack reference |

## Tool Restrictions

Implementation and Code Review columns: **unrestricted** (all tools allowed).

## Pipeline Templates

One built-in template available: `adversarial-pipeline` (40 steps). Creates a full planner→generator→evaluator board with sprint contracts, adversarial QA, circuit breaking, firing constraints, WIP limits, and dependency gating.

---

## Architecture Patterns Worth Adopting

### 1. Single Board with Inline Epic Lifecycle
Epics are tickets that flow through Epic Planning → Decomposition (which creates child story tickets) → archive. No separate epic board.

### 2. Firing Constraints as Orchestration
24 constraints drive the entire pipeline without polling or manual intervention:
- "Minimum tickets" triggers agents when work arrives
- "Downstream empty" serializes the pipeline
- "Circuit breaker clear" is a global kill switch
- "Active loops" prevents concurrency conflicts

### 3. Every Column → Escalation
Every pipeline column has a transition rule to Escalation. Combined with the circuit breaker (2 backward transitions), this prevents infinite loops.

### 4. Signals as Architectural Context
Board-level signals inject persistent rules into every agent's context. Agents don't need to re-read docs — the rules come to them via `get_composed_signals`.

### 5. Minimal Fields
Only 2 custom fields (branch_name, epic_ref) vs our 10. The pipeline relies on transition rules, firing constraints, and agent prompts rather than field-based gates.

### 6. Handoff via Ticket Content, Not Fields
Implementation details (branch name, test results, review feedback) flow through ticket descriptions, comments, and the `handoff` parameter on `move_ticket` — not through proliferating custom fields.
