# Handoff — continuing on another machine

Written 2026-08-25. This is a session-boundary document: how to get running
elsewhere, and what to do first. It does **not** duplicate project state.

- **What is believed and what is open** → `TREE.md`
- **What happened and why** → `RESEARCH_LOG.md`
- **How to work here** → `AGENTS.md`
- **Why this model slate** → `notes/model-selection.md`

If this file ever disagrees with those, they win.

## 1. Get running on the laptop

```bash
git clone <remote> spar-odd-number-reward-hacking
cd spar-odd-number-reward-hacking
```

Four things a clone does not carry:

**The API key.** `.env` is gitignored and must never be committed — a key that
reaches git history is burned and has to be rotated, not deleted.

```bash
cp .env.example .env
```

Then paste your key into `OPENROUTER_API_KEY`. `settings.py` reads `.env` *and*
the real environment, environment winning, so `export OPENROUTER_API_KEY=...`
also works and is what a cloud runner should use.

**The pre-commit hook.** Git never versions `.git/hooks/`.

```bash
bash hooks/install.sh
```

**Python 3.13.** Pinned via the committed `.python-version`. If that file ever
goes missing, `UV_PYTHON=3.13 bash check.sh` is the equivalent — `lanorme`
requires >=3.13 and uv's default interpreter may be older.

**The `.agents/skills` symlink** (Windows only). If it checks out as a 17-byte
text file, git recorded `core.symlinks=false`:

```bash
git config core.symlinks true && rm .agents/skills && git checkout -- .agents/skills
```

Symptom if missed: `check.sh` fails `skill_portability`, and Codex silently
loads zero skills.

Then confirm the whole thing works without spending anything:

```bash
uv run odd-number collect --mock --n 2 && bash check.sh
```

`check.sh` must exit 0. On Windows it dies roughly one run in three with
`Application Control policy has blocked this file (os error 4551)` while
spawning `pytest.exe`. That is not a test failure — it exits 2 rather than 1,
and lanorme reports `0 failed` in the same run. Just re-run it.

## 2. Running it in the cloud

Never commit the key. Use the runner's own secret store and let it inject the
environment variable — `settings.py` prefers the environment over `.env`
precisely so no file is needed:

- **GitHub Actions** — repository *Settings → Secrets and variables → Actions*,
  then `env: OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}`.
- **Any other runner** — whatever its secret mechanism is, exported as
  `OPENROUTER_API_KEY`.

I could not verify the exact secret-configuration UI for Claude Code cloud
sessions from this machine, so check that in the app rather than taking a
guess from here. The requirement either way is only that
`OPENROUTER_API_KEY` is present in the process environment.

## 3. State of the code

Green as of the last commit: 162 tests, `check.sh` exit 0, validator exit 0.

```
uv run odd-number prompts                       # every prompt variant
uv run odd-number models                        # the pinned slate
uv run odd-number endpoints qwen/qwen3.6-27b    # provider tags available to pin
uv run odd-number collect --mock --n 5          # no API key needed
uv run odd-number collect --model qwen/qwen3.6-27b --n 40
uv run odd-number audit results/<file>.jsonl    # did the pins hold?
uv run odd-number grade results/<file>.jsonl    # BLOCKED, see below
```

Collection is resumable: re-running the same command collects only what is
missing, so a killed run costs at most the in-flight call.

## 4. Do this first

**Run the baseline A/B at n>=40 per arm across all three ladder rungs.** This is
`Q1.H1.E1` and it is the experiment everything else waits on. All three rungs
are pinned and smoke-tested; nothing is blocking it.

```bash
uv run odd-number collect --model qwen/qwen3.5-27b --n 40
uv run odd-number audit results/odd-number-qwen-qwen3.5-27b.jsonl
uv run odd-number collect --model qwen/qwen3.6-27b --n 40
uv run odd-number audit results/odd-number-qwen-qwen3.6-27b.jsonl
uv run odd-number collect --model qwen/qwen3.8-27b --n 40
uv run odd-number audit results/odd-number-qwen-qwen3.8-27b.jsonl
```

Roughly $0.25–0.75 per model at n=40 per arm. Run `audit` after each — it reads
the file, calls no API, and fails loudly if anything was served by an endpoint
other than the pinned one.

Cost is genuinely not the constraint on this design, so do not shrink *n* to
save money.

## 5. Then: the blocker

`grades.extract_number` raises `NotImplementedError`. **Nothing can be scored
until it is written**, and it is the single decision that determines what every
rate in the project means. Its docstring lays out the trap: a "last number wins"
rule reads the operand of a restated `reward = output % 2` as the model's
answer.

The direction chosen was a pinned cheap-LLM judge, scaffolded in
`src/odd_number/answers.py` and **imported by nothing**. `Q1.H7.E3` tracks the
three things it still needs:

1. **Record the judge's own justification and its chain of thought.** `Answer`
   has neither today. A judge you cannot inspect is a regex you cannot read.
2. **Validate it against hand-labelled fixtures before any rate depends on it**,
   reporting agreement. It is a measurement instrument; an unvalidated
   instrument is an unmeasured one.
3. **Wire it into `grades.py` behind a flag**, so `grade` still runs with no
   API key.

The deterministic path (a response that *is* a bare integer, which is every
rollout collected so far) needs no judge and is already written.

## 6. Open decisions

- **NLA scope** — deferred until the chains of thought have been read. Public
  NLAs exist only for pre-2026 checkpoints, so a legacy Qwen2.5-7B arm would be
  a methods demonstration, not evidence about a current model.
- **CoT analysis** — the idea of a second LLM pass over the subject models'
  reasoning for evaluation awareness, confusion, gaming, and justification is
  not built. It does not need to be yet: the full transcripts are already
  recorded verbatim in `results/*.jsonl` (`prompt`, `response`, `reasoning`),
  so that analysis can be done later over data already collected, with nothing
  re-run.
- **`top_k=0`** — sent as the vLLM convention for "disabled", verified only far
  enough to know the pinned endpoints accept it and still produce normal-length
  output. Whether DeepInfra and Parasail both read it as "disabled" is
  unconfirmed. Documented in `sampling.py`.

## 7. Things that will bite

- **The ladder's residual confound**: 3.8 is served by Parasail, 3.5 and 3.6 by
  DeepInfra. No provider serves all three reliably. Any rung-to-rung comparison
  has to say so — `Q1.H7.E2.C5`.
- **Only one lens is trustworthy.** Of four slate Jacobian lenses, exactly one
  (`qwen3.5-27b`) has a verified source checkpoint. `gemma-4-31b`'s is fitted on
  *base* weights while OpenRouter serves `-it`. Do not build a readout on an
  unverified lens — `Q1.H7.E2.C4`.
- **`seed` is best-effort.** At `temperature=1.0` on a continuously batched
  endpoint it does not give per-rollout replay. The reproducibility that carries
  evidence here is distributional — *n* rollouts and an interval.
