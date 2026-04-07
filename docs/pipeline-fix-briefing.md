# Pipeline Fix Briefing — Ultraplan Context

This document provides full context for planning fixes to the A-Priori KantBan autonomous pipeline. These are NOT code changes to the A-Priori Python project — they are updates to agent prompt documents (both local files and synced KantBan documents) and pipeline configuration.

---

## System Overview

A-Priori uses a two-board KantBan autonomous pipeline where AI agents process tickets through columns:

### Story Execution Board (`89836111-5121-4ec5-8113-38933e6a91ed`)
7 columns: Backlog → Ready (Haiku dispatcher) → Implementation (Sonnet) → Code Review (Sonnet) → Merge (Sonnet) → Done + Escalation (Opus)

Each pipeline column has a **prompt document** stored as a KantBan document that tells the agent what to do. These prompts are also maintained as local files in `docs/agent-prompts/`.

### Epic Progression Board (`755c8950-88dc-4ea9-9e82-e51b1376cb03`)
6 columns: Backlog → Active → Gate: Integration (Opus) → Gate: Architecture (Opus) → Done + Escalation

### How They Connect
- Stories belong to epics via an `epic` field
- When ALL stories for an epic are Done, the merge agent moves the epic from Active → Gate: Integration
- Gate: Integration reviews cross-story coherence, then passes to Gate: Architecture
- Gate: Architecture reviews architectural compliance, then moves epic to Done and activates the next eligible epic from Backlog

### Pipeline Templates
Templates are reusable multi-step automations. They are referenced by UUID:
- `story-complete-check` (`81278e02`): Story Done — check if epic ready for review
- `epic-complete-unblock` (`0ec87913`): Epic Done — unblock downstream stories
- `gap-story-creator` (`69b04d08`): Create gap stories on epic review failure

**Known Problem:** `kantban_run_pipeline_template` requires the full UUID, but `kantban_list_pipeline_templates` doesn't reliably return IDs. This causes agents that call `run_pipeline_template` by name to fail silently.

---

## Current Board State (Live as of 2026-04-06)

### Story Board
- **Backlog:** 59 tickets (E2-E13 stories)
- **Ready:** 1 ticket (AP-110 Dispatcher Sentinel — permanent, never moves)
- **Implementation/Code Review/Merge:** 0 tickets
- **Done:** 5 tickets (AP-46 through AP-50, all E1 stories)
- **Escalation:** 0 tickets

### Epic Board
- **Backlog:** 11 epics (E2-E13, including AP-39 E2 which was manually moved back from Active)
- **Active:** 0 epics
- **Gate: Integration:** 0 epics
- **Gate: Architecture:** 1 epic (AP-34 E1 — awaiting architecture review)
- **Done:** 0 epics
- **Escalation:** 0 epics

### No pipelines are currently running.

---

## Entity ID Reference

### Project
- Project: `3cd3e944-44d9-4d82-9d38-701696b74ef7`

### Story Board Columns
| Column | Short ID | Full UUID |
|--------|----------|-----------|
| Backlog | `81e37093` | `81e37093-f97f-473c-a5ce-57b201630907` |
| Ready | `114f9afa` | `114f9afa-18c2-4c83-be6b-51c3a9a7e2c4` |
| Implementation | `1d3de569` | `1d3de569-426b-4d87-8eb6-cd9d10a70032` |
| Code Review | `c6d5ba54` | `c6d5ba54-474f-4bf4-806b-48846f3326c9` |
| Merge | `985d6122` | `985d6122-7c77-4edd-8ec0-af41a1f20db6` |
| Done | `c04b485b` | `c04b485b-6f94-4133-964d-4eee96abea9f` |
| Escalation | `e7ea5182` | `e7ea5182-0176-4d28-94e4-3ad5683a7e6c` |

### Epic Board Columns
| Column | Short ID | Full UUID |
|--------|----------|-----------|
| Backlog | `13898c91` | `13898c91-a833-4591-9a2c-7704cedeb34b` |
| Active | `b4c6ea61` | `b4c6ea61-e996-4f0e-8b63-2b87e2813745` |
| Gate: Integration | `41a2bc9c` | `41a2bc9c-9c7f-4420-86e4-d16fb26f2b92` |
| Gate: Architecture | `e061a9a2` | `e061a9a2-b8bf-4f78-88eb-c2854e12a1c3` |
| Done | `509fae35` | `509fae35-a281-439e-b99c-8032317cc483` |
| Escalation | `8c50f695` | `8c50f695-be64-41b9-a3ff-8ae1ed5f0cef` |

### Custom Fields
| Field | ID |
|-------|----|
| branch_name | `b081b013` |
| epic | `a6674a44` |
| story_type | `c122078e` |
| gate_result | `22f6f101` |

