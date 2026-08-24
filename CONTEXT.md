# <Organization> Wiki - Task Router

`AGENTS.md` is canonical: it holds the folder map, conventions, and hard rules. This file routes a task to the right workspace. Do not read everything; find the task family, open the workspace entry, and load only what it says to load.

Works with any agent. Start with `AGENTS.md`, read `wiki/domain.md`, then use this file to open the selected workspace `CONTEXT.md`. Wrapper details live in `AGENTS.md`; nothing here depends on a wrapper surface.

Workflows are grouped into three workspaces under `workflows/`: **ingest** (raw -> pages), **research** (question -> answer), and **maintenance** (document audits, lint, tooling evals, capture, artifact promotion, sourcing-queue refresh, synthesis, review, log rotation, and export). This file chooses the workspace; each workspace `CONTEXT.md` owns task-level routing and scopes exactly what to load.

Analysis capture, artifact promotion, and synthesis promotion share one executable approval gate, `python3 scripts/capture_gate.py`; the canonical boundary is in `AGENTS.md`. Nothing else routes through the gate.

---

## Routing

| Task family | Workspace entry |
|---|---|
| Ingest a source (`raw/` -> wiki page) | [`workflows/ingest/CONTEXT.md`](workflows/ingest/CONTEXT.md) |
| Answer a wiki question or compare entities. Default to `wiki-ask`; use `wiki-research` only when explicitly invoked | [`workflows/research/CONTEXT.md`](workflows/research/CONTEXT.md) |
| Audit or lint the wiki, verify tooling, capture context, promote artifacts, refresh sourcing, synthesize, review outcomes, rotate the log, or export | [`workflows/maintenance/CONTEXT.md`](workflows/maintenance/CONTEXT.md) |
| Browse what's in the wiki | [`wiki/index.md`](wiki/index.md) |

The workspace `CONTEXT.md` and task files own task-level routing and Load / Skip lists. Follow the selected workspace instead of reconstructing maintenance routes here.
