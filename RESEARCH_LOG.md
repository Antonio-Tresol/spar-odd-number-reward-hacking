# Odd Number Reward Hacking — research log

## Project summary

Update this regularly. One paragraph covering: what paper, codebase, or project
idea this builds on; what we are trying to figure out; how it connects to the
broader landscape.

SPAR Model Forensics take-home, single setting (Odd Number environment), 5-hour budget, replication excluded from the limit

---

# Log

Newest entry first. Every entry answers the same four questions. A null or
infeasible result recorded with evidence counts as a completed experiment.

Entry format:

```
### YYYY-MM-DD

* What I did:
* What I expected vs what happened:
* What this changes about my thinking:
* What I will do next:
```

### 2026-08-24

* What I did: Scaffolded the project from the research-harness — skills, research tree, this log, and the mechanical validator — and wrote Q1 into TREE.md. Merged the separate take-home workspace repo into this one under `notes/take-home/`, retiring the second repo. Began the literature pass with Singh et al., *Model Forensics* (arXiv:2606.26071) — the mentor's own paper, which defines the protocol this take-home asks us to apply — took verbatim notes in `notes/model-forensics-paper-notes.md`, and derived a `model-forensics` skill from those notes. Fixed two Windows path-separator bugs in the vendored lanorme plugins that were silently disabling PROV-003 and STALE-002.
* What I expected vs what happened: I expected the paper to be background reading. It is closer to a rubric — it names the standard of evidence, the seven benign explanations that must be ruled out, and the failure modes (negative results are not symmetric with positive ones; counterfactual effect sizes are confounded three ways). Separately, I expected the harness checks to be sound; two of them were passing by scanning zero files on Windows, which is the failure mode those checks exist to prevent.
* What this changes about my thinking: Q1 should not be framed as "is this reward hacking?" but as "which of the candidate explanations survives?" — benign motif 4 (an RLVR-trained model treating an ambiguous environment feature as task-relevant) is a serious competitor to reward hacking for the Odd Number setting, and motif 1 (task misspecification) is a second. Any claim needs a control setting and a positive control before it means anything.
* What I will do next: Replicate the Odd Number result and measure a base rate with a reportable *n*, then build the control setting (remove the in-context reward function and verify the behavior disappears).
