# Multi-Agent Teams

**Status:** implemented (2026-10-08) · branch `multi-agent`
**Inspired by:** stablyai/orca (fleet of parallel agents), HarnessMD/munder-difflin
(office of agents), OpenHands/OpenHands (agent loop patterns)

## Architecture

```
backend/teams/
  definitions.py   Team + AgentSpec data; 3 built-in teams
  runner.py        fan-out (asyncio.gather over specialists) /
                   fan-in (coordinator synthesis); per-agent
                   failure isolation
  __init__.py      register_teams_extension() -> capability:multi_agent
```

### Built-in teams
| Team | Specialists | Coordinator does |
|---|---|---|
| research | Researcher + Fact-checker | Sourced brief, drops unverified claims |
| code | Coder + Reviewer | Final code with review fixes applied |
| writing | Writer + Editor | Polished piece |

### Flow
1. `POST /api/teams/run` {team_id, task, model?} — gated by `FEATURE_MULTI_AGENT`
   (404 when off).
2. Specialists run **concurrently**, each with its role system prompt.
3. Coordinator synthesizes successful specialists' outputs.
4. Response includes the synthesis **and** per-specialist outputs/elapsed/error.

A failed specialist doesn't fail the run — the coordinator works with what
succeeded. If all specialists fail, the run reports an error.

### Frontend
`features/teams/teams.js` — a Teams button (topbar, hidden unless the
`multi_agent` feature flag is on) opens a modal: team picker, task box, run
button. Results show the synthesis plus collapsible specialist sections.

### Adding a team
Add a `TeamDefinition` in `definitions.py` — no other code changes needed.

## Future (not in this pass)
- Streaming team progress (SSE per specialist)
- Custom user-defined teams via UI
- Specialist tool use (web_search/file ops inside specialist runs)
- Long-running teams with persistence
