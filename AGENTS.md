# Odd Number Reward Hacking — Model Forensics SPAR take-home: why do models output an odd number in the Odd Number toy environment when asked for an even number but given an in-context reward function that rewards odd numbers? Reward hacking, or something else?

Instructions for any coding agent working in this repository (Codex, Claude
Code, Cursor, Aider, and anything else reading `AGENTS.md`). `CLAUDE.md` imports
this file, so there is one source of truth rather than two that drift.

SPAR Model Forensics take-home, single setting (Odd Number environment), 5-hour budget, replication excluded from the limit
Everything here is optimised for one thing: ending the project with **answers we
can trust**, with an audit trail proving it. A well-evidenced null, a refuted
hypothesis, or an honest "infeasible in the time available" is exactly as much a
success as a positive finding. There is no pressure to produce positive results,
only to record what is true.

## State and history (read these first, every session)

- `TREE.md`: the research tree, questions → hypotheses → experiments → claims,
  with statuses and evidence links. This is the current state of belief.
- `RESEARCH_LOG.md`: the daily log (4-question format, newest first). This is the
  append-only history. Never encode state only here or history only in the tree.
- `uv run scripts/validate_research.py`: mechanical validator for both. Must exit
  0 before ending any session and before any deliverable.
- `./check.sh`: every mechanical check. `lanorme` (code quality, Agent Skills
  spec, plus the harness plugins `tensors` for jaxtyping/einops discipline and
  `skill_portability`) followed by the research-integrity gate. Run after
  editing any skill, script, or pipeline.

Two kinds of Python live here, and they follow different rules.

- **The harness's own tooling** (`scripts/validate_research.py`,
  `scripts/run_skill_evals.py`, and the skills' `references/*.py`) stays
  self-contained PEP 723 uv scripts — inline dependencies, no venv, runnable
  from any checkout. Leave them that way.
- **This project's research code** is a package: `src/odd_number/`, declared in
  `pyproject.toml`. `uv run` installs it, so tests and modules import
  `odd_number.*` directly — no `sys.path` manipulation anywhere. One CLI is the
  front door:

  ```
  uv run odd-number prompts                    # print every prompt treatment
  uv run odd-number models                     # every pinned model
  uv run odd-number endpoints qwen/qwen3.6-27b # provider tags available to pin
  uv run odd-number collect --mock --n 5       # no API key needed
  uv run odd-number collect --model qwen/qwen3.6-27b --n 40
  uv run odd-number audit results/<file>.jsonl # did the pins hold?
  uv run odd-number grade results/<file>.jsonl
  ```

  Modules are importable library code with no import-time side effects;
  argument parsing lives only in `cli.py`. Type hints throughout, absolute
  imports throughout (`from odd_number.x import y`, never `from .x`).

  Three rules the layout enforces.

  1. **Vendor types stop at `completions.py`.** Nothing else touches a
     `ChatResult`, and that boundary uses direct typed attribute access, so a
     renamed SDK field raises instead of silently yielding `""`.
  2. **Configuration is read once**, in `settings.py`, via `pydantic-settings`
     — never `os.environ.get` at a point of use.
  3. **Names say what a thing is or does.** A module is named for the principal
     type it defines, pluralised (`rollouts.py` → `Rollout`, `completions.py` →
     `Completion`, `grades.py` → `Grade`, `pinned_models.py` → `PinnedModel`), or for
     the domain area when it defines a single configuration or specification
     rather than a kind of thing (`settings.py`, `sampling.py`, `environment.py`,
     `client.py`). Functions are verbs that name their object — `classify_parity`
     not `classify`, `build_routing_body` not `routing`, `load_completed_keys`
     not `done_keys`. Types are what the thing *is*, not what happened to it:
     `Grade`, not `Graded`.

The split is deliberate: a promoted pipeline that other code imports and tests
exercise wants to be a package, while a validator that must run in a repo with
no venv wants to be a standalone script.

## The workflow

Phases iterate; the gates do not.

0. **Speed is a first-class constraint.** Most work is exploratory de-risking in
   notebooks and throwaway scripts, and that code is deliberately exempt from
   polish and linting (`experiment-engineering` has the two-mode table). Gates
   apply at *promotion*, when code produces evidence a claim rests on. What is
   never deferred, even in explore mode, is the observability contract: structured
   incremental logs, resumable checkpoints, fail-fast ordering, seeds. Unlogged
   fast work has to be re-run, and re-running is slower than logging was.
1. **Scope**. One narrow question answerable within the project's budget of
   data, models, and time. Use `research-ideation`: de-risk load-bearing
   components with cheap probes before executing, ordering by information gained
   per unit time. Write the question as `Q1` in TREE.md before anything else.
2. **Literature** (timebox it). Use the `research` skill for search and retrieval; papers
   land in `data/papers/`. Any synthesis document follows `derive-from-sources`:
   read every source, notes file with verbatim quotes first, draft only from notes.
3. **Design**. For eval work, follow the `eval-design` skill: threat model →
   specification → operational definitions → question design → QC, with the
   construct-validity checklist. Name the confound-of-concern explicitly and
   design at least one read that separates construct from confound.
