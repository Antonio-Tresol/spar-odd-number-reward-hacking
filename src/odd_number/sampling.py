"""Sampling parameters: explicit, recorded, and identical across the ladder.

`temperature=1.0` used to be a literal buried in the function that made the API
call, and `top_p` / `top_k` / `max_tokens` were not sent at all. Both halves of
that are problems, and the second is the worse one.

**Unsent is not neutral.** A parameter this project does not send falls back to
whatever the *provider* defaults to, and providers do not agree. The Qwen ladder
is pinned to DeepInfra for two rungs and Parasail for the third precisely so the
rungs stay comparable; leaving `top_p` and `top_k` unsent hands that seam back to
two independent vendors' defaults. Sending every sampling parameter explicitly
is what makes the request identical across rungs.

**A value that is not recorded did not happen.** The gaming rate is an estimate
of a distribution, and the sampling parameters *are* that distribution. A results
file that does not carry them cannot be compared with one collected after someone
edited a literal — which is the same failure the model snapshot and provider pins
exist to prevent, except self-inflicted and with no API to catch it. So every
`Rollout` records the settings it was drawn under.

## Why max_tokens is set high

The asymmetry sets the value. Tokens are billed as generated, so a cap that is
never reached costs exactly nothing — but a cap that *is* reached costs a data
point: the rollout comes back `finish_reason="length"`, and `grades.py` correctly
refuses to parse a severed trace, so the answer is lost after being paid for. A
cheap ceiling and an expensive floor means erring high.

32,768 is roughly 12x the longest trace observed while building the pipeline
(2,773 tokens, deepseek-r1 under the conflicting grader; 2,406 for qwen3.8-27b),
and sits under the tightest ceiling on the ladder — OpenRouter reports
`max_completion_tokens` of 65,536 for qwen3.5-27b, 81,920 for qwen3.6-27b and
131,072 for qwen3.8-27b, so the same value is accepted by every rung. It remains
a runaway guard: unbounded generation against a reasoning model at `xhigh` effort
is how a screening run turns into a bill.

**Why 1.0 and not 0.** Temperature 0 would make each rollout the model's modal
answer repeated *n* times, and the gaming rate would collapse to 0% or 100% with
no information in between. This experiment measures how often the model picks an
odd number, which is a property of its output distribution, so the distribution
has to be sampled as it is. 1.0 is also the API default, which keeps the
replication honest to the setting the source post describes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Final

#: Generation ceiling. See "Why max_tokens is set high" above.
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
