"""Every model the project calls, pinned on both axes that drift on OpenRouter.

1. **The snapshot.** `qwen/qwen3.6-27b` is an alias OpenRouter may repoint
   at a newer checkpoint without notice; the dated slug (`…-20260422`) is
   what is sent, and it pins the weights. The API rejects made-up dates, so
   an accepted dated slug is a real pin.
2. **The endpoint.** One model id may be served by many providers at fp4,
   fp8, bf16 or undisclosed precision. `PinnedModel.provider` is an endpoint
   tag (`novita/bf16`) naming provider and quantization together, sent in
   `provider.order` with `allow_fallbacks=False`, so an unavailable pin is a
   loud "No endpoints found" rather than a silent reroute.

The three Qwen 27Bs form an RL-generation ladder at fixed architecture. No
provider serves all three reliably, so the ladder holds quantization fixed
at fp8 (`LADDER_QUANTIZATION`) and lets the provider vary; the residual
confound — 3.8 on Parasail, 3.5 and 3.6 on DeepInfra — is `Q1.H7.E2.C5`
and must be reported with every rung comparison.

Two traps. "No endpoints found" also fires when `max_tokens` exceeds an
endpoint's `max_completion_tokens` (Kimi K3 on DeepInfra caps at 16,384);
check `odd-number endpoints <slug>` before blaming the pin. And `seed` is
best-effort at temperature 1.0 on a batched endpoint: pinning fixes the
*distribution* sampled, not the tokens.

Derivation and numbers: `notes/model-selection.md` (catalogue read
2026-08-24).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

#: Quantization held constant across the three Qwen 27B rungs. The two
#: provider-fixed designs tried first, and why both failed, are under
#: "Pinning the ladder" in `notes/model-selection.md`.
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
    #: Whether this endpoint forwards a `reasoning` field on an *inbound*
    #: assistant message, so a rollout can be replayed with the reasoning it
    #: produced. Verified per endpoint, never assumed: the SDK accepts it
    #: everywhere and most providers drop it silently, which is indistinguishable
    #: from a model that cannot recall. Findings: `notes/interview-protocol.md`.
    replays_reasoning: bool = False
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
        replays_reasoning=True,
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
