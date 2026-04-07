# Epic Progression Board — v1 Snapshot (Pre-Redesign)

**Date:** 2026-04-04
**Board ID:** `755c8950-88dc-4ea9-9e82-e51b1376cb03`
**Project ID:** `3cd3e944-44d9-4d82-9d38-701696b74ef7`

---

## Columns

| # | Name | Type | WIP | ID | Goal | Prompt Doc | Agent Config |
|---|------|------|-----|----|------|------------|--------------|
| 1 | Backlog | start | - | `13898c91-a833-4591-9a2c-7704cedeb34b` | - | - | - |
| 2 | Active | in_progress | - | `b4c6ea61-e996-4f0e-8b63-2b87e2813745` | - | - | - |
| 3 | Gate: Epic Review | default | - | `41a2bc9c-9c7f-4420-86e4-d16fb26f2b92` | Holistic epic review — evaluate coherence, interface consistency, and gap detection across all stories. | Gate: Epic Review Agent (`27dbddd1`) | `{execution_mode: "auto", model_preference: "claude-opus-4-6"}` |
| 4 | Done | done | - | `509fae35-a281-439e-b99c-8032317cc483` | - | - | - |

## Transition Rules (4)

| From | To | Instruction |
|------|----|-------------|
| Backlog | Active | Epic becomes Active when work begins on its stories. |
| Active | Gate: Epic Review | All stories for this epic must be Done before entering Epic Review gate. |
| Gate: Epic Review | Done | Epic review passed. Move to Done. Requires gate_result=pass. |
| Gate: Epic Review | Active | Epic review failed. Gap stories created. Return to Active until gaps are resolved. |

## Transition Requirements (1)

| Target Column | Required Field | Instruction |
|---------------|----------------|-------------|
| Done | `gate_result` (`22f6f101`) | gate_result must be set to pass before an epic can move to Done. |

## Firing Constraints (1, auto-created)

| Name | Column | Subject | Rule |
|------|--------|---------|------|
| Minimum tickets | Gate: Epic Review (`41a2bc9c`) | column.ticket_count | gt 0 |

## Dependency Requirements

None configured (epic-level dependency enforcement was planned but not implemented).

## Circuit Breaker

None configured.

## Epic Tickets (13)

| Ticket | Epic | Phase | ID | Status |
|--------|------|-------|----|--------|
| AP-34 | E1 - Data Models & Configuration | 1 | `c7037021-db35-48cb-b6e2-a5e1ac423cc3` | Active |
| AP-39 | E2 - Storage Layer | 1 | `78fcd57a-b393-4672-b46d-ff80880d8780` | Backlog |
| AP-33 | E3 - Structural Engine | 1 | `320f1f8b-c39e-4cf9-9d51-9438405e570a` | Backlog |
| AP-38 | E4 - MCP Server | 1 | `43a4dfc1-ef0c-455c-8914-bd096747cb5c` | Backlog |
| AP-43 | E5 - CLI & First-Run | 1 | `cafb0d1d-a724-465c-9a07-ef4d5510ff07` | Backlog |
| AP-40 | E6 - LLM Adapter Layer | 2 | `01a6054c-1e28-4fdb-8301-d82a8a77b7c0` | Backlog |
| AP-41 | E7 - Quality Assurance Pipeline | 2 | `0468714c-04b2-4f01-8d3d-da85df3e36b9` | Backlog |
| AP-45 | E8 - Knowledge Manager | 2 | `88c1e747-2744-4195-bd56-768efa191e8e` | Backlog |
| AP-36 | E9 - Priority Scoring & Metrics | 2 | `84c52e70-e3f8-48e0-9ae9-ed5011d24e75` | Backlog |
| AP-37 | E10 - Librarian Orchestrator | 2 | `f3be1264-18a1-400c-928f-9b917c52df2d` | Backlog |
| AP-44 | E11 - Human Audit UI | 2 | `ec3e6228-fe5d-4ccf-93e5-c4260558b4e4` | Backlog |
| AP-35 | E12 - Blast Radius & Impact | 3 | `ca2eafec-098c-4540-9f36-c48770e28075` | Backlog |
| AP-42 | E13 - Polish & Documentation | 4 | `861e134d-b0cc-4697-91a9-ae24c9fc99b0` | Backlog |

## Epic Dependency Graph

```
E1 → E2 → E3 → E5
       ↘ E4 ↗
E1 → E6 → E7 → E10, E11
E2 → E8 → E10, E11
E2 → E9 → E10, E11
Phase 2 complete → E12
All prior → E13
```

## Known Gaps at Snapshot Time

1. No cross-epic blocker links (stories not blocked by prerequisite epic tickets)
2. No dependency requirements on columns (planned for Gate: Epic Review but not set)
3. No mechanism to auto-move epic to Gate: Epic Review when all stories are Done
4. No mechanism to auto-move next epic to Active when current epic passes review
5. No firing constraints beyond auto-created "minimum tickets" on Gate: Epic Review
6. No circuit breaker
7. Active column has no agent config (no automated epic lifecycle management)
