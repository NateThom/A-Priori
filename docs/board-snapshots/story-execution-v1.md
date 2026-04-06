# Story Execution Board — v1 Snapshot (Pre-Redesign)

**Date:** 2026-04-04
**Board ID:** `89836111-5121-4ec5-8113-38933e6a91ed`
**Project ID:** `3cd3e944-44d9-4d82-9d38-701696b74ef7`

---

## Columns

| # | Name | Type | WIP | ID | Goal | Prompt Doc | Agent Config |
|---|------|------|-----|----|------|------------|--------------|
| 1 | Backlog | start | - | `81e37093-f97f-473c-a5ce-57b201630907` | - | - | - |
| 2 | Ready | default | - | `114f9afa-18c2-4c83-be6b-51c3a9a7e2c4` | - | - | - |
| 3 | In Progress | in_progress | 2 | `1d3de569-426b-4d87-8eb6-cd9d10a70032` | Implement the story using TDD. Write tests first, then code to pass them. Create a PR when done. | Implementation Agent (`306ac373`) | `{execution_mode: "auto", model_preference: "claude-sonnet-4-6"}` |
| 4 | In Progress — Escalated | in_progress | 1 | `22989491-c373-4c19-b094-754c0e8a7dbf` | Escalated implementation — story failed gate 3+ times. Use Opus to resolve persistent issues. | Implementation Agent (`306ac373`) | `{execution_mode: "auto", model_preference: "claude-opus-4-6"}` |
| 5 | Gate: Quality | default | - | `c6d5ba54-474f-4bf4-806b-48846f3326c9` | Evaluate the implementation against acceptance criteria. CI must pass first, then LLM judge reviews. | Gate: Quality Agent (`4f126c2b`) | `{execution_mode: "auto", model_preference: "claude-sonnet-4-6"}` |
| 6 | Done | done | - | `c04b485b-6f94-4133-964d-4eee96abea9f` | - | - | - |

## Transition Rules (7)

| From | To | Instruction |
|------|----|-------------|
| Backlog | Ready | Stories move from Backlog to Ready when all dependency stories are Done. |
| Ready | In Progress | Pick up a Ready story for implementation by the Sonnet 4.6 agent. |
| In Progress | Gate: Quality | Implementation complete. Ensure tests_written=true and pr_created=true before moving to gate. |
| In Progress — Escalated | Gate: Quality | Escalated implementation complete. Ensure tests_written=true and pr_created=true before moving to gate. |
| Gate: Quality | In Progress | Gate failed (count < 3). Return to In Progress for Sonnet 4.6 to rework. |
| Gate: Quality | In Progress — Escalated | Gate failed 3+ times. Escalate to Opus 4.6 via In Progress — Escalated. |
| Gate: Quality | Done | Gate passed. Move to Done. Requires gate_result=pass. |

## Transition Requirements (3)

| Target Column | Required Field | Instruction |
|---------------|----------------|-------------|
| Gate: Quality | `tests_written` (`9d2aec43`) | Set tests_written=true before moving to Gate: Quality. For spikes, set decision_documented=true instead. |
| Gate: Quality | `pr_created` (`c219292b`) | Set pr_created=true before moving to Gate: Quality. |
| Done | `gate_result` (`22f6f101`) | gate_result must be set to pass before a ticket can move to Done. |

## Dependency Requirements (1)

| Target Column | Policy | Instruction |
|---------------|--------|-------------|
| Ready (`114f9afa`) | column_or_archived (Done column) | Story cannot enter Ready until all blocking stories are in Done or archived. |

## Firing Constraints (3, auto-created)

| Name | Column | Subject | Rule |
|------|--------|---------|------|
| Minimum tickets | In Progress (`1d3de569`) | column.ticket_count | gt 0 |
| Minimum tickets | In Progress — Escalated (`22989491`) | column.ticket_count | gt 0 |
| Minimum tickets | Gate: Quality (`c6d5ba54`) | column.ticket_count | gt 0 |

## Circuit Breaker

None configured.

## Custom Fields (10)

| Name | Type | ID |
|------|------|----|
| story_type | single_select (implementation/spike) | `c122078e-f556-4f65-8b05-e82759339bdb` |
| epic | short_text | `a6674a44-7f02-450f-80b2-ea85f103e201` |
| phase | single_select (1/2/3/4) | `028a08f1-8f09-4a04-a026-eea6375d0ccc` |
| gate_result | single_select (pass/fail) | `22f6f101-f3da-4d49-8745-0184bb76e641` |
| gate_reasoning | long_text | `9649fcd5-06af-4901-895e-d17661a02896` |
| failing_criteria | long_text | `4a9559e8-798b-42a0-8cb3-ecac24d1bb04` |
| gate_fail_count | number | `913a7322-97a0-46c9-a48d-b54f5517c9f3` |
| tests_written | checkbox | `9d2aec43-6b8e-4e17-98c1-5e7cb2ba7aa3` |
| pr_created | checkbox | `c219292b-2b8b-4a39-b2a7-159bbf3c1562` |
| decision_documented | checkbox | `c83ec959-885e-4449-91a4-69e975aeb613` |

## Select Option IDs

**phase:** 1=`b0000001-0001-0001-0001-000000000001`, 2=`..02`, 3=`..03`, 4=`..04`
**story_type:** implementation=`c0000001-0001-0001-0001-000000000001`, spike=`c0000001-0001-0001-0001-000000000002`
**gate_result:** pass=`d0000001-0001-0001-0001-000000000001`, fail=`d0000001-0001-0001-0001-000000000002`

## Prompt Documents

| Document | KantBan ID | Local Path |
|----------|------------|------------|
| Implementation Agent | `306ac373-e653-47f3-9be2-78fe1c785266` | `docs/agent-prompts/implementation-agent.md` |
| Gate: Quality Agent | `4f126c2b-2b26-4c9f-a2ae-b802e15d6c3c` | `docs/agent-prompts/gate-quality-agent.md` |
| Gate: Epic Review Agent | `27dbddd1-80df-4e6f-8229-9e8edd30808c` | `docs/agent-prompts/gate-epic-review-agent.md` |

## Pipeline Templates (3)

| Name | ID |
|------|----|
| unblock-check | `1b062fd0-3cb2-4ec8-ab47-b140c073f0ef` |
| epic-complete-check | `7d7c1633-0068-407e-8496-86edda543104` |
| gap-story | `a7024b09-e33a-4b5c-ae36-c65357d4ac1c` |

## Ticket Summary

- **Total:** 64 story tickets
- **Backlog:** 61
- **Ready:** 3 (Stories 1.1, 1.4, 1.5)
- **65 intra-epic dependency links** created

## Known Gaps at Snapshot Time

1. No firing constraints beyond auto-created "minimum tickets"
2. No circuit breaker or escalation column
3. No cross-epic blocker links (E2 stories not blocked by E1 epic)
4. No signals for architectural rules
5. No tool restrictions per column
6. No handoff data pattern between stages
7. Ready → In Progress dispatch not automated
8. Epic completion check not automated