### Prompt Documents (KantBan Document IDs)
| Agent | Document ID | Local File |
|-------|-------------|------------|
| Dispatcher | `530d9834-2e8f-4624-be09-2c3459ff1610` | `docs/agent-prompts/dispatcher-agent.md` |
| Implementation | `306ac373` | `docs/agent-prompts/implementation-agent.md` |
| Code Review | `4f126c2b` | `docs/agent-prompts/code-review-agent.md` |
| Merge | `2cddaff5-468e-4e8b-91fc-7cd7bac1e67c` | `docs/agent-prompts/merge-agent.md` |
| Escalation Recovery | `187f1434` | `docs/agent-prompts/escalation-recovery-agent.md` |
| Gate: Integration | `27dbddd1` | `docs/agent-prompts/gate-integration-agent.md` |
| Gate: Architecture | `e8812813-c856-400b-b385-7030071cc320` | `docs/agent-prompts/gate-architecture-agent.md` |

### Pipeline Templates
| Template | ID |
|----------|----|
| story-complete-check | `81278e02` |
| epic-complete-unblock | `0ec87913` |
| gap-story-creator | `69b04d08` |

### Key Tickets
| Ticket | ID |
|--------|----|
| AP-110 Dispatcher Sentinel | `074a41a7-ff19-42e1-af5a-4a69f6910293` |
| AP-34 E1 | `c7037021-db35-48cb-b6e2-a5e1ac423cc3` |
| AP-39 E2 | `78fcd57a-b393-4672-b46d-ff80880d8780` |

---

## Issues to Resolve

### Issue 1: Dispatcher Epic Board Guardrail

**Problem:** The dispatcher agent (runs on Story Board Ready column) moved an epic ticket on the Epic Board. It should ONLY operate on the Story Board.

**File:** `docs/agent-prompts/dispatcher-agent.md`
**KantBan Doc:** `530d9834-2e8f-4624-be09-2c3459ff1610`

**Fix:** Add this rule to the Rules section of the dispatcher prompt:
```
- **NEVER move tickets on the Epic Board — you only operate on the Story Board.** You may READ the Epic Board to check which epics are Active, but you must not move, create, or modify any tickets on it.
```

**Sync:** After updating the local file, sync content to KantBan document `530d9834-2e8f-4624-be09-2c3459ff1610` using `kantban_update_document`.

### Issue 2: Gap-Story-Creator Template UUID Problem

**Problem:** Gate agent prompts reference a `gap-story-creator` pipeline template by name in their FAIL paths. But `run_pipeline_template` requires a UUID, and agents can't reliably discover UUIDs from names. This will cause silent failures if a gate review fails.

**Affected files:**
- `docs/agent-prompts/gate-integration-agent.md` (FAIL path, Step 3)
- `docs/agent-prompts/gate-architecture-agent.md` (FAIL path, Step 3)

**Current broken pattern in gate-integration-agent.md:**
```markdown
- For each gap or coherence issue:
  - Trigger the `gap-story-creator` pipeline template with:
    - `epic_id`: this epic's ticket ID
    - `gap_title`: "[Gap] {Epic Name}: {specific issue}"
    - `gap_description`: detailed description of what's missing
    - `gap_ac`: Given/When/Then acceptance criteria
    - `source_gate`: "integration"
```

