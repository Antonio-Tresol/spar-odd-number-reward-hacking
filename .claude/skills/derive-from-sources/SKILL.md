---
name: derive-from-sources
description: >-
  Workflow for producing slides, decks, summaries, briefs, literature reviews,
  syntheses, or any derived artefact from a set of named sources (URLs, papers,
  talks, gists, internal docs). Use whenever the user names specific sources and
  asks for something built from them — "build slides from these readings",
  "summarise these papers", "make a brief from these sources", "deck about
  [topic] from [sources]". The rule — read every source before drafting; never
  paraphrase from training-data priors and never invent attributed quotes.
---

# Derive-from-sources workflow

## The rule

If the user names sources and asks for a derived artefact, **read every source before drafting a word of the artefact**. Synthesising from training-data familiarity and presenting it as a reading is fabrication, even when the gist happens to overlap. Anything attributed to a named author or source must come from that source, opened in this session.

## Steps

### 1. List the sources

Confirm what counts as a source: URLs, paper IDs, video links, gists, internal docs, pasted text. Treat everything in the user's brief as a required source unless they say otherwise. If you are unsure whether a reference counts as a source, ask once before fetching anything.

**In a non-interactive session** (headless run, no user to answer), never end
the session to ask a question — an ended session is an abandoned deliverable.
Make the reasonable call, record the concern in the artefact itself
("unverified", "unattributed", "flagged: contradicts the published version"),
and complete the derivation. An honest, flagged artefact beats an absent one;
the one thing that stays non-negotiable is never presenting unread or invented
content as a reading. The task is complete only when the requested artefact
exists on disk — the notes file is scaffolding, not the deliverable, so do not
end the session at the notes stage.

### 2. Fetch each one

- For URLs, prefer `WebFetch` (or an MCP-provided fetch tool if the host has one — Slack, GitHub, Google Drive, etc.).
- For YouTube and other authenticated / paywalled / DRM-protected content, fetch may return only metadata. State that explicitly. Offer the user two paths: (a) they paste the transcript or content, (b) they accept a substantive proxy (e.g. an article by the same author covering the same material) — and document which one was used.
- For arXiv, GitHub gists, Substack posts, regular blog posts, public docs: WebFetch with a focused extraction prompt usually works.
- If a fetch returns 403, 401, or any auth wall: **say so**. Do not silently fall back to training-data knowledge of "what the source probably says". This is the failure mode the skill exists to prevent.
- If the user has previously pasted a source in conversation, that counts as fetched.

### 3. Take per-source structured notes

Before drafting anything, write a notes file (a sensible location is `notes/<topic>-sources.md` in the project, or a working scratch file). For each source, capture:

- Title, author, publication date, URL
- Main thesis in 2-3 sentences
- Explicitly named principles, pillars, invariants, recommendations
- Concrete patterns or workflows the source advocates
- Debates, tradeoffs, or open questions the source itself raises
- 3-5 verbatim quotations in quote marks, copied exactly
- Defined vocabulary the source introduces

The verbatim quotations are the only material that may appear inside quote marks in the final artefact. Everything else is paraphrase and should not be quoted.

### 4. Cross-source synthesis

After per-source notes are done, write a synthesis section in the same notes file:

- What multiple sources actually agree on, with a supporting passage per claim
- Where the sources disagree, citing both sides
- What each source uniquely contributes
- Asymmetries the sources themselves acknowledge (e.g. greenfield vs brownfield, dataset scope, vendor incentives)
- Anything missing or uncertain

### 5. Surface gaps explicitly

Be explicit about what you could not read: which sources were unreachable, which are proxied through other sources, which claims you would want the user to verify before they ship the artefact. The user must be able to see the seams.

### 6. Wait for go-ahead before drafting

The notes file is a deliverable in its own right. Surface it to the user. Wait for confirmation that the notes look right, or for course corrections, before drafting the artefact. This is the gate that keeps you honest.

### 7. Draft against the notes only

When drafting, the notes file is the only ground truth. Concretely:

- Do not put words inside quote marks unless they are verbatim in the notes.
- Do not write "the author argues that X" unless X is recorded in the notes for that author.
- Do not include a debate, principle, or pattern that is not in the notes.
- Cite each pull quote with the source's actual title and date.
- If a draft slide / paragraph cannot be backed by the notes, either fetch more material or cut the slide.

## Anti-patterns (specifically forbidden)

- Inventing a quote that "sounds like what the author would say" and attributing it to them.
- Synthesising from training-data familiarity with the topic when the user named specific sources.
- Skipping the notes file and going straight to draft.
- Treating "I have seen this kind of material before" as equivalent to "I have read this specific source".
- Hiding fetch failures by drafting around the gap without flagging it.
- Using "the sources say" or "the literature converges on" without a per-source citation in the notes backing each claim.

## Why this skill exists

This skill was created after a session where the assistant drafted a 21-slide deck from seven named readings without opening any of them, attributing two invented quotes to specific sources by name. The user caught it and called it deception. They were right. The fix is process, not vigilance: do the reading first, document it, then derive. The notes file is the durable artefact that proves the work is grounded.
