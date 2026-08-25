# Model selection and routing pins (2026-08-24/25)

Evidence for `Q1.H7.E2` — the model-selection sweep. Answers two questions the
project has to settle before spending any budget:

1. Which open-weights reasoning models are worth screening, given that the plan
   is to graduate the survivors to self-hosted activation access (J-lens / NLA)?
2. How do we stop OpenRouter moving the underlying model between runs?

Everything below is read from live APIs during the session, not recalled. The
session spanned midnight UTC, so reads are dated 2026-08-24/25.

Retrieval trail:

- `https://openrouter.ai/api/v1/models` — 418 models, 168 with a
  `hugging_face_id` (the open-weights signal), 104 of those with a `reasoning`
  block.
- `https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints` — per-provider
  quantization, `supported_parameters`, uptime, price.
- `https://huggingface.co/api/models/neuronpedia/jacobian-lens/tree/main` — the
  pre-fitted Jacobian lens collection, 39 model directories.
- `https://huggingface.co/api/models?search=…` — NLA and third-party lens repos.
- `https://github.com/anthropics/jacobian-lens`,
  `https://transformer-circuits.pub/2026/nla/`,
  `https://transformer-circuits.pub/2026/workspace/index.html`.

## The two drift axes, and which one people forget

**Axis 1 — the alias moves.** `qwen/qwen3.6-27b` is an alias. Its
`canonical_slug` today is `qwen/qwen3.6-27b-20260422`, and nothing stops
OpenRouter repointing it. Every slate member except `openai/gpt-oss-20b` has a
canonical slug that differs from its alias.

Sending the dated slug pins the weights, and the dated slug is a real routing
target rather than a cosmetic suffix. Tested directly:

| model sent | result |
|---|---|
| `qwen/qwen3.6-27b-20260422` | accepted |
| `qwen/qwen3.6-27b-20200101` | `BadRequestResponseError: … is not a valid model ID` |
| `qwen/qwen3.6-27b-notadate` | `BadRequestResponseError: … is not a valid model ID` |

The rejections are the informative rows. An API that normalised any suffix back
to the alias would have accepted the first row too, and dated pinning would have
been theatre. Note the dated slugs are *not* listed as separate ids in
`/models`, so they can only be discovered through `canonical_slug`.

**Axis 2 — the provider and precision move.** A single model id is served by up
to 18 independent endpoints. `google/gemma-4-31b-it` is served at fp4, fp8,
bf16 and fp16 by different providers at the same time. Providers also disagree
about parameters: of the 17 endpoints serving `deepseek/deepseek-v4-flash`, six
do not accept `seed`.

`provider={"order": [tag], "allow_fallbacks": false, "require_parameters": true}`
pins both provider and quantization, because the endpoint `tag` names them
together (`novita/bf16`). Both flags were tested in the direction that matters —
that they *refuse* rather than silently comply:

- **`allow_fallbacks: false`** — requesting `qwen/qwen3.6-27b` via
  `parasail/fp8`, which does not serve it, raised `NotFoundResponseError: No
  endpoints found` rather than rerouting.
- **`require_parameters: true`** — `siliconflow/fp8` serves `qwen3.6-27b` but
  reports `seed: false`. With the flag set the call is refused with "No
  endpoints found"; with it unset the *same pin serves normally*. So the flag is
  what stops a results file recording a seed that was never applied.

**Verifying the pin held needs one header.** The SDK's typed chat response drops
the `provider` field the raw API returns — `ChatResult.model_dump()` yields only
`choices, created, id, model, object, service_tier, system_fingerprint, usage` —
and the `model` it echoes is the alias, not the dated slug that was sent.

The fix is not a second API call. `x_open_router_metadata="enabled"`, off by
default, makes the same response carry `openrouter_metadata`: a structured
`EndpointInfo(model, provider, selected)` for the endpoint that served it, plus
the routing strategy and the cost. So every rollout records its own provenance
inline, at no extra call and no extra latency.

