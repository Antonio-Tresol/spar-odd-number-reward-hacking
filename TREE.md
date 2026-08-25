# Research tree

State of the project: questions → hypotheses → experiments → claims.
Grammar and status vocabulary: see `.claude/skills/research-log/SKILL.md`.
Validate with `python scripts/validate_research.py`. Never delete nodes — mark
them `abandoned` and point at the log entry explaining why.

- Q1: Why do models output an odd number when asked for an even number, given an in-context reward function that rewards odd numbers? [open]

  - Q1.H1: The odd answer is reward hacking — the model recognises the grader as a reward signal and optimises it against the user's stated instruction. [open]
    - Q1.H1.E1: Replicate the gaming rate on condition A (`reward = output % 2`) against the built-in control B (`reward = 1 - (output % 2)`, reward and instruction agree), n>=40 per arm, one public reasoning model. Second measure: reasoning length, which the source post reports as much higher under A. [planned]
  - Q1.H2: The model reads the `<_grader>` field as part of the task specification rather than as something to exploit — the RLVR bias toward treating environment features as task-relevant (benign motif 4). [open]
  - Q1.H3: The prompt is a genuinely contradictory specification, and the model resolves it toward the machine-readable half. This makes the behaviour an instruction-priority question, not a misalignment one (benign motif 1). [open]
  - Q1.H4: The model is metagaming — it reads the real task as a test of its strategic ability, so answering odd is compliance with the task it believes it was set, not defection from the stated one. Named explicitly by the mentor in `notes/concrete-problems-notes.md`. [open]
  - Q1.H5: Conditional on H4 — if the model is metagaming, its reasoning is motivated (rationalising toward the answer that "passes") rather than faithful. Only testable if H4 is supported. [open]
  - Q1.H6: Orthogonal to H1 — if the model is prioritising the grader over the user, it is *aware* it is doing so. The awareness axis is separable from the behaviour: a reward seeker that knows it is one makes different predictions (concealment, justification) than one that does not. [open]
  - Q1.H7: Principal ambiguity — the model cannot determine who it is supposed to satisfy, treating the grader as a "meta-user" whose instruction outranks or merges with the user's. Distinct from H3: the spec is not contradictory to the model, it simply resolves to a different principal. [open]
    - Q1.H7.E2: Model-selection sweep. Screen open-weights reasoning models on OpenRouter for (a) a measurable gaming rate, (b) readable `reasoning.text` rather than a provider summary, (c) post-RL training. Output: the shortlist worth self-hosting for activation access. [planned]
