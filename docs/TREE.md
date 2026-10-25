# Sangam — Tree (perfect-flow program)

Top-level layout. `mainfiles/` holds the runnable app (backend +
frontend); the repo root holds docs, specs, and tooling. Nothing
outside `mainfiles/` is served.

```
sangam/
├── ARCHITECTURE.md          # full architecture guide (root, not docs/)
├── FIX_LOG.md               # change log for this iteration (root)
├── MANIFEST.md              # coordinator manifest (root)
├── README.md                # claims-checked feature list (root)
├── SECURITY.md
├── docs/                    # this program's doc set
│   ├── INFORMATION_ARCHITECTURE.md
│   ├── RESPONSE_PIPELINE.md
│   ├── AGENT_RUNTIME.md
│   ├── MEMORY.md
│   ├── SKILLS.md
│   ├── STUDIO.md
│   ├── SETTINGS.md
│   ├── EVENTS.md
│   ├── TESTING.md
│   ├── ATTRIBUTIONS.md
│   ├── TREE.md              # this file
│   ├── CODE_TREE.md         # module map with owners
│   ├── DECISIONS.md         # user-approved defaults + out-of-scope
│   ├── DESIGN.md            # pre-existing design notes
│   ├── REPO_COVERAGE.md     # pre-existing coverage notes
│   └── STUDIO_AUDIT.md      # pre-existing studio audit
├── mainfiles/
│   ├── backend/             # FastAPI + SQLite/SQLAlchemy/LiteLLM/ChromaDB
│   │   ├── main.py          # lifespan: workflow + agent schedulers
│   │   ├── api.py           # router mounting
│   │   ├── api_routes/      # one module per surface (see CODE_TREE.md)
│   │   ├── agent_runtime/   # planner, state machine, scheduler,
│   │   │                    # approvals, budgets, circuit, audit
│   │   ├── response_intelligence/  # intake→…→post-actions pipeline
│   │   ├── providers/       # 11 providers, capability registry
│   │   ├── contracts.py     # error envelope, pagination, RunStore
│   │   └── <domain modules> # projects, memory, skills, studio, …
│   └── frontend/            # vanilla JS SPA (NO React/Vue)
│       ├── index.html       # sidebar rail + chat + tool view shells
│       ├── css/style.css    # tokens + components (single file)
│       └── js/
│           ├── app.js       # boot: rail/palette before model probe
│           ├── core/        # nav, state, tabs-adjacent helpers
│           ├── features/    # one folder per destination/feature
│           │   ├── shell/   # router + destination renderers
│           │   ├── tabs/    # tabs.js: navigation + pushState
│           │   ├── palette/ # Ctrl/Cmd+K command palette
│           │   ├── settings/# control center + sections
│           │   ├── projects/# project workspaces
│           │   ├── studio/  # documents/design/diagrams/image/voice
│           │   ├── agents/  # hub, task board, run history
│           │   └── …        # chat, composer, models, memory, …
│           ├── shared/      # http, settings_schema, settings_store
│           └── vendor/      # qrcode.min.js etc.
├── scripts/
│   └── check_frontend_modules.mjs  # module parse+link gate (70/70)
└── tests/
    ├── e2e/                 # Playwright specs (see TESTING.md)
    │   ├── run_smoke.sh     # required gate runner (fresh DB + mock)
    │   └── *.spec.ts        # shell, smoke, runs, skills, … (25 green)
    └── test_*.py            # pytest suite (see TESTING.md)
```

## Notes

- `features/work/work.js` was deleted in this program: the old Work
  container module was orphaned by the IA swap and nothing imported
  it. `features/home.js` stays (dynamically imported by
  `settings/sections.js`).
- `test-results/` and `tests/e2e/screenshots/` are run artifacts,
  gitignored in practice (never committed except the deliberate
  `runs-centre-linux.png` baseline under `*.spec.ts-snapshots/`).
- Old destination ids (`home/work/create/knowledge`) survive ONLY as
  redirects in `features/shell/router.js` — never as UI.
