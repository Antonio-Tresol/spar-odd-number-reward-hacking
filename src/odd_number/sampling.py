"""Sampling parameters: explicit, recorded, and identical across the ladder.

Every parameter is sent on every call, because an unsent parameter falls
back to the *provider's* default and the ladder spans two providers; and
every rollout records the values it was drawn under, because the gaming rate
is an estimate of a distribution and these parameters are that distribution.

`temperature=1.0`: the rate is a property of the output distribution, so it
is sampled as it is — temperature 0 would collapse it to 0% or 100%. It is
also every vendor's thinking-mode recommendation
(`notes/sampling-recommendations.md`); where the project deviates from the
vendors is `top_p=1.0` with `top_k` off.

`MAX_TOKENS=32_768`: an unreached cap costs nothing and a reached cap loses a
paid-for data point (`grades.py` refuses a severed trace), so the ceiling
errs high while still guarding against runaway generation. It sits under
every Qwen rung's `max_completion_tokens` (65,536 / 81,920 / 131,072); Kimi
K3's endpoint caps at 16,384 and needs `--max-tokens 16384`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Final

#: Generation ceiling; the module docstring has the reasoning.
MAX_TOKENS: Final[int] = 32_768


@dataclass(frozen=True, slots=True)
class SamplingParams:
    """One sampling configuration, sent in full and recorded in full.

    temperature: 1.0 samples the model's own distribution — see the module
                 docstring for why 0 would destroy the measurement.
    top_p:       1.0 disables nucleus truncation. Unambiguous across providers.
    top_k:       0 by default, the vLLM convention for "disabled". **This is an
                 assumption, not a confirmed fact**: it was checked only far
                 enough to know the pinned endpoints accept it and still return
                 normal-length output, so it is certainly not being read as a
                 literal cap of zero tokens. Whether DeepInfra and Parasail both
                 read it as "disabled" is unverified. Set to None to omit the
                 parameter instead — which trades a stated assumption for an
                 unstated provider default, so neither option is free.
    max_tokens:  bounded generation; see MAX_TOKENS.
    """

    temperature: float = 1.0
    top_p: float = 1.0
    top_k: int | None = 0
    max_tokens: int = MAX_TOKENS

    def as_request_kwargs(self) -> dict[str, Any]:
        """The keyword arguments to pass to `chat.send`.

        `top_k` is dropped when None so that "omit the parameter" is expressible;
        every other field is always sent.
        """
        kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        if self.top_k is not None:
            kwargs["top_k"] = self.top_k
        return kwargs

    def as_record(self) -> dict[str, Any]:
        """The settings as they go into the results file, verbatim."""
        return asdict(self)


#: What every rollout uses unless a CLI flag overrides it. Named rather than
#: inlined so a results file can say which preset it was drawn under, and so
#: changing it is a visible edit to a constant rather than to a call site.
DEFAULT_SAMPLING: Final[SamplingParams] = SamplingParams()
