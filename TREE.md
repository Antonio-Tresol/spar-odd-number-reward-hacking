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