4. **Experiment**. Follow `experiment-engineering`. Explore freely in notebooks;
   promoted pipelines live under `scripts/` or `src/`, results as `.jsonl` under
   `results/` written incrementally (these paths are the evidence the tree links).
   Any run costing real time or money must be resumable: kill it halfway and
   re-running should pick up where it left off. Fixed seeds; a result that can't
   be re-produced by re-running a script doesn't count as evidence.
5. **Falsify** (gate). Before any claim graduates, run the `falsify` skill:
   design tests that could destroy each claim. Update claim statuses in TREE.md:
   `survived` / `weakened` / `failed`, scorecard linked as evidence.
6. **Validate** (gate). Before any document with numbers leaves the project, run
   `validate-claims`: every number traced to a results file, every methodology
   sentence to code, every citation to a real paper, looped to zero mismatches.
7. **Log**. End every session by appending the day's RESEARCH_LOG.md entry and
   running the validator (`research-log` skill has the full ritual).
8. **Communicate**. Use `communicate-results` for decks and write-ups: strongest
   message first, failed setups in backup, error bars and *n* on every number,
   full prompts and real outputs shown.

## Collaboration and parallelism

- **Branches and PRs between humans.** Direct commits to `main` are for solo
  work only. When more than one person is on the project, work happens on
  short-lived branches merged to `main` by PR; a PR that adds or changes
  results, claims, or documents with numbers runs `./check.sh` and the
  `validate-claims` gate before merge. `main` is always green: validator exit 0,
  all checks passing.
- **Worktrees between parallel sessions.** Two agent sessions in one clone will
  fight over TREE.md, RESEARCH_LOG.md, and `results/`. Run parallel sessions in
  separate git worktrees (`git worktree add ../<name> <branch>`; Claude Code can
  create one for a session with EnterWorktree), one branch per worktree, merged
  back like any other branch.
- **Be an orchestrator.** For work that fans out — sweeps, literature searches,
  reviews, independent experiments — delegate to subagents or an agent team and
  keep synthesis in the orchestrating session. Three rules learned the hard way:
  give subagents self-contained prompts (they do not see your conversation);
  give any subagent that executes untrusted or generated work a workspace
  *outside* the repository (a nested workspace let eval agents write fabricated
  state into a host project's tree); and keep a **single writer** for TREE.md
  and RESEARCH_LOG.md — subagents report findings back, the orchestrator records
  them. The tree survives parallelism because updates flow through one pen.

## Non-negotiables

- No claim in any deliverable that is not a node in TREE.md with linked evidence.
- No quoted text that is not verbatim from a source read in-session.
- Honest nulls: an effect that doesn't appear is reported as such, never dressed
  up. A null or infeasible result recorded with evidence is a completed
  experiment, not a failure to complete one.
- Pivots are recorded, not erased: nodes become `abandoned`, never deleted.

## Tooling

- MCP: `arxiv-mcp-server` (paper storage: `data/papers/`, path relative to the
  project root; after your first download, verify papers actually land there and
  switch to an absolute path in `.mcp.json` if they don't), `paper-search-mcp`
  (multi-source search). Configured in `.mcp.json`.
- Skills live in `.claude/skills/<name>/SKILL.md`, with `.agents/skills`
  symlinked to the same directory so Codex finds them too. Both load skills
  automatically from the `description` field. If your agent does neither, read
  the file that matches before starting that kind of work:

  | Read this | When |
  |---|---|
  | `research-ideation` | choosing what to run next, scoping, or stuck |
  | `research` | searching or retrieving literature |
  | `derive-from-sources` | writing anything derived from named sources |
  | `eval-design` | designing an eval or writing eval questions |
  | `model-forensics` | explaining *why* a model did something concerning — before calling it reward hacking, deception, or misalignment |
  | `experiment-engineering` | writing any script that costs GPU time or API budget |
  | `falsify` | before any claim graduates from `unvalidated` |
  | `validate-claims` | before any document with numbers leaves the project |
  | `research-log` | at the start and end of every session |
  | `communicate-results` | preparing an update, figures, or a write-up |

  All are generic and portable, with no machine-specific paths.
- Machine-specific pointers (local copies of reference material, related repos)
  live in `CLAUDE.local.md`, which is gitignored, so each team member keeps their
  own. All sources the skills cite are public; unequivocal identifiers (arXiv
  ID / DOI / URL) are in the harness repo's `references/harness.bib`.
- **Shared session configuration** (checked in, applies to everyone on clone):
  - `.claude/settings.json` — compaction forced at 50% context
    (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`; effective on Opus 4.8 and most models,
    documented as having *no effect on Sonnet 5*, unverified on Fable), agent
    teams enabled (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`), and Opus as the
    advisor model (Fable is the intended advisor once its advisor rollout
    completes — currently unselectable per docs; revisit cost before flipping,
    since advisor calls bill at the advisor model's rates). Teams and
    advisor are experimental; advisor needs the
    Anthropic API. Personal opt-outs go in the gitignored
    `.claude/settings.local.json`, which overrides project settings.
  - `.codex/config.toml` — Codex auto-compaction at ~50% of a 400k window
    (`model_auto_compact_token_limit = 200000`; Codex takes tokens, not
    percentages — adjust if the default model's window differs). Loads only
    after you mark the project trusted, and note it *outranks* your personal
    `~/.codex/config.toml`. Codex subagents are on by default; shareable custom
    agent roles can be added under `.codex/agents/` if the project needs them.
