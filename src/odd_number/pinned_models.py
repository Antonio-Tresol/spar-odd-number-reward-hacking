"""Every model the project calls, pinned on both axes that drift on OpenRouter.

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
   over. `PinnedModel.provider` holds an endpoint *tag* (`novita/bf16`), which
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

The same "No endpoints found" also fires when `max_tokens` exceeds the pinned
endpoint's `max_completion_tokens` — OpenRouter filters the endpoint out
rather than reporting the cap. Kimi K3 on DeepInfra (cap 16,384) failed
three rollouts in a row this way at the default 32,768 before the cause was
found with a 64-token probe. Check `odd-number endpoints <slug>` caps before
blaming the pin.

None of that makes a hosted rollout replayable token-for-token: at
`temperature=1.0` on a continuously batched endpoint, `seed` is best-effort.
What pinning buys is that the *distribution* being sampled is the same one next
week — which is what the gaming rate and its interval are estimates of.

Provenance of the pinned set: OpenRouter's `/models` and `/models/{id}/endpoints`, and the
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
class PinnedModel:
    """A model fixed to one snapshot and one endpoint, so a run can be re-run.

    The models under study and the judge are all `PinnedModel`s; the type says how
    the model is addressed, not what role it plays in an experiment.

    snapshot:   the dated slug actually sent as `model`. Pins the weights.
    hf_id:      the HuggingFace repo of the served weights, or None when the
                vendor publishes none — an API-only model is screenable but
                can never graduate to activation access.
    params_b:   parameter count in billions, or None when the vendor does not
                publish one. Never a placeholder number.
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
                no common level exists across the pinned models.
    seed_supported: whether the pinned endpoint accepts `seed`. When False the
                parameter is not sent and the rollout records `seed=None` —
                stated rather than faked, because `require_parameters` would
                otherwise refuse the only endpoint serving the model.
    """

    slug: str
    snapshot: str
    provider: str
    hf_id: str | None
    params_b: float | None
    quantization: str
    lens: str | None = None
    lens_ckpt: str | None = None
    lens_ckpt_source: str = ""
    effort: str | None = None
    seed_supported: bool = True
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


# Dense and single-GPU-hostable: the models where an OpenRouter screen can
# graduate to activation access, which is the reason the project pins models
# at all.
HOSTABLE_MODELS: Final[tuple[PinnedModel, ...]] = (
    PinnedModel(
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
    PinnedModel(
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
            "Newest open-weights reasoning model among the pinned models (2026-08-14), and the "
            "only 27B Qwen with a bf16 endpoint anywhere (`akashml/bf16`) if the "
            "ladder is ever abandoned for a single-model dive. The one rung not "
            "served by DeepInfra, so it carries the ladder's provider confound. "
            "Community lens rather than the Neuronpedia collection, and its "
            "provenance does not check out: the README claims `Qwen/Qwen3.8-27B` "
            "while the fit command it prints names `eyes-ml/Qwen3.8-27B`. Treat "
            "as unverified until resolved. Catalogue "
            "default effort is xhigh — the only pinned model whose default is "
            "not the provider's own."
        ),
    ),
    PinnedModel(
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
    PinnedModel(
        slug="google/gemma-4-31b-it",
        snapshot="google/gemma-4-31b-it-20260402",
        provider="novita/bf16",
        hf_id="google/gemma-4-31B-it",
        params_b=31.27,
        quantization="bf16",
        lens="neuronpedia/jacobian-lens/gemma-4-31b",
        lens_ckpt="google/gemma-4-31B",
        lens_ckpt_source="jlens/Salesforce-wikitext/config.yaml (hf_model_name)",
        effort="high",
        note=(
            "Deepest bf16 supply among the pinned models (four endpoints). But the pre-fitted "
            "lens config names `google/gemma-4-31B` — the *base* model — so the "
            "lens does not transfer to the served instruct weights and would have "
            "to be re-fitted. Reasoning is off by default here, and `enabled` "
            "alone does not turn it on: Novita returned 0 reasoning tokens on 80 "
            "rollouts until an effort level was named (probed 2026-08-25: high and "
            "medium both return `reasoning.text`). That effort-less run is kept as "
            "results/odd-number-google-gemma-4-31b-it-no-effort.jsonl."
        ),
    ),
)

# Screening breadth only; none is a self-hosting target. gpt-oss-20b is a
# previous-generation reference point, and deepseek-v4-flash is a 291B MoE.
SCREENING_ONLY_MODELS: Final[tuple[PinnedModel, ...]] = (
    PinnedModel(
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
            "Cheapest bf16 endpoint among the pinned models, mandatory reasoning, and "
            "the only member whose alias is already its own canonical slug. Serves "
            "as the previous-generation anchor for the RL-generation comparison."
        ),
    ),
    PinnedModel(
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
    # Added 2026-08-25 at Antonio's request: the newest GLM, Kimi and MiniMax
    # reasoning models, to widen the screen. None is a self-hosting target.
    PinnedModel(
        slug="z-ai/glm-5.3",
        snapshot="z-ai/glm-5.3-20260816",
        provider="z-ai/fp8",
        hf_id=None,
        params_b=None,
        quantization="fp8",
        seed_supported=False,
        note=(
            "Newest GLM (2026-08-18), API-only: no HuggingFace id, one endpoint "
            "(Z.ai's own, fp8) which does not accept `seed`, so rollouts record "
            "seed=None. The newest open-weights GLM is 5.2 (`zai-org/GLM-5.2`). "
            "Catalogue defaults temperature 1.0, top_p 0.95."
        ),
    ),
    PinnedModel(
        slug="moonshotai/kimi-k3",
        snapshot="moonshotai/kimi-k3-20260715",
        provider="deepinfra/bf16",
        hf_id="moonshotai/Kimi-K3",
        params_b=2800.0,
        quantization="bf16",
        note=(
            "2.8T-parameter open-weights reasoning model (2026-07-16). Pinned to "
            "the one bf16 endpoint with `seed` and >99% uptime. Expensive: "
            "$15/Mout, roughly $5 for an n=40 A/B. Catalogue default top_p 0.95, "
            "temperature unset. DeepInfra caps completions at 16,384 tokens, so "
            "collect with `--max-tokens 16384` — the default 32,768 is refused "
            "as 'No endpoints found'."
        ),
    ),
    PinnedModel(
        slug="minimax/minimax-m3",
        snapshot="minimax/minimax-m3-20260531",
        provider="parasail/fp8",
        hf_id="MiniMaxAI/Minimax-M3",
        params_b=None,
        quantization="fp8",
        note=(
            "Newest MiniMax reasoning model (2026-05-31), open weights, parameter "
            "count not published in the catalogue. Pinned to Parasail fp8 after "
            "two others failed on 2026-08-25: DeepInfra fp8 returned an upstream "
            "429 on three consecutive rollouts, and Novita fp8 served 13 of 80 "
            "rollouts with empty content and the answer glued onto the end of "
            "the reasoning text (`...I'll go with 42.42`) — a think/answer split "
            "bug on that endpoint, kept as results/odd-number-minimax-minimax-m3-"
            "novita.jsonl. Parasail populated content on a 3-call probe. All "
            "three support `seed`. Catalogue defaults temperature 1.0, top_p 0.95."
        ),
    ),
)

PINNED_MODELS: Final[tuple[PinnedModel, ...]] = HOSTABLE_MODELS + SCREENING_ONLY_MODELS

PINNED_MODELS_BY_SLUG: Final[dict[str, PinnedModel]] = {c.slug: c for c in PINNED_MODELS}


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


def resolve_pinned_model(slug: str) -> PinnedModel:
    """Look up a pinned model, listing the alternatives when the name is wrong.

    Raises:
        KeyError: when `slug` is not among the pinned models. Unpinned models are refused
            rather than passed through, because an un-pinned run produces a
            results file that cannot be compared against a pinned one.
    """
    try:
        return PINNED_MODELS_BY_SLUG[slug]
    except KeyError:
        known = "\n  ".join(c.slug for c in PINNED_MODELS)
        raise KeyError(
            f"{slug!r} is not a pinned model. Known models:\n  {known}\n"
            "Add it to pinned_models.py with a snapshot and a provider tag "
            "(`uv run odd-number endpoints <slug>` lists the tags)."
        ) from None
