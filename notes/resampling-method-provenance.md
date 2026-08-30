# Which resampling method Q1.H8 actually implements

Both papers read in session on 2026-08-29, from PDFs in `data/papers/`. Quotes
below are verbatim from those files and are the basis for everything after them.

| | paper | local copy |
|---|---|---|
| **TA** | Bogdan, Macar, Nanda, Conmy, "Thought Anchors: Which LLM Reasoning Steps Matter?", arXiv 2506.19143 | `data/papers/2506.19143.pdf`, 34pp |
| **TB** | Macar et al., "Thought Branches: Interpreting LLM Reasoning Requires Resampling", arXiv 2510.27484 | `data/papers/2510.27484.pdf` |

TA is the paper the mentor's take-home links. TB is the paper this project built
from. TB is a successor and cites TA for the primitive.

## What each paper defines

**TA §2.3, the resampling design.** For a sentence `S_i`, two distributions over
final answers, each from 100 rollouts. TA writes the base condition as rollouts
of the form "S1,S 2,...,S i−1,Ti,...,T N,A′" and the intervention condition as
"S1,S 2,...,S i−1,Si,...,S M,ASi". So the base condition truncates *before* `S_i`
and resamples forward; the intervention condition holds `S_i` and resamples
forward from `i+1`. The contrast between them is the effect of that one sentence.

**TA §3.2 defines two measures on that design, and prefers the second.**

1. Resampling importance, the plain KL between the two conditions:
   `importance_r := D_KL[p(A'_Si) || p(A_Si)]`.
2. Counterfactual importance, the same KL conditioned on the resampled sentence
   being semantically different from the original: `D_KL[p(A'_Si | T_i ≉ S_i) ||
   p(A_Si)]`.

TA states the reason for preferring the second in one sentence: "if Ti is
identical or similar to Si then we do not get much information about whether Si
is important or not" (TA §3.2). Dissimilarity is operationalised as embedding
cosine similarity below the dataset median.

**TB §2.1.1** restates that same conditioned formula as its "counterfactual
importance baseline", credits Bogdan et al. for it, and names the embedding
model: `bert-large-nli-stsb-mean-tokens`.

**TB §2.1.2** adds two things TA does not have. *Resilience*, which TB describes
as "how many times we must intervene to keep a sentence's semantic content from
reappearing downstream", and *counterfactual++*, the KL conditioned on the
content being absent from the whole remaining trace rather than only at position
`i`. TB's stated motivation is that reasoning models regenerate deleted ideas: "a
sentence removed at position i may resurface at position j≥i" (TB §2.1.2).

## What this project implements

`src/odd_number/branches.py`. The resampling design is TA §2.3 exactly: hold
`S_1..S_k` as prefix, resample forward, read the shift in the outcome across `k`.
Prefixes are truncations of a real trace, seeds vary per resample, and the chat
template is rendered client-side.

The measure is not either paper's. The outcome here is one bit, so the module
computes a difference of proportions:

    importance(S_i) = P(odd | S_1..S_i) - P(odd | S_1..S_i-1)

Three differences from the papers, in increasing order of how much they matter.

**1. KL replaced by a difference of proportions. Fine.** KL over a multiclass
answer distribution collapses to a comparison of two numbers when the outcome is
binary. Nothing is lost and the module's docstring says so.

**2. No dissimilarity filter, so this is TA's resampling importance, not its
counterfactual importance.** The module's docstring says the binary outcome
"needs none of the paper's embedding or KL machinery", which is right about the
KL and wrong about the embeddings. The filter has nothing to do with how many
outcome classes there are. It exists because a resample that happens to
reproduce the original sentence tells you nothing about that sentence, and both
papers therefore treat the unfiltered quantity as the weaker measure. This
project reports the weaker one.

**3. No resilience or counterfactual++.** TB's whole §2.1.2, unimplemented.

## What follows for the claims

The **cumulative curve is unaffected**. `P(odd | first k sentences)` is a
well-defined quantity whatever the papers prefer, and every claim phrased as
"the rate is X at prefix k" stands: the envelope, both anchors, the three-trace
comparison, and the cross-prompt contrast. Those are the load-bearing results and
none of them is a per-sentence attribution.

The **per-sentence decomposition is a lower bound, and biased toward zero**.
`Q1.H8.E1.C6` reports the band as a sawtooth with no single step established at
n=30, and attributes that to thin data and ten comparisons. There is a second
cause, and both papers predict it. Every branch point's resample pool contains
continuations that re-derived the sentence just dropped, and those contribute
zero difference by construction, so every step is attenuated toward zero by an
unmeasured amount. TB's resilience result says this is not a small effect for
reasoning models.

This strengthens `C6`'s conclusion rather than weakening it: the decomposition is
even less trustworthy than the multiple-comparison argument alone implies. It
also means the honest reading of a near-zero step, such as `[14]` at 0 points, is
"not measured", not "this sentence does nothing".

Filtering would need sentence embeddings over the resampled continuations, which
is a real piece of work and not obviously worth it for a one-bit outcome on one
trace. Recording the gap costs nothing and is the alternative.

## Citation state, before and after

Before this note: TREE.md cited TB for the method and TB was absent from
`references/project.bib`; TA sat in the bib flagged "not read in-session; do not
quote" and was cited by no node, despite being the paper the take-home links and
the source of the primitive. Both are now corrected.
