# <Organization> Wiki - Task Router

`AGENTS.md` is canonical: it holds the folder map, conventions, and hard rules. This file routes a task to the right workspace. Do not read everything; find the task family, open the workspace entry, and load only what it says to load.

Works with any agent. Start with `AGENTS.md` and check `wiki/domain.md`. An unconfigured clone routes to `SETUP.md` and stops there. A configured wiki reads this file, then opens the selected workspace `CONTEXT.md`. Wrapper details live in `AGENTS.md`; nothing here depends on a wrapper surface.

Workflows are grouped into three workspaces under `workflows/`: **ingest** (raw -> pages), **research** (question -> answer), and **maintenance** (hygiene, audits, tooling, capture, synthesis, review, and export). This file chooses the workspace; each workspace `CONTEXT.md` owns task-level routing and scopes exactly what to load.

Analysis capture, artifact promotion, and synthesis promotion share one executable approval gate, `python3 scripts/capture_gate.py`; the canonical boundary is in `AGENTS.md`. Nothing else routes through the gate.

---

## Routing

| Task family | Workspace entry |
|---|---|
| Configure a fresh clone | [`SETUP.md`](SETUP.md) |
| Ingest a source (`raw/` -> wiki page) | [`workflows/ingest/CONTEXT.md`](workflows/ingest/CONTEXT.md) |
| Answer a wiki question or compare entities | [`workflows/research/CONTEXT.md`](workflows/research/CONTEXT.md) |
| Maintain or audit the wiki, verify tooling, capture context, synthesize, review outcomes, or export | [`workflows/maintenance/CONTEXT.md`](workflows/maintenance/CONTEXT.md) |
| Browse what's in the wiki | [`wiki/index.md`](wiki/index.md) |

The workspace `CONTEXT.md` and task files own task-level routing and Load / Skip lists. Follow the selected workspace instead of reconstructing maintenance routes here.