This replaced an earlier design that fetched `GET /generation?id=` per rollout
into an append-only sidecar. That worked, but cost an extra call each and lagged
about eight seconds before a generation became queryable (four consecutive 404s
at 2s intervals in testing). It is recorded here because the reasoning that led
to it was sound given what was known — the SDK really does drop `provider` — and
the thing that made it unnecessary was a request flag, not a better idea.

End-to-end check on all three ladder rungs, two rollouts each. Every generation
record returned the pinned provider and the dated slug that was sent:

| sent | pinned | `provider_name` | `model` returned |
|---|---|---|---|
| `qwen/qwen3.5-27b-20260224` | `deepinfra/fp8` | DeepInfra | `qwen/qwen3.5-27b-20260224` |
| `qwen/qwen3.6-27b-20260422` | `deepinfra/fp8` | DeepInfra | `qwen/qwen3.6-27b-20260422` |
| `qwen/qwen3.8-27b-20260814` | `parasail/fp8` | Parasail | `qwen/qwen3.8-27b-20260814` |

`routing_strategy` is checked too: `allow_fallbacks=False` should make a reroute
impossible, so anything other than `direct` means an assumption this project
relies on has stopped holding, even if the endpoint still matches.

Evidence: `results/ladder-smoke-*.jsonl`.

## The slate

Selection criteria, in the order they bind:

1. **Post-RL reasoning model returning readable `reasoning.text`** — the
   forensics protocol starts by reading the CoT, and a provider summary is not a
   CoT.
2. **A Jacobian lens whose source checkpoint was read and matches**, or a
   checkpoint we could fit one for. "A lens directory exists with the right
   name" is not this criterion — see "Lens provenance is unreliable" below.
3. **Self-hostable on a single node** — otherwise activation access is out of
   reach and the model is a screening arm only.
4. **A precision that can be held constant across the comparison.** This was
   originally written as "bf16 available on OpenRouter", so that the screen and
   a self-hosted follow-up would match. Running the three Qwens as a ladder
   inverts the priority: an uncontrolled difference *inside* the comparison is
   worse than a known offset between the screen and a later self-host, because
   only the first one is mistakable for a result. See "Pinning the ladder".

### Tier 1 — screen, then self-host

| model | snapshot | params | pinned endpoint | J-lens provenance |
|---|---|---|---|---|
| `qwen/qwen3.5-27b` | `-20260224` | 27.78B dense | `deepinfra/fp8` | **verified match** |
| `qwen/qwen3.6-27b` | `-20260422` | 27.78B dense | `deepinfra/fp8` | unverified — no config |
| `qwen/qwen3.8-27b` | `-20260814` | 27.78B dense | `parasail/fp8` | unverified — self-contradictory |
| `google/gemma-4-31b-it` | `-20260402` | 31.27B dense | `novita/bf16` | **verified mismatch (base)** |

All four are Apache-2.0 and ungated on HuggingFace.

The three Qwen 27Bs report an **identical parameter count** (27,781,427,952),
i.e. the same architecture across three post-training generations. That is the
cleanest available separation of "post-training caused this" from "scale caused
this", and it is the single strongest reason to prefer this family. All three
are being run as a ladder (decision, 2026-08-25).

### Pinning the ladder: what was tried

A ladder is only a controlled comparison if the rungs differ in one thing. The
per-model best endpoints were `novita/bf16`, `deepinfra/fp8` and `akashml/bf16`
— three providers at two precisions, so a rung-to-rung difference could have
been generation, provider, or number format.

Holding the **provider** fixed is the stronger control, since it also fixes the
serving stack, batching and sampler. Exactly two providers serve all three
rungs, and neither works:

