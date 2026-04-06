# Epic Progression Board — v2 Snapshot (Pipeline Redesign)

**Date:** 2026-04-05
**Board ID:** `755c8950-88dc-4ea9-9e82-e51b1376cb03`
**Project ID:** `3cd3e944-44d9-4d82-9d38-701696b74ef7`

---

## Columns

| # | Name | Type | WIP | ID | Goal | Prompt Doc | Agent Config |
|---|------|------|-----|----|------|------------|--------------|
| 1 | Backlog | start | - | `13898c91` | - | - | - |
| 2 | Active | in_progress | - | `b4c6ea61` | - | - | Status column (no agent) |
| 3 | Gate: Integration | default | - | `41a2bc9c` | Evaluate integration quality across all stories in the epic. | Gate: Integration Agent (`27dbddd1`) | `{execution_mode: "auto", model_preference: "claude-opus-4-6"}` |
| 4 | Gate: Architecture | default | - | `e061a9a2` | Evaluate architectural consistency against project signals. | Gate: Architecture Agent (`e8812813`) | `{execution_mode: "auto", model_preference: "claude-opus-4-6"}` |
| 5 | Done | done | - | `509fae35` | - | - | - |
| 6 | Escalation | default | - | `8c50f695` | - | - | Human intervention required |

## Transition Rules (8)

| From | To | Instruction |
|------|----|-------------|
| Backlog | Active | Epic becomes Active when work begins on its stories. |
| Active | Gate: Integration | All stories for this epic are Done. Begin integration review. |
| Gate: Integration | Gate: Architecture | Integration review passed. Proceed to architecture review. |
| Gate: Integration | Active | Integration review failed. Gap stories created. Return to Active. |
| Gate: Integration | Escalation | Error during integration review. Escalate for human intervention. |
| Gate: Architecture | Done | Architecture review passed. Epic is complete. |
| Gate: Architecture | Active | Architecture review failed. Gap stories created. Return to Active. |
| Gate: Architecture | Escalation | Error during architecture review. Escalate for human intervention. |

## Transition Requirements (1)

| Target Column | Required Field | Instruction |
|---------------|----------------|-------------|
| Done | `gate_result` (`22f6f101`) | gate_result must be set to pass before an epic can move to Done. |

## Circuit Breaker

| Setting | Value |
|---------|-------|
| Threshold | 2 backward transitions |
| Target column | Escalation (`8c50f695`) |

## Firing Constraints (5)

| Name | Column | Subject | Rule |
|------|--------|---------|------|
| Minimum tickets | Gate: Integration (`41a2bc9c`) | column.ticket_count | gt 0 |
| Minimum tickets | Gate: Architecture (`e061a9a2`) | column.ticket_count | gt 0 |
| circuit-breaker | Gate: Integration (`41a2bc9c`) | board.circuit_breaker_count | eq "0" |
| circuit-breaker | Gate: Architecture (`e061a9a2`) | board.circuit_breaker_count | eq "0" |
| serialized-review | Gate: Integration (`41a2bc9c`) | column.ticket_count ref:Gate:Architecture | eq "0" |

## Prompt Documents

| Document | KantBan ID |
|----------|------------|
| Gate: Integration Agent | `27dbddd1` |
| Gate: Architecture Agent | `e8812813` |

## Epic Tickets (13)

| Ticket | Epic | ID | Status |
|--------|------|----|--------|
| AP-34 | E1 - Data Models & Configuration | `c7037021` | Active |
| AP-39 | E2 - Storage Layer | `78fcd57a` | Backlog |
| AP-33 | E3 - Structural Engine | `320f1f8b` | Backlog |
| AP-38 | E4 - MCP Server | `43a4dfc1` | Backlog |
| AP-43 | E5 - CLI & First-Run | `cafb0d1d` | Backlog |
| AP-40 | E6 - LLM Adapter Layer | `01a6054c` | Backlog |
| AP-41 | E7 - Quality Assurance Pipeline | `0468714c` | Backlog |
| AP-45 | E8 - Knowledge Manager | `88c1e747` | Backlog |
| AP-36 | E9 - Priority Scoring & Metrics | `84c52e70` | Backlog |
| AP-37 | E10 - Librarian Orchestrator | `f3be1264` | Backlog |
| AP-44 | E11 - Human Audit UI | `ec3e6228` | Backlog |
| AP-35 | E12 - Blast Radius & Impact | `ca2eafec` | Backlog |
| AP-42 | E13 - Polish & Documentation | `861e134d` | Backlog |

## Cross-Epic Dependency Graph

```
E1 ──→ E2 ──→ E3 ──→ E5
        │      │      ↑
        ├──→ E4 ──────┘
        ├──→ E8 ──→ E10 ──→ E12
        ├──→ E9 ──→ E11 ──→ E12
        │          ↗  ↑       │
E1 ──→ E6 ──→ E7 ┘   │       │
              │───→ E10       ↓
              │───→ E11    E12 ──→ E13
                              ↑
E5 ────────────────────────→ E13
```

**Minimal links (transitive coverage):**

| Epic | Blocked By |
|------|------------|
| E2 | E1 |
| E3 | E2 |
| E4 | E2 |
| E5 | E3, E4 |
| E6 | E1 |
| E7 | E6, E2 |
| E8 | E2 |
| E9 | E2 |
| E10 | E6, E7, E8, E9 |
| E11 | E7, E8, E9 |
| E12 | E10, E11 |
| E13 | E5, E12 |

## Project-Level Signals (14)

| Signal |
|--------|
| `arch:layer-flow` |
| `arch:quality-invariant` |
| `arch:protocol-first` |
| `arch:pydantic-models` |
| `arch:sqlite-vec-storage` |
| `arch:tree-sitter-only` |
| `arch:mcp-thin-shell` |
| `arch:librarian-loop` |
| `arch:test-mirrors-src` |
| `arch:adapter-pattern` |
| `arch:sync-first` |
| `arch:embedding-model` |
| `arch:core-lib-thin-shells` |
| `arch:no-raw-sql` |

## Changes from v1

1. Split single "Gate: Epic Review" column into two sequential gates: Gate: Integration and Gate: Architecture
2. Added Escalation column for human intervention on persistent errors
3. Added circuit breaker (threshold: 2 backward transitions) targeting Escalation column
4. Added circuit-breaker firing constraints on both gate columns
5. Added serialized-review constraint ensuring only one epic reviews at a time across gates
6. Added Gate: Architecture prompt document (`e8812813`)
7. Added 14 project-level architectural signals
8. Added explicit cross-epic dependency links with minimal transitive coverage
