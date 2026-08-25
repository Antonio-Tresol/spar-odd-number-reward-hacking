"""The candidate model slate, and the routing pins that keep a run reproducible.

Two independent things can drift under you on OpenRouter, and closing one does
not close the other:

1. **Which snapshot the alias points at.** `qwen/qwen3.6-27b` is an alias. It
   currently resolves to `qwen/qwen3.6-27b-20260422`, and OpenRouter is free to
   repoint it at a newer checkpoint without notice. Sending the *dated* slug
   pins the weights. This was verified against the live API rather than assumed:
   `qwen/qwen3.6-27b-20260422` is accepted, while `qwen/qwen3.6-27b-20200101`
   and `qwen/qwen3.6-27b-notadate` are both rejected with "is not a valid model
   ID". A bogus suffix failing is what makes the real one meaningful — if every
   suffix were silently normalised to the alias, dated pinning would be theatre.

2. **Which provider and quantization serve the call.** One model id is served by
   up to 18 independent endpoints at fp4, fp8, bf16, fp16, or undisclosed
   precision. `google/gemma-4-31b-it` alone spans all four. For a behaviour that
   turns on a single parity decision, quantization is not a detail to average
   over. `Candidate.provider` holds an endpoint *tag* (`novita/bf16`), which
   names the provider and the quantization together, and OpenRouter accepts
   tags in `provider.order`. Some providers do not publish a quantization at
   all, in which case the tag is a bare slug (`alibaba`) and the precision is
   simply unknown — see `LADDER_QUANTIZATION` for why the ladder avoids those.

## Pinning the ladder

The three Qwen 27Bs share an identical parameter count, so they differ only in
post-training — which is what makes them a usable RL-generation ladder, and
what a careless pin would destroy. Their individually-best endpoints were
`novita/bf16`, `deepinfra/fp8` and `akashml/bf16`: three providers at two
precisions, so a rung-to-rung difference could have been generation, provider,
or number format, with no way to tell which.

Holding the *provider* fixed is the stronger control — it pins the serving
stack, batching and sampler, not just the number format. It was tried and does
not work here. Exactly two providers serve all three rungs: Phala reports 0%
uptime on 3.5, and Alibaba returns a persistent upstream 429 on 3.6
("temporarily rate-limited upstream"), failing two of three rungs on a
one-rollout smoke test. That failure is `allow_fallbacks=False` working as
intended — without it those rollouts would have come back healthy-looking from
some other endpoint.

So the ladder fixes quantization at fp8, which every rung supports together
with `seed`, and lets the provider vary. Of the two available confounds this is
the one to accept: number format is the more plausible route to shifting a
near-even parity choice. It still gets two of three rungs onto one provider,
since DeepInfra serves both 3.5 and 3.6 at fp8. **The residual confound, which
every rung-to-rung comparison must report: 3.8 is served by Parasail.** All
three pins were smoke-tested live before being written down.

`build_routing_body()` sets `allow_fallbacks=False` so an unavailable pin is a loud error
rather than a silent reroute — confirmed: pinning a tag that does not serve a
model raises `NotFoundResponseError: No endpoints found`. `require_parameters`
extends the same contract to parameters, so a provider that would quietly ignore
`seed` is refused instead of used.

None of that makes a hosted rollout replayable token-for-token: at
`temperature=1.0` on a continuously batched endpoint, `seed` is best-effort.
What pinning buys is that the *distribution* being sampled is the same one next
week — which is what the gaming rate and its interval are estimates of.

Slate provenance: OpenRouter's `/models` and `/models/{id}/endpoints`, and the
`neuronpedia/jacobian-lens` file tree, all read on 2026-08-24. See
`notes/model-selection.md` for the full derivation and the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

#: Quantization held constant across the three Qwen 27B rungs. See "Pinning the
#: ladder" in the module docstring for the two provider-fixed designs that were
#: tried first and why both failed.
LADDER_QUANTIZATION: Final[str] = "fp8"

#: Sent as `reasoning` on every call. `enabled` is explicit rather than left to
#: the provider default because the default is not uniform: `gemma-4-31b-it`
#: reports `default_enabled=False`, so an unset call returns no chain of thought
#: at all — and a silently empty `reasoning` field would read as "this model
#: does not verbalise" rather than "we forgot to ask".
REASONING_ENABLED: Final[dict[str, Any]] = {"enabled": True}


@dataclass(frozen=True, slots=True)
class Candidate:
    """One model on the slate, pinned.

    snapshot:   the dated slug actually sent as `model`. Pins the weights.
    provider:   the endpoint tag sent in `provider.order`. Pins who serves it
                and at what precision.
    lens:       HuggingFace repo path of a pre-fitted Jacobian lens, or None.
    lens_ckpt:  the checkpoint that lens was fitted on. A lens fitted on base
                weights does not transfer to the instruct model, so this is
                recorded separately rather than assumed to match `hf_id`.
    lens_ckpt_source: the artefact that establishes `lens_ckpt`, or "" when
                nothing does. Only a lens whose source was actually read counts
                as matching — see `lens_matches_served_weights`.
    effort:     reasoning effort, when the model exposes levels at all. Left
                None where it does not — see `notes/model-selection.md` for why
                no common level exists across the slate.
    """

    slug: str
    snapshot: str
    provider: str
    hf_id: str
    params_b: float
    quantization: str
    lens: str | None = None
    lens_ckpt: str | None = None
    lens_ckpt_source: str = ""
    effort: str | None = None
    note: str = ""

    @property
    def lens_matches_served_weights(self) -> bool:
        """Whether the lens is *known* to be fitted on the checkpoint we serve.

        Requires `lens_ckpt_source`: a lens whose provenance nobody read is not
        a match, it is an unknown. Writing `lens_ckpt == hf_id` from a plausible
        directory name and then testing that they are equal proves only that the
        same string was typed twice — and gemma-4 is the standing proof that the
        assumption fails in practice.
        """
        return (
            self.lens is not None and bool(self.lens_ckpt_source) and self.lens_ckpt == self.hf_id
        )


# Tier 1 — dense, single-GPU-hostable, and the reason the slate exists: these
# are the models where an OpenRouter screen can graduate to activation access.
TIER1: Final[tuple[Candidate, ...]] = (
    Candidate(
        slug="qwen/qwen3.6-27b",
        snapshot="qwen/qwen3.6-27b-20260422",
        provider="deepinfra/fp8",
        hf_id="Qwen/Qwen3.6-27B",
        params_b=27.78,
        quantization=LADDER_QUANTIZATION,
        lens="neuronpedia/jacobian-lens/qwen3.6-27b",
        lens_ckpt=None,
        lens_ckpt_source="",
        note=(
            "Official pre-fitted lens, credited to an Anthropic interpretability "
            "author — but the directory holds only a CREDIT.md and the .pt, with "
            "no config.yaml naming the checkpoint it was fitted on, so the match "
            "to the served weights is unverified. Confirm by loading before any "
            "readout is trusted. No bf16 endpoint exists at any provider for this "
            "model, so a self-hosted follow-up would run at a precision the screen "
            "cannot match regardless of which endpoint is pinned."
        ),
    ),
    Candidate(
        slug="qwen/qwen3.8-27b",
        snapshot="qwen/qwen3.8-27b-20260814",
        provider="parasail/fp8",
        hf_id="Qwen/Qwen3.8-27B",
        params_b=27.78,
        quantization=LADDER_QUANTIZATION,
        lens="eyes-ml/Qwen3.8-27B_jacobian-lens",
        lens_ckpt=None,
        lens_ckpt_source="",
        effort=None,
        note=(
            "Newest open-weights reasoning model on the slate (2026-08-14), and the "
            "only 27B Qwen with a bf16 endpoint anywhere (`akashml/bf16`) if the "
            "ladder is ever abandoned for a single-model dive. The one rung not "
            "served by DeepInfra, so it carries the ladder's provider confound. "
            "Community lens rather than the Neuronpedia collection, and its "
            "provenance does not check out: the README claims `Qwen/Qwen3.8-27B` "
            "while the fit command it prints names `eyes-ml/Qwen3.8-27B`. Treat "
            "as unverified until resolved. Catalogue "
            "default effort is xhigh — the only slate member whose default is "
            "not the provider's own."
        ),
    ),
    Candidate(
        slug="qwen/qwen3.5-27b",
        snapshot="qwen/qwen3.5-27b-20260224",
        provider="deepinfra/fp8",
        hf_id="Qwen/Qwen3.5-27B",
        params_b=27.78,
        quantization=LADDER_QUANTIZATION,
        lens="neuronpedia/jacobian-lens/qwen3.5-27b",
        lens_ckpt="Qwen/Qwen3.5-27B",
        lens_ckpt_source="jlens/Salesforce-wikitext/config.yaml (hf_model_name)",
        note=(
            "Identical parameter count to 3.6 and 3.8, so the three form an "
            "RL-generation ladder at fixed architecture — the cleanest read "
            "available on whether post-training, not scale, drives the behaviour. "
            "Oldest rung, and the cheapest of the three at $1.56/Mout."
        ),
    ),
    Candidate(
        slug="google/gemma-4-31b-it",
        snapshot="google/gemma-4-31b-it-20260402",
        provider="novita/bf16",
        hf_id="google/gemma-4-31B-it",
        params_b=31.27,
        quantization="bf16",
        lens="neuronpedia/jacobian-lens/gemma-4-31b",
        lens_ckpt="google/gemma-4-31B",
        lens_ckpt_source="jlens/Salesforce-wikitext/config.yaml (hf_model_name)",
        note=(
            "Deepest bf16 supply on the slate (four endpoints). But the pre-fitted "
            "lens config names `google/gemma-4-31B` — the *base* model — so the "
            "lens does not transfer to the served instruct weights and would have "
            "to be re-fitted. Reasoning is off by default here."
        ),
    ),
)

# Tier 2 — screening breadth. Neither is a self-hosting target: gpt-oss-20b is a
# previous-generation reference point, and deepseek-v4-flash is a 291B MoE.
TIER2: Final[tuple[Candidate, ...]] = (
    Candidate(
        slug="openai/gpt-oss-20b",
        snapshot="openai/gpt-oss-20b",
        provider="deepinfra/bf16",
        hf_id="openai/gpt-oss-20b",
        params_b=20.91,
        quantization="bf16",
        lens="neuronpedia/jacobian-lens/gpt-oss-20b",
        lens_ckpt=None,
        lens_ckpt_source="",
        effort="medium",
        note=(
            "Cheapest bf16 endpoint anywhere on the slate, mandatory reasoning, and "
            "the only member whose alias is already its own canonical slug. Serves "
            "as the previous-generation anchor for the RL-generation comparison."
        ),
    ),
    Candidate(
        slug="deepseek/deepseek-v4-flash",
        snapshot="deepseek/deepseek-v4-flash-20260423",
        provider="deepinfra/fp8",
        hf_id="deepseek-ai/DeepSeek-V4-Flash",
        params_b=290.94,
        quantization="fp8",
        lens="neuronpedia/jacobian-lens/deepseek-v4-flash",
        lens_ckpt=None,
        lens_ckpt_source="",
        effort="high",
        note=(
            "Has an official lens, but 291B of MoE puts self-hosting out of reach "
            "for this project, and no provider serves it above fp8. Screening arm "
            "only. Reasoning effort levels are xhigh/high — it cannot go lower."
        ),
    ),
)

SLATE: Final[tuple[Candidate, ...]] = TIER1 + TIER2

BY_SLUG: Final[dict[str, Candidate]] = {c.slug: c for c in SLATE}


def build_routing_body(provider_tag: str) -> dict[str, Any]:
    """The `provider` body that pins one endpoint and refuses substitutes.

    `allow_fallbacks=False` turns an unavailable pin into an error instead of a
    silent reroute to a different provider at a different precision.
    `require_parameters=True` does the same for parameters: a provider that
    would drop `seed` is excluded rather than used, so the results file never
    claims a seed that was never applied.
    """
    return {
        "order": [provider_tag],
        "allow_fallbacks": False,
        "require_parameters": True,
    }


def resolve_candidate(slug: str) -> Candidate:
    """Look up a slate member, listing the alternatives when the name is wrong.

    Raises:
        KeyError: when `slug` is not on the slate. Unpinned models are refused
            rather than passed through, because an un-pinned run produces a
            results file that cannot be compared against a pinned one.
    """
    try:
        return BY_SLUG[slug]
    except KeyError:
        known = "\n  ".join(c.slug for c in SLATE)
        raise KeyError(
            f"{slug!r} is not on the pinned slate. Known models:\n  {known}\n"
            "Add it to candidates.py with a snapshot and a provider tag "
            "(`uv run odd-number endpoints <slug>` lists the tags)."
        ) from None