**Fix:** Replace template invocation with inline logic using direct KantBan tool calls. The gap-story-creator template's job is simple: create a new story ticket in the Story Board Backlog with the gap details and link it to the epic. The inline replacement should:
1. Create a ticket on Story Board (`89836111-5121-4ec5-8113-38933e6a91ed`) with `columnId: null` (backlog)
2. Set the title to the gap_title
3. Set the description to include gap_description and gap_ac
4. Set the `epic` field to match this epic's value
5. Set `story_type` field to "gap"
6. Create a blocker link from the gap story to the epic (so the epic can't re-enter review until gap is resolved)

**Same fix needed for gate-architecture-agent.md** FAIL path which has similar template references.

**KantBan Docs to sync:**
- Gate: Integration → `27dbddd1`
- Gate: Architecture → `e8812813-c856-400b-b385-7030071cc320`

### Issue 3: Circuit Breaker Counter Reset

**Problem:** The Epic Board's circuit breaker backward-transition counter is at 1 (from when E2 was manually moved back to Backlog). The threshold is 2. If a gate review fails and moves an epic backward, the counter will hit 2 and the circuit breaker will fire, sending all tickets to Escalation.

**Fix:** This is a MANUAL action — the user must reset the counter in the KantBan web UI. There is no API endpoint for this. The plan should just remind the user to do this before restarting pipelines.

### Issue 4: Pipeline Restart and Verification

**After fixes 1-3, restart both pipelines:**
```bash
kantban pipeline 89836111-5121-4ec5-8113-38933e6a91ed -y  # Story Board
kantban pipeline 755c8950-88dc-4ea9-9e82-e51b1376cb03 -y  # Epic Board
```

**Expected behavior after restart:**
1. Epic Board pipeline: Gate: Architecture agent processes E1 (AP-34)
   - If PASS: E1 moves to Done, next eligible epic (E2 and E6, both blocked only by E1) moves to Active
   - If FAIL: Gap stories created inline (not via template), E1 moves back to Active
2. Story Board pipeline: Dispatcher promotes unblocked E2/E6 stories from Backlog to Ready when their epic is Active
3. Dispatcher does NOT touch Epic Board tickets

**Verification checklist:**
- [ ] E1 completes Gate: Architecture review
- [ ] If E1 passes, next epic(s) activated correctly
- [ ] Dispatcher only moves Story Board tickets
- [ ] No template UUID errors in agent logs
- [ ] Circuit breaker counter remains stable

---

## Previously Resolved Issues (for context)

These were already fixed in prior sessions — do NOT re-fix:

1. **Dispatcher comment spam** — Fixed: added "NEVER create comments" rule + tool restriction
2. **Rogue signal creation** — Fixed: `kantban_create_signal`/`update`/`delete` added to disallowed tools on all pipeline columns
3. **Merge agent epic advancement** — Fixed: replaced `run_pipeline_template` with inline logic using hardcoded IDs in merge-agent.md
4. **Gate: Architecture PASS path epic activation** — Fixed: replaced `run_pipeline_template` with inline logic in gate-architecture-agent.md

---

## How to Update Agent Prompts

Each agent prompt exists in TWO places that must stay in sync:
1. **Local file:** `docs/agent-prompts/{agent-name}.md` — edit with standard file tools
2. **KantBan document:** identified by document ID — sync with `kantban_update_document`

When updating, ALWAYS update both. The pipeline reads from the KantBan document, not the local file. The local file is the source of truth for version control.

---

## Cross-Epic Dependency Graph

```
E1 --> E2 --> E3 --> E5
        |      |      ^
        +--> E4 ------+
        +--> E8 --> E10 --> E12
        +--> E9 --> E11 --> E12
        |          /  ^       |
E1 --> E6 --> E7 -+   |       |
              |---> E10       v
              |---> E11    E12 --> E13
                              ^
E5 ------------------------> E13
```

After E1 completes (Done), the following epics become eligible for Active:
- **E2** (blocked only by E1)
- **E6** (blocked only by E1)

---

## Gap-Story-Creator Template Steps (What Inline Logic Must Replicate)

The `gap-story-creator` template performs these 4 steps. The inline replacement in gate prompts must do the same thing using direct tool calls:

1. **Create gap story ticket** — `kantban_create_ticket` on Story Board (`89836111-5121-4ec5-8113-38933e6a91ed`) with `columnId: null` (backlog). Title = gap_title, description = gap_description + gap_ac.
2. **Set story fields** — `kantban_set_field_value` to set `story_type` (field `c122078e`) to `"implementation"` and `epic` (field `a6674a44`) to match this epic's value on the new ticket.
3. **Create blocker link** — `kantban_create_ticket_link` with type `"blocks"` — the gap story blocks the epic ticket so the epic cannot re-enter review until the gap story is Done.
4. **Add comment** — `kantban_create_comment` on the epic ticket linking back to the reviewer's finding.

### Template Parameters Reference
```
epic_id: string       — Epic ticket ID (full UUID)
gap_title: string     — Title for the gap story
gap_description: string — Full description including AC
gap_ac: string        — Given/When/Then acceptance criteria
source_gate: string   — "integration" or "architecture"
```

---

## Current Tool Restrictions (Already Configured)

### Story Board
| Column | Disallowed Tools |
|--------|-----------------|
| Ready (Dispatcher) | `kantban_create_signal`, `kantban_update_signal`, `kantban_promote_signal`, `kantban_create_comment`, `kantban_create_comments` |
| Code Review | `Edit`, `Write`, `NotebookEdit`, `kantban_create_signal`, `kantban_update_signal`, `kantban_promote_signal` |
| Merge | `Edit`, `Write`, `NotebookEdit`, `kantban_create_signal`, `kantban_update_signal`, `kantban_promote_signal` |

### Epic Board
| Column | Disallowed Tools |
|--------|-----------------|
| Gate: Integration | `kantban_create_signal`, `kantban_update_signal`, `kantban_promote_signal` |
| Gate: Architecture | `kantban_create_signal`, `kantban_update_signal`, `kantban_promote_signal` |

---

## Reference Pattern: Merge Agent Inline Epic Check (Already Implemented)

This is the pattern that was already applied to fix the merge agent. Use this same approach for the gate FAIL paths.

From `docs/agent-prompts/merge-agent.md`, Step 4:

```markdown
### Step 4: Cleanup & Epic Check

1. Delete the feature branch (local and remote)
2. Set `gate_result = pass` on the ticket
3. Add a comment: "Merged to main via {merge_commit_sha}. Branch cleaned up."
4. Move ticket to Done (`kantban_complete_task` with `moveToColumn` targeting Done column `c04b485b`)
5. **Epic completion check — do this inline, do NOT call `run_pipeline_template`:**
   a. Read this story's `epic` field value (field ID: `a6674a44`)
   b. Search all story tickets with that same epic value on Story Board (`89836111-5121-4ec5-8113-38933e6a91ed`)
   c. If **ALL** matching stories are in the Done column (`c04b485b`), move the epic ticket from Active (`b4c6ea61`) to Gate: Integration (`41a2bc9c`) on Epic Board (`755c8950-88dc-4ea9-9e82-e51b1376cb03`)
   d. If any story is NOT in Done, do nothing — exit cleanly
```

**Key principles of this pattern:**
- Hardcode structural IDs (board, column UUIDs) directly in the prompt
- Use direct KantBan tool calls instead of `run_pipeline_template`
- Include clear conditional logic (if/else) so the agent knows when to act vs. exit
- Reference field IDs for lookups

---

## Reference Pattern: Gate Architecture PASS Path (Already Implemented)

From `docs/agent-prompts/gate-architecture-agent.md`, PASS decision:

```markdown
- Move epic ticket to Done (`509fae35`)
- **Activate next epic — do this inline, do NOT call `run_pipeline_template`:**
  a. List all epics in Backlog (`13898c91`) on Epic Board (`755c8950-88dc-4ea9-9e82-e51b1376cb03`)
  b. For each, check its dependency links (`kantban_get_ticket_context`)
  c. If ALL dependencies are resolved (blocking epics are in Done column `509fae35`), the epic is eligible
  d. Move the first eligible epic from Backlog to Active (`b4c6ea61`)
  e. If no epic is eligible, do nothing — exit cleanly
```

---

## Files That Need Modification

### 1. `docs/agent-prompts/dispatcher-agent.md` (Issue 1)
**Current Rules section (lines 37-42):**
```markdown
## Rules

- **NEVER move the Dispatcher Sentinel ticket.** It must remain in Ready permanently.
- **NEVER promote a story whose epic is not in the Active column.** Check the Epic Progression board first. If unsure, skip the ticket.
- **NEVER force-move a blocked ticket.** If a ticket has unresolved blockers, skip it entirely. Do not override, bypass, or ignore dependency links under any circumstances.
- **NEVER create comments on any ticket.** Do not leave status updates, progress reports, or notes. Your only outputs are ticket moves and field updates.
- Never implement anything yourself — you only dispatch
- If no stories are eligible for promotion or dispatch, **exit immediately** — do not iterate further, do not write comments, do not explain why
- Keep branch names short and descriptive (max 50 chars for the slug portion)
```
**Change needed:** Add the Epic Board guardrail rule.

### 2. `docs/agent-prompts/gate-integration-agent.md` (Issue 2)
**Current FAIL path (lines 57-66):**
```markdown
**FAIL** — coherence issues or gaps found:
- Write a detailed ticket comment documenting each finding
- For each gap or coherence issue:
  - Trigger the `gap-story-creator` pipeline template with:
    - `epic_id`: this epic's ticket ID
    - `gap_title`: "[Gap] {Epic Name}: {specific issue}"
    - `gap_description`: detailed description of what's missing
    - `gap_ac`: Given/When/Then acceptance criteria
    - `source_gate`: "integration"
- Move epic ticket back to Active
- The gap stories will block the epic from re-entering review until resolved
```
**Change needed:** Replace template invocation with inline gap-story creation logic.

### 3. `docs/agent-prompts/gate-architecture-agent.md` (Issue 2)
**Current FAIL path (lines 76-86):**
```markdown
**FAIL** — architecture issues found:
- Write a detailed ticket comment documenting each finding
- For each architecture issue:
  - Trigger `gap-story-creator` with:
    - `epic_id`: this epic's ticket ID
    - `gap_title`: "[Arch] {Epic Name}: {specific issue}"
    - `gap_description`: what needs to change and why
    - `gap_ac`: Given/When/Then for the fix
    - `source_gate`: "architecture"
- Move epic ticket back to Active
```
**Change needed:** Replace template invocation with inline gap-story creation logic.
