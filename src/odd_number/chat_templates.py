"""Model prompt formats, rendered client-side for the text-completions endpoint.

`/v1/chat/completions` applies a Jinja template server-side. `/v1/completions`
does not, and only the second endpoint lets a request stop mid-thought, which is
what resampling a chain of thought needs. So the template is rendered here.

Getting it wrong is silent. A prefix missing the reasoning-effort system block
still returns fluent, well-formed output at roughly a ninth the deliberation
length: 976 characters median against 9,602 once the block was restored, over
the same 40 prompts (probed 2026-08-28, `Q1.H8.E1`).

Transcribed from `Qwen/Qwen3.8-27B`'s `tokenizer_config.json` `chat_template`,
read 2026-08-28. Only the path this project uses is rendered: one user turn,
thinking enabled, no tools, and no system message of our own. Every other branch
of that template raises, because rendering an approximation is the failure mode
described above.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Rendered by Qwen's template from `reasoning_effort|default('xhigh')` when no
#: system message is supplied. Verbatim; `pinned_models.py` records that xhigh is
#: this model's catalogue default, and the template above is where that default
#: actually lives.
QWEN_XHIGH_INSTRUCTIONS: Final[str] = (
    "Reasoning effort is set to xhigh. Please think carefully through the task, "
    "validate key assumptions, consider plausible alternatives, and prioritize "
    "correctness, consistency, and clarity in the final answer."
)


class TemplateError(RuntimeError):
    """A conversation this template cannot render exactly.

    Raised rather than approximated: an approximate prefix produces output that
    looks right and is drawn from a different distribution.
    """


@dataclass(frozen=True, slots=True)
class ChatTemplate:
    """One model's prompt format, enough of it to resume a partial trace.

    reasoning_instructions: the system text the template injects when thinking is
        on. For Qwen this is the entire difference between a 976-character trace
        and a 9,602-character one, so it is a required field with no default.
    turn_open, turn_close, think_open: the ChatML markers. Fields rather than
        literals so a second model can be added without editing `render`.
    """

    reasoning_instructions: str
    turn_open: str = "<|im_start|>"
    turn_close: str = "<|im_end|>"
    think_open: str = "<think>"
    think_close: str = "</think>"

    def render(self, user_message: str, partial_reasoning: str = "") -> str:
        """The exact prompt string, ending inside the reasoning channel.

        `partial_reasoning` is the trace kept as a prefix; empty means branch
        position zero, where the model reasons from nothing but the prompt. The
        string deliberately ends without a trailing newline after the prefix, so
        the model continues the last sentence rather than starting a new one.

        Raises:
            TemplateError: when `user_message` contains a turn marker. That would
                let prompt text close the user turn and open another role, which
                is prompt injection against our own harness rather than a
                measurement of the model.
        """
        for marker in (self.turn_open, self.turn_close):
            if marker in user_message:
                raise TemplateError(
                    f"user message contains the turn marker {marker!r}, which would "
                    "forge a role boundary. Refusing to render it."
                )
        return (
            f"{self.turn_open}system\n{self.reasoning_instructions}{self.turn_close}\n"
            f"{self.turn_open}user\n{user_message}{self.turn_close}\n"
            f"{self.turn_open}assistant\n{self.think_open}\n{partial_reasoning}"
        )


#: The one template this project has verified against the chat endpoint.
QWEN3_THINKING: Final[ChatTemplate] = ChatTemplate(reasoning_instructions=QWEN_XHIGH_INSTRUCTIONS)

#: Keyed by the model slug whose served weights the template was read from.
#: A slug absent here cannot be branched, which is the intended failure: the
#: template is per-model and guessing one is the hazard this module exists for.
TEMPLATES_BY_SLUG: Final[dict[str, ChatTemplate]] = {
    "qwen/qwen3.8-27b": QWEN3_THINKING,
}


def resolve_template(slug: str) -> ChatTemplate:
    """The verified template for a model slug.

    Raises:
        TemplateError: when none has been transcribed for that model.
    """
    try:
        return TEMPLATES_BY_SLUG[slug]
    except KeyError:
        known = ", ".join(sorted(TEMPLATES_BY_SLUG)) or "(none)"
        raise TemplateError(
            f"no chat template transcribed for {slug!r}; have: {known}. "
            "Read its tokenizer_config.json chat_template and add it, then verify "
            "against the chat endpoint before branching anything."
        ) from None