- **Phala** — reports 0% uptime on `qwen3.5-27b`.
- **Alibaba** — looked ideal on paper (seed on all three, 99.7/100/100% uptime,
  cheapest on two, Qwen's own first-party deployment). A one-rollout smoke test
  failed on two of three rungs: `qwen3.6-27b` returned a persistent upstream
  429, `"qwen/qwen3.6-27b is temporarily rate-limited upstream"`, which
  `allow_fallbacks: false` correctly refused to route around. This is the pin
  design working: a silent reroute would have produced usable-looking rollouts
  from a different endpoint.

So the ladder holds **quantization** fixed at fp8 instead — supported with
`seed` on all three rungs — and lets the provider vary. Of the two available
confounds this is the one to accept: number format is the more plausible route
to shifting a near-even parity choice. It also still gets two of three rungs
onto one provider, since DeepInfra serves both 3.5 and 3.6 at fp8. **The
residual confound to report: 3.8 is served by Parasail, the other two by
DeepInfra.**

Cost of the fp8 choice: `qwen3.8-27b` has the slate's only 27B bf16 endpoint
(`akashml/bf16`), unused under this design. A later single-model deep dive that
cares about screen-to-self-host transfer should switch to it.

### Tier 2 — screening breadth, not self-hosting

| model | snapshot | params | pinned endpoint | why not Tier 1 |
|---|---|---|---|---|
| `openai/gpt-oss-20b` | (alias is canonical) | 20.91B MoE | `deepinfra/bf16` | previous generation; cheapest bf16 on the slate at $0.14/Mout |
| `deepseek/deepseek-v4-flash` | `-20260423` | 290.94B MoE | `deepinfra/fp8` | 291B puts self-hosting out of reach; no provider serves it above fp8 |

`deepseek/deepseek-v4-flash` is the model named in the original direction note.
It keeps a place as a screening arm — it has an official lens and is cheap — but
it cannot be the activation-access target here.

## Three constraints found while doing this

**Lens provenance is unreliable, and only one slate lens actually checks out.**
Each pre-fitted lens directory *may* contain a `config.yaml` recording the
checkpoint it was fitted on. Reading them, rather than trusting the directory
name, changes the picture completely:

| lens | what its own artefacts say | verdict |
|---|---|---|
| `.../qwen3.5-27b` | `config.yaml` → `hf_model_name: "Qwen/Qwen3.5-27B"` | **verified match** |
| `.../gemma-4-31b` | `config.yaml` → `hf_model_name: "google/gemma-4-31B"` | **verified mismatch** — base, not the served `-it` |
| `.../qwen3.6-27b` | no config at all; only a `CREDIT.md` and the `.pt` | unverified |
| `eyes-ml/Qwen3.8-27B_jacobian-lens` | README says `Qwen/Qwen3.8-27B`, its own printed fit command says `eyes-ml/Qwen3.8-27B` | unverified, self-contradictory |

The gemma case is the proof that this is not pedantry: a lens fitted on base
weights does not transfer to the instruct checkpoint, and nothing in the
directory name warns you. So `Candidate.lens_matches_served_weights` requires a
`lens_ckpt_source` naming the artefact that was actually read — a lens whose
provenance nobody checked is an unknown, not a match. `test_pinning.py` pins
both the gemma mismatch and the rule itself, so the check cannot be satisfied
by typing the expected checkpoint into the field being tested.

Consequence for the plan: **only `qwen3.5-27b` currently has a lens that can be
trusted without further work.** For 3.6 and 3.8 the options are to confirm by
loading, or to re-fit — which the gemma config shows costs 1000 wikitext prompts
on a single GPU.

The same config gives the cost of re-fitting, which is reassuringly small: 1000
wikitext-103 prompts at `max_seq_len 128`, `bfloat16`, on a single B200, and it
converged after 861. Fitting a lens for any 27–31B model on the slate is a
modest job, not a blocker. This is why lens availability ranks *below* bf16
availability in the criteria — a lens we can create, a bf16 endpoint we cannot.

**There is no reasoning-effort level common to the slate.** `qwen3.8-27b`
exposes `xhigh/medium/low`, `gpt-oss-20b` exposes `high/medium/low`,
`deepseek-v4-flash` exposes only `xhigh/high`, and `qwen3.6-27b`,
`qwen3.5-27b` and `gemma-4-31b-it` expose no levels at all. Since reasoning
*length* is one of the two headline measures, effort cannot be equalised across
models — it can only be recorded. `Rollout.reasoning_effort` carries whatever
was requested, and the generation record carries `native_tokens_reasoning` as
the measured outcome. Any cross-model length comparison has to say so out loud.

**`gemma-4-31b-it` has reasoning off by default** (`default_enabled: false`).
An unset call returns no chain of thought, which would read as "this model does
not verbalise" rather than "we did not ask". Every call now sends
`reasoning={"enabled": true}` explicitly.

## NLAs are not available for these models

The user's plan named "J-lens or NLAs". Only the first is live.

Public NLA artefacts are `kitft/nla-qwen2.5-7b-L20-{av,ar}` (the reference
release, ~1.9k downloads) and `minnesotanlp/nla-qwen3-4b-L24-*`, plus assorted
small community forks on Qwen2.5-0.5B/1.5B/3B. Every one targets a
**pre-2026 checkpoint**, so none is a current-generation RLVR reasoning model —
which is precisely the property criterion 1 selects for.

Training one is out of budget: per the NLA paper, "NLA training requires joint
RL on two full language models, and inference requires generating several
hundred tokens per activation".

Worth weighing against dropping NLA entirely: the NLA paper's headline
application was a pre-deployment audit that surfaced *unverbalized evaluation
awareness* — a model believing, but not saying, that it was being evaluated.
That is `Q1.H6` (aware reward-seeking) and `Q1.H4` (metagaming: the model reads
the setting as a test of its strategic ability) almost verbatim. If the CoT read
comes back ambiguous on awareness, a legacy NLA arm on Qwen2.5-7B may be worth
more than its staleness costs — as a methods demonstration, not as evidence
about a current model.

## Costs

Per-rollout completion price at the pinned endpoints, in $/M output tokens:
`gpt-oss-20b` 0.14, `deepseek-v4-flash` 0.18, `gemma-4-31b-it` 0.40,
`qwen3.5-27b` 2.60, `qwen3.6-27b` 3.20, `qwen3.8-27b` 3.20. Observed reasoning
on `qwen3.6-27b` was 1153 tokens under conflict and 699 under agreement, so at
n=40 per arm a single Qwen model costs roughly $0.25. The whole six-model slate
at n=40 per arm is well under $2 — cost is not a constraint on this design, and
should not be used to justify shrinking n.

## Two things checked because they looked wrong

**The `qwen3.8-27b` answers looked truncated.** Its smoke responses came back as
`'

1'` and `'

4'`, which would be alarming if Parasail were cutting
generations short while DeepInfra was not — differential truncation on the one
rung served by a different provider. All six smoke rollouts carry
`finish_reason: "stop"`, and the 3.8 conflict arm ran to 2342 completion tokens,
so nothing was cut. The model simply answered `1`. At n=1 that is not evidence
of anything, but it is a real answer rather than a parsing artefact.

**`qwen3.5-27b` failed once on Alibaba** with `BadRequestResponseError` before
the repin, and that failure is unexplained. It is not attributed to the 429
story: it did not recur, and the rung has since run clean twice through
`collect` on `deepinfra/fp8` — the pin actually in use, with no `max_tokens` set
and 2006 completion tokens on one arm. Recorded rather than explained away.

## Caveat to carry forward

`seed` is pinned and recorded, but at `temperature=1.0` on a continuously
batched endpoint it is best-effort at most. No claim should rest on per-rollout
replay. The reproducibility that carries evidence here is **distributional** —
n rollouts and an interval — which is exactly what the pins protect: not that
the same tokens come back, but that the same distribution is being sampled next
week.
