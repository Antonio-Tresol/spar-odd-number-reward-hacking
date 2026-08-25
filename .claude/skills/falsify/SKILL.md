---
name: falsify
description: Plan and execute scientific falsification tests for claims — permutation nulls, bootstrap CIs, random-direction controls, distractor discrimination. Use before any claim graduates to survived/weakened/failed and before findings ship in a deliverable; produces the scorecard the research tree links as evidence.
effort: max
---

# Falsification Protocol

Scientific claims survive falsification efforts. That is science. This skill systematically attempts to destroy every claim before it graduates into a deliverable.

A **Failed** verdict is the protocol succeeding, not the research failing: retracting a claim before it ships is the entire point. The scorecard's value is its honesty, not its survival rate — a scorecard where everything survives is more suspicious than one with retractions.

## Workflow

### Step 1: Identify claims
Read the target document ($ARGUMENTS or the most recent findings report). Extract every testable claim as a numbered list.

### Step 2: Design falsification tests
For each claim, design at least one test that could destroy it:

- **Statistical claims** → permutation null, bootstrap CI, effect size vs random baseline
- **"X is different from Y"** → is the difference distinguishable from noise? Random split null.
- **"X causes Y"** → random direction control (does a random intervention also produce the effect?)
- **"N dimensions needed"** → random baseline (how many dims do random vectors need?)
- **"Cluster structure"** → stability across methods (Ward vs complete vs single linkage)
- **Small-n claims** → subsample instability (what happens at n=4?)
- **Sweeping claims** → multiple comparisons correction. Was the "best" parameter pre-registered?
- **Scorer-based claims** → test-retest reliability of the scorer
- **Qualitative labels / interpretations** ("this feature means X", "this circuit does Y") → **discrimination against a matched distractor.** A label that also fits an unrelated unit explains nothing, and detection-style scoring is blind to this: published feature-label sets have been shown to be riddled with collisions where one description matches many distinct units. Test: given the label and two candidates (the real one and a random other), can a scorer pick the right one above chance? Report recall *and* selectivity, never recall alone.
- **"My method finds X" claims** → **plant or borrow a ground truth and run blind.** The strongest validation design that still scales to a short project: hide a known answer, apply the method without looking, report what it recovered *and* how many false positives it produced out of the full candidate set.

### Step 3: Prioritize by destructive potential
Order tests by: which test, if it succeeds, destroys the most important claim?

### Step 4: Implement and run
Write the tests as a single reproducible script. Include:
- Clear logging of each test
- JSON output for programmatic validation
- Random seeds for reproducibility

### Step 5: Report
For each claim, state:
1. The claim
2. The falsification test(s) applied
3. The result: **Survives** / **Weakened** (qualified version) / **Failed** (retracted)
4. If weakened: the qualified version
5. If failed: the corrected finding

### Step 6: Update
Update the source document with qualified claims and a falsification scorecard.

## Worked examples of falsification catches

- **Base-rate artifact caught by permutation test**: two detectors appeared to strongly "co-fire" (high Jaccard overlap), but each fired on ~97% of inputs individually — the expected overlap under independence was already ~0.94. The apparent relationship was nothing beyond base rates. Always check: is the "effect" just what you'd expect from base rates?
- **Bootstrap CI crossing zero**: a "near-orthogonal" cosine-similarity claim had a bootstrap CI of roughly [-0.32, 0.64] — consistent with everything from mild anti-alignment to substantial alignment. The point estimate carried no information; the claim was retracted.
- **Borderline p-value**: a random-split null gave p = 0.054 — reported as borderline, neither dressed up as significant nor dismissed as null. Borderline stays borderline in the writeup.

$ARGUMENTS
