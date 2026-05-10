# SepsisGuard — Development Phases

This is the master plan for building SepsisGuard from the spec (`SEPSISGUARD_BUILD_SPEC.md`). Work is split into **8 active phases** + Phase 0 (already done). Each phase has a self-contained handoff document in `docs/phases/`. A teammate can pick up any phase by reading its doc plus the spec sections it cites — no other onboarding needed.

> **Source of truth:** `SEPSISGUARD_BUILD_SPEC.md`. Phase docs cite specific sections — always read the spec section, don't paraphrase from the phase doc.
> **Agent guidance:** `CLAUDE.md` lists the gotchas that have already burned the spec author (e.g. omit `temperature`, strip stale `cache_control`, FastAPI `request: Request` pitfall).

---

## Phase map

| # | Phase | Doc | Blocks | Blocked by | Effort |
|---|---|---|---|---|---|
| 0 | Scaffold | — (DONE) | 1, 2 | — | ✅ |
| 1 | Shared Infrastructure | [PHASE_01_INFRASTRUCTURE.md](docs/phases/PHASE_01_INFRASTRUCTURE.md) | 3, 4, 5 | 0 | M |
| 2 | Domain Layer | [PHASE_02_DOMAIN.md](docs/phases/PHASE_02_DOMAIN.md) | 3, 4 | 0 | M |
| 3 | Deterministic Tools | [PHASE_03_DETERMINISTIC_TOOLS.md](docs/phases/PHASE_03_DETERMINISTIC_TOOLS.md) | 5 | 1, 2 | M |
| 4 | Claude-Backed Tools | [PHASE_04_CLAUDE_TOOLS.md](docs/phases/PHASE_04_CLAUDE_TOOLS.md) | 5 | 1, 2 | M |
| 5 | Orchestration & Transport | [PHASE_05_ORCHESTRATION.md](docs/phases/PHASE_05_ORCHESTRATION.md) | 6, 8 | 3, 4 | L |
| 6 | Demo Suite | [PHASE_06_DEMO_SUITE.md](docs/phases/PHASE_06_DEMO_SUITE.md) | 7, 8 | 5 | M |
| 7 | Testing & Quality | [PHASE_07_TESTING.md](docs/phases/PHASE_07_TESTING.md) | 8 | 5 (parallel with 6) | S |
| 8 | Submission & Deployment | [PHASE_08_SUBMISSION_DEPLOY.md](docs/phases/PHASE_08_SUBMISSION_DEPLOY.md) | — | 6, 7 | M |

Effort key: **S** ≈ half a day, **M** ≈ 1–2 days, **L** ≈ 2–3 days for one engineer.

## Dependency graph

```
   Phase 0 (Scaffold) ─── DONE
        │
        ├─► Phase 1 (Infrastructure) ──┐
        │                              ├──► Phase 3 (Deterministic Tools) ──┐
        └─► Phase 2 (Domain Layer)  ──┤                                     │
                                       └──► Phase 4 (Claude Tools) ─────────┤
                                                                            │
                                                Phase 5 (Orchestration) ◄───┘
                                                     │
                              ┌──────────────────────┼──────────────────────┐
                              ▼                      ▼                      ▼
                        Phase 6 (Demo)         Phase 7 (Tests)        (writeable in parallel)
                              │                      │
                              └──────────┬───────────┘
                                         ▼
                                Phase 8 (Submission + Deploy)
```

**Parallelism rules**
- Phases 1 and 2 can be done by two people simultaneously — they don't share files.
- Phases 3 and 4 can be split between two people once 1 and 2 are merged.
- Phase 7 (tests) can begin as soon as the modules under test exist; it doesn't have to wait for Phase 5 to finish.
- Phase 8's documentation tasks (docs/*.md, demo video script) can be drafted in parallel with Phase 6, since they describe the system at the spec level.

## Suggested team assignments

For a 2-person team:
- **Person A:** 1 → 3 → 5 → 7 (infrastructure / orchestration / tests path)
- **Person B:** 2 → 4 → 6 → 8 (domain / Claude / demo / submission path)

For a 3-person team:
- **Person A:** 1, 5
- **Person B:** 2, 3, 7
- **Person C:** 4, 6, 8

For a 1-person team: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 in order.

## Per-phase doc structure

Every phase doc contains:

1. **Goal** — one sentence, what's done at the end.
2. **Prerequisites** — which phases must be merged.
3. **Files to create** — exact paths.
4. **Spec sections to read first** — never start without these.
5. **Task breakdown** — checklist of concrete sub-tasks.
6. **Key patterns and gotchas** — the things that will break if missed.
7. **Acceptance criteria** — how to know the phase is done.
8. **Handoff to next phase** — what the next phase consumer needs from your work.

## Status tracking

Use the checklists inside each phase doc to mark progress. When you complete a phase:

1. Tick all acceptance-criteria boxes in the phase doc.
2. Update the **Phase map** table above with status (✅).
3. Open a PR titled `Phase N: <phase name>` so the next phase's owner knows it's ready.

## Conventions for all phases

- **Python 3.10+ only.** Type hints required on public APIs.
- **`from __future__ import annotations`** at the top of every module.
- **No PHI in logs or audit entries** — references only (`Patient/abc-123`), never names/MRN/DOB.
- **Don't pass `temperature`** to Claude — `claude-opus-4-7` deprecated it.
- **`PYTHONPATH=src`** is required to import the package (src layout).
- **Run `pytest tests/ -v` before merging any phase.** Even partial test coverage catches import errors.
