---
name: communicate-results
description: >-
  Presenting empirical results honestly and legibly — slide decks for research
  meetings, chart hygiene, error bars, and showing raw prompts and outputs. Use
  when preparing an update, writing up findings, making figures, or answering
  "how did the experiments go?".
---

# Communicating results

Doing great experiments is only half the journey — they matter only if people
understand them. Budget for this: the first deck of a project costs a day or two,
later ones about half a day.

## The standing deck

Keep **one deck per project**, extended over time rather than rebuilt. Structure:

1. **Summary slide** — the takeaways from last meeting plus what this round's
   experiments showed. A reader who sees only this slide should be correctly
   oriented.
2. **Agenda** — sections in priority order, with rough time allocations.
3. **Experimental setup** — what was run, on what, with what prompts.
4. **Results** — strongest message first.
5. **Discussion / next steps** — what you propose to do, and what you need.
6. **Backup slides** — everything anticipated-but-not-central.

**Lead with the most important message.** You may have tried ten setups; you do not
show ten. The ones that did not work go in backup slides — available when asked,
not occupying the main line.

## Honesty requirements (these are the point, not decoration)

- **Show the full prompts** alongside results. A result without its prompt is not
  interpretable.
- **Show real model outputs** — put actual transcripts in backup slides. Aggregate
  numbers hide the behaviour that produced them.
- **Error bars on every proportion.** For a rate over *N* items, standard error is
  `SE = sqrt(p(1-p)/N)`. A bar without an interval invites over-reading.
- **State *n* and the aggregation rule** with any headline number — best-of-*k*,
  mean over seeds, and union-over-variants are different claims, and results can
  reverse depending on which you used.
- **Nulls and negative results are content**, reported plainly. A detector that
  barely fires is reported as barely firing, never rehabilitated with framing.

## Writing for readers who do not know the thing exists

- **Introduce concepts before naming them.** Explain the idea as if the reader
  has never encountered it — what it is, why it matters here — and only then
  attach its name and origin. "When you ask humans to rate emotions, they
  arrange on two axes, pleasantness and activation; this is Russell's
  circumplex model" teaches; opening with "per Russell's circumplex model"
  gatekeeps. A named concept the reader cannot reconstruct is jargon, not a
  citation.
- **Citations carry locators.** A reference is a claim about where a fact
  lives, so cite to the finest grain the source allows: page for papers and
  books, section or figure for web-native publications, file and line for
  code. Locators are added when the source is read in-session — a page number
  written from memory is a fabrication risk, not a courtesy. If the source has
  not been read yet, cite the work without a pinpoint and mark the pinpoint as
  pending verification.
- **No acronym before its definition.** Expand at first use — "principal
  component analysis (PCA)", "false-positive rate (FPR)" — or maintain a
  `GLOSSARY.md` in the project whose entries carry a source backing each
  definition. An undefined acronym is a claim the reader already belongs to
  the club; documents in this workflow assume the opposite.

## Chart hygiene

- Simple charts beat clever ones: prefer bar charts over heatmaps.
- Three to five colors maximum.
- Label axes, and say which direction is better.
- Put the actual value on the chart (e.g. `51.4%`), not just the bar height.

## Before it leaves the project

Every number in a deck, report, or notebook must trace to a results file — run the
`validate-claims` protocol. Communication is a place where prose silently drifts
from the data it describes, so the check applies to the write-up, not only to the
analysis.

$ARGUMENTS
