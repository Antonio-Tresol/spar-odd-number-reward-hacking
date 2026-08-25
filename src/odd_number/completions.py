"""This project's own completion types, and the parsing that produces them.

`Completion`, `TokenUsage` and `Routing` are what the rest of the package works
with; a `ChatResult` never leaves this module. That is the whole point — the
vendor's shapes stop here, so a change to them breaks one file rather than
every call site.

**Why this exists.** The code this replaces reached into SDK objects with
`getattr(message, "content", None) or ""`. That is not defensive, it is
destructive. The SDK is fully typed — `ChatResult.choices[0].message.content`
is a real field on a real pydantic model — and `getattr` with a default throws
that away in the worst possible direction: if the vendor renames `content`, the
call does not fail, it returns `""`, and the run records hundreds of rollouts
with empty responses that look exactly like refusals. A grader downstream then
scores them. Silent data corruption is a far worse outcome than a crash, and a
crash is what typed attribute access gives you for free.

So the rules here are:

- **Attribute access is direct and typed.** No `getattr` with defaults, no
  `hasattr` dispatch. A renamed field raises `AttributeError` at the boundary,
  on the first call, before any budget is spent.
- **`isinstance` appears only to reject, never to branch.** Validating that the
  vendor handed us the shape we expect, and raising when it did not, is this
  layer's job. Using it to quietly pick between two behaviours is what makes it
  a smell.
- **Genuinely optional fields are handled explicitly**, because the SDK declares
  them optional. `content` really is nullable on a refusal; `reasoning_details`
  really is absent on a non-reasoning model. Those are documented states, not
  missing attributes, and they are distinguished from each other in the result.

`openrouter_metadata` is the reason provenance is cheap. It is off by default
and gated behind `x_open_router_metadata="enabled"` (see `client.py`); with it
on, one response carries the served provider, the *dated* model actually routed
to, the routing strategy, and the cost. Without it, `ChatResult.model` echoes
the bare alias and there is no provider field at all — which is what previously
forced a second, lagged API call per rollout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from openrouter.components.chatassistantmessage import ChatAssistantMessage
from openrouter.components.chatresult import ChatResult

#: Reasoning we can actually read, as opposed to a provider-side summary or an
#: encrypted blob. The distinction is load-bearing: the forensics protocol's
#: first step is reading the CoT, and a *summary* is not the CoT. Treating one
#: as the other would quietly turn "what the model reasoned" into "what the
#: provider chose to tell us about it".
READABLE_REASONING: Final[str] = "reasoning.text"

#: What `Routing.strategy` reads when OpenRouter routed straight to the pinned
#: endpoint. Anything else means the request was re-routed and the rollout is
#: not from the endpoint it claims.
DIRECT_ROUTING: Final[str] = "direct"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts for one completion.

    `reasoning` is nested two levels deep in the SDK
    (`usage.completion_tokens_details.reasoning_tokens`) and is the measure the
    source post's headline finding is about, so it is lifted to the top level
    here rather than left for every call site to dig out.
    """

    prompt: int = 0
    completion: int = 0
    reasoning: int = 0
    total: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class Routing:
    """Which endpoint actually served a call, as OpenRouter reports it.

    `served_model` is the field that matters most and the one the plain
    response does not give you: it is the *dated* snapshot the request resolved
    to, so it catches an alias being repointed at new weights. `ChatResult.model`
    echoes the alias instead and would show no difference at all.

    Every field is optional because metadata can legitimately be absent — the
    header may be off, or a retried attempt may not carry it. Absent provenance
    is an unknown, not a mismatch, and `verified` is what separates the two.
    """

    served_provider: str | None = None
    served_model: str | None = None
    strategy: str | None = None
    attempt: int | None = None

    @property
    def verified(self) -> bool:
        """Whether OpenRouter told us who served this call."""
        return self.served_provider is not None and self.served_model is not None


@dataclass(frozen=True, slots=True)
class Completion:
    """One chat completion, in this project's own terms.

    `response` and `reasoning` are separate on purpose: a number appearing only
    in the chain of thought must never be readable as the model's answer, so
    grading is handed `response` alone.
    """

    gen_id: str
    response: str
    reasoning: str
    reasoning_kinds: tuple[str, ...] = ()
    refusal: str | None = None
    finish_reason: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    routing: Routing = field(default_factory=Routing)

    @property
    def has_readable_reasoning(self) -> bool:
        """True when the provider returned a real CoT rather than a summary."""
        return READABLE_REASONING in self.reasoning_kinds


