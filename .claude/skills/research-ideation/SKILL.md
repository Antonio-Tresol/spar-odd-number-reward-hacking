---
name: research-ideation
description: >-
  Choosing and sequencing research work — scoping a question, ordering
  experiments by information gained per unit time, and de-risking before
  executing. Use when picking a research question, deciding what to run next,
  when a project feels stuck, or when deciding whether to keep going or pivot.
  Humans set direction; this skill structures the choice.
---

# Research ideation and sequencing

Humans own the direction. This skill exists to make the choice explicit and to
stop the most expensive failure: finishing the easy parts of a project whose hard
part was never going to work.

## The core framing

Research is a multi-round game: each round you take an action that yields
stochastic information. You are optimising two things at once — the probability
the project succeeds, and the time it takes. The operating principle:

> **Reduce uncertainty at the fastest possible rate.**

Not "easy things first" (they may be irrelevant). Not "hard things first" (they
may be expensive to even attempt). **Most-informative-per-hour first.**

## De-risk, then execute

Before building anything properly, list the project's components and ask of each:
*if this fails, is the project dead?* Those are the load-bearing ones. For each,
find the cheapest probe that would give high confidence it works — a tiny sample, a
single prompt, a 1B model, a hardcoded stub. Run all the probes first. Only then
execute.

Two ways to order the probes:

- **Expected time saved**: do first the task whose *failure* would save the most
  downstream work.
- **Failure rate**: sort by `λ = -ln(P(success)) / duration`, highest first — the
  fastest-to-eliminate, most-likely-to-fail things go first.

Both are estimates. Writing the numbers down is more useful than getting them right.

## Scoping a question

A well-scoped question for a short project is answerable with one dataset, one or
two models, and metrics you already know how to compute. Write it into `TREE.md`
as `Q1` before writing code — a question you cannot state in one sentence is not
scoped yet.

Then decompose recursively: question → hypotheses → the smallest experiment that
would discriminate between them. Break down until each piece is small enough to
attempt in one sitting. Fill the pieces in fast; polish only once the skeleton
stands. Building linearly — perfecting each part before moving on — is the slowest
way to finish, and the outline you get from decomposing is itself the plan.

## Write to think

Expect most of a project's ideas to arrive *during* writing, and expect a large
share of your starting assumptions to be wrong. This is why the research log's
"what I expected vs what happened" bullet is load-bearing and not bureaucracy:
writing the expectation *before* the result is what makes the surprise legible, and
the surprise is where the research is.

Practical consequence: when stuck, write. Draft the paragraph explaining what you
would conclude if the current run succeeds. If that paragraph is boring or
unfalsifiable, the experiment is not worth running yet.

## Deciding to pivot

Pivot when a load-bearing component has failed its probe and no cheap alternative
exists, or when the expected information from the next experiment no longer
justifies its cost. Record it: the node in `TREE.md` becomes `abandoned` with a
log-date pointing at the entry explaining why. An abandoned branch with a recorded
reason is a result — it tells the next person (or the next you) what not to retry.

$ARGUMENTS
