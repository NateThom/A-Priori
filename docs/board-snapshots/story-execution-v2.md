# Story Execution Board — v2 Snapshot (Pipeline Redesign)

**Date:** 2026-04-05
**Board ID:** `89836111-5121-4ec5-8113-38933e6a91ed`
**Project ID:** `3cd3e944-44d9-4d82-9d38-701696b74ef7`

---

## Columns

| # | Name | Type | WIP | ID | Goal | Prompt Doc | Agent Config |
|---|------|------|-----|----|------|------------|--------------|
| 1 | Backlog | start | - | `81e37093` | - | - | - |
| 2 | Ready | default | - | `114f9afa` | Dispatch stories to Implementation when unblocked. | Dispatcher Agent (`530d9834`) | `{execution_mode: "auto", model_preference: "claude-haiku"}` |
| 3 | Implementation | in_progress | 1 | `1d3de569` | Implement the story using TDD. Write tests first, then code to pass them. Create a PR when done. | Implementation Agent (`306ac373`) | `{execution_mode: "auto", model_preference: "claude-sonnet-4-6"}` |
| 4 | Code Review | in_progress | 1 | `c6d5ba54` | Review the PR for correctness, style, and adherence to architectural signals. | Code Review Agent (`4f126c2b`) | `{execution_mode: "auto", model_preference: "claude-sonnet-4-6"}` |
| 5 | Merge | in_progress | 1 | `985d6122` | Merge the approved PR into main. | Merge Agent (`2cddaff5`) | `{execution_mode: "auto", model_preference: "claude-sonnet-4-6"}` |
| 6 | Done | done | - | `c04b485b` | - | - | - |
| 7 | Escalation | default | - | `e7ea5182` | Resolve stuck or failing stories using Opus-level reasoning. | Escalation Recovery Agent (`187f1434`) | `{execution_mode: "auto", model_preference: "claude-opus-4-6", max_iterations: 3}` |

## Transition Rules (10)

| From | To | Instruction |
|------|----|-------------|
| Backlog | Ready | Story unblocked — all dependency stories are Done or archived. |
| Ready | Implementation | Dispatcher moves story to Implementation for pickup. |
| Implementation | Code Review | PR created and tests green. Ready for review. |
| Implementation | Escalation | Stuck after max iterations. Escalate for Opus resolution. |
| Code Review | Merge | PR approved. Proceed to merge. |
| Code Review | Implementation | PR rejected — rework needed. Return to Implementation. |
| Code Review | Escalation | Error or repeated failures during review. |
| Merge | Done | Successfully merged into main. |
| Merge | Escalation | Merge failed. Escalate for resolution. |
| Escalation | Code Review | Opus resolved the issue. Return to Code Review. |

## Transition Requirements (2)

| Target Column | Required Field | Instruction |
|---------------|----------------|-------------|
| Code Review | `branch_name` (`b081b013`) | branch_name must be set before moving to Code Review. |
| Done | `gate_result` (`22f6f101`) | gate_result must be set to pass before a ticket can move to Done. |

## Dependency Requirements (1)

| Target Column | Policy | Instruction |
|---------------|--------|-------------|
| Ready (`114f9afa`) | column_or_archived (Done column) | Story cannot enter Ready until all blocking stories are in Done or archived. |

## Firing Constraints (6)

| Name | Column | Subject | Rule |
|------|--------|---------|------|
| Minimum tickets | Ready (`114f9afa`) | column.ticket_count | gt 0 |
| Minimum tickets | Implementation (`1d3de569`) | column.ticket_count | gt 0 |
| Minimum tickets | Code Review (`c6d5ba54`) | column.ticket_count | gt 0 |
| Minimum tickets | Merge (`985d6122`) | column.ticket_count | gt 0 |
| Minimum tickets | Escalation (`e7ea5182`) | column.ticket_count | gt 0 |
| one-at-a-time | Merge (`985d6122`) | column.active_loops ref:self | eq "0" |

## Circuit Breaker

None configured at board level. Per-ticket escalation is handled via loop checkpoints on individual columns.

## Custom Fields (4 used)

| Name | Type | ID |
|------|------|----|
| branch_name | short_text | `b081b013` |
| epic | short_text | `a6674a44` |
| story_type | single_select | `c122078e` |
| gate_result | single_select | `22f6f101` |

## Tool Restrictions

| Column | Disallowed Tools |
|--------|-----------------|
| Code Review (`c6d5ba54`) | Edit, Write, NotebookEdit |
| Merge (`985d6122`) | Edit, Write, NotebookEdit |

## Prompt Documents

| Document | KantBan ID |
|----------|------------|
| Dispatcher Agent | `530d9834` |
| Implementation Agent | `306ac373` |
| Code Review Agent | `4f126c2b` |
| Merge Agent | `2cddaff5` |
| Escalation Recovery Agent | `187f1434` |

## Pipeline Templates (3)

| Name | ID | Trigger |
|------|----|---------|
| story-complete-check | `81278e02` | Story Done — check if epic ready for review |
| epic-complete-unblock | `0ec87913` | Epic Done — unblock downstream stories |
| gap-story-creator | `69b04d08` | Create gap stories on epic review failure |

## Ticket Summary

- **Total:** 64 story tickets
- **Backlog:** 61
- **Ready:** 3
- **Dependency links:** 65 intra-epic + 103 cross-epic

## Changes from v1

1. Replaced single "In Progress" column with separate Implementation, Code Review, and Merge columns
2. Removed "In Progress -- Escalated" column; added dedicated Escalation column with Opus 4.6
3. Added Dispatcher Agent (Haiku) on Ready column to automate story dispatch
4. Added tool restrictions on Code Review and Merge (no Edit, Write, NotebookEdit)
5. Added branch_name transition requirement for Code Review
6. WIP limit reduced from 2 to 1 on all in_progress columns
7. Added one-at-a-time firing constraint on Merge column
8. Added 103 cross-epic dependency links (previously missing)
9. Added 3 pipeline templates for story/epic lifecycle automation
10. Escalation uses loop checkpoints (max 3 iterations) instead of gate_fail_count