class ResponseShapeError(RuntimeError):
    """The SDK returned a shape this project cannot interpret.

    Raised rather than papered over. Every case that produces this is one where
    guessing would put a plausible-looking wrong value into a results file.
    """


def parse_text(content: object, source: str) -> str:
    """Narrow a nullable SDK content field to a string, or refuse.

    The SDK types `content` as a union that resolves to `str` in every text
    response observed, but a multi-part content list is representable. Coercing
    one with `str()` would write `"[ChatContentPart(...)]"` into the results
    file as though the model had said it, so an unexpected type raises here
    instead.
    """
    if content is None:
        return ""
    if not isinstance(content, str):
        raise ResponseShapeError(
            f"{source} was {type(content).__name__}, expected str or None. "
            "The SDK's content shape changed; update completions.py rather than "
            "coercing it, or the results file records something the model never said."
        )
    return content


def parse_reasoning_kinds(message: ChatAssistantMessage) -> tuple[str, ...]:
    """The kinds of reasoning the provider returned, e.g. `reasoning.text`.

    Recorded rather than assumed, because the kind is the difference between
    reading the model's chain of thought and reading a provider's summary of it.
    The SDK models these as a discriminated union with an explicit
    `UnknownReasoningDetailUnion` variant, so a kind this project has never seen
    still arrives with a usable `.type` instead of being silently dropped.
    """
    details = message.reasoning_details
    if details is None:
        return ()
    return tuple(str(detail.type) for detail in details)


def parse_usage(result: ChatResult) -> TokenUsage:
    """Token counts and cost, flattened out of the SDK's nested optionals."""
    usage = result.usage
    if usage is None:
        return TokenUsage()
    details = usage.completion_tokens_details
    reasoning = (
        0 if details is None or details.reasoning_tokens is None else details.reasoning_tokens
    )
    return TokenUsage(
        prompt=usage.prompt_tokens,
        completion=usage.completion_tokens,
        reasoning=reasoning,
        total=usage.total_tokens,
        cost_usd=usage.cost or 0.0,
    )


def parse_routing(result: ChatResult) -> Routing:
    """Who served the call, from `openrouter_metadata`.

    Returns an unverified `Routing` when metadata is absent rather than raising.
    Absence is a real, benign state — the header can be off, and a retried
    attempt need not carry it — and treating "we were not told" as "the pin was
    violated" would make the audit cry wolf on infrastructure noise, which is
    how an audit gets ignored.

    A metadata block that *is* present but names no selected endpoint is a
    different matter: that is a shape this project cannot interpret, so it
    raises.
    """
    metadata = result.openrouter_metadata
    if metadata is None:
        return Routing()
    available = metadata.endpoints.available if metadata.endpoints is not None else []
    selected = [endpoint for endpoint in available if endpoint.selected]
    if len(selected) != 1:
        raise ResponseShapeError(
            f"expected exactly one selected endpoint, got {len(selected)} "
            f"of {len(available)} available. Cannot say which endpoint served this call."
        )
    return Routing(
        served_provider=selected[0].provider,
        served_model=selected[0].model,
        strategy=str(metadata.strategy),
        attempt=metadata.attempt,
    )


def parse_completion(result: ChatResult) -> Completion:
    """Convert one SDK `ChatResult` into a `Completion`.

    The single place the vendor's shape is read. Everything downstream sees
    project types only.
    """
    if not result.choices:
        raise ResponseShapeError(
            f"generation {result.id} returned no choices; there is no response to record."
        )
    choice = result.choices[0]
    message = choice.message
    return Completion(
        gen_id=result.id,
        response=parse_text(message.content, "message.content"),
        reasoning=parse_text(message.reasoning, "message.reasoning"),
        reasoning_kinds=parse_reasoning_kinds(message),
        refusal=message.refusal,
        finish_reason="" if choice.finish_reason is None else str(choice.finish_reason),
        usage=parse_usage(result),
        routing=parse_routing(result),
    )
