"""Interviews: resume a finished rollout as a conversation and question the model.

An `Interview` picks up at the moment a model answered: the original prompt and
the response it gave are replayed as the first two turns, and every later turn
is a question put to the same pinned endpoint.

**What an interview is evidence of.** Hypotheses, not causes. A model asked why
it answered 7 generates a plausible account; it does not recall a computation.
`notes/interview-protocol.md` has the rules a session follows, and why.

**Both sides are recorded.** The model's turns keep reasoning, finish reason,
served endpoint, cost and seed. The interviewer's keep three things, all
required: `interviewer`, who is asking; `rationale`, why this question was
asked; and an observation turn after each answer.

Observations use `OBSERVER_ROLE`, which `build_conversation_messages` does not send,
so notes are private by construction rather than by convention. The seeded
rollout's chain of thought is always recorded on the replayed turn for the
reader; whether it is also sent to the model is the session's seed-reasoning
mode, `shown` by default. Either way the interviewer has it, which is what makes
it possible to check an account against the reasoning that actually ran.

An observation carries free prose in `content`, verbatim `quotes` from the turn
it observes, and free-form `tags`. Quotes are checked before the turn is built,
so a citation that is not in its source raises `QuoteNotFoundError` instead of
entering the record. Tags have no enum, because a fixed set would only ever
record the categories already expected. `observes_turn` keeps a note attached to
its evidence when the transcript is filtered or re-ordered.

`ask_question` raises `UnobservedAnswerError` when the previous answer has no
note: notes written at the end are reconstruction.

One JSONL file per interview under `results/interviews/`, appended turn by turn
and flushed, so a killed session keeps everything up to the last exchange.

Sampling matches collection, temperature 1.0 included. Seeds are stable per
turn, but a re-asked question is not expected to repeat.

Entry point: `uv run odd-number interview --session <name> …`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final, NotRequired, TextIO, TypedDict

from openrouter import OpenRouter

from odd_number.pinned_models import PinnedModel
from odd_number.rollouts import request_chat
from odd_number.sampling import SamplingParams
from odd_number.traces import Trace, load_traces

#: Subdirectory of `results/` holding one JSONL per interview.
INTERVIEWS_DIRNAME: Final[str] = "interviews"

# The four kinds of turn. `REPLAYED` marks the two turns copied out of a
# results file rather than generated in this session: they cost nothing, they
# were not sampled here, and a reader must be able to tell them from turns the
# interview itself produced.
REPLAYED: Final[str] = "replayed"
QUESTION: Final[str] = "question"
ANSWER: Final[str] = "answer"
OBSERVATION: Final[str] = "observation"

#: Whether the seeded rollout's chain of thought is replayed to the model.
#: `shown` asks what it endorses with its deliberation in front of it;
#: `withheld` asks what it reconstructs without. Different questions, never
#: pooled, so the mode is recorded on every turn. Only endpoints with
#: `PinnedModel.replays_reasoning` can run `shown`; the rest drop the field
#: silently, which is why `build_seed_turns` refuses rather than downgrading.
SEED_REASONING_SHOWN: Final[str] = "shown"
SEED_REASONING_WITHHELD: Final[str] = "withheld"
SEED_REASONING_MODES: Final[tuple[str, str]] = (SEED_REASONING_SHOWN, SEED_REASONING_WITHHELD)

#: Roles that go on the wire. An observation is written with `OBSERVER_ROLE`,
#: which is not in this set, so the detective's notes cannot reach the model
#: even if a future caller forgets they are private.
WIRE_ROLES: Final[frozenset[str]] = frozenset({"user", "assistant"})
OBSERVER_ROLE: Final[str] = "observer"


class EmptyRationaleError(ValueError):
    """A question was asked without saying why.

    Raised rather than defaulted. An interview is only interpretable if each
    question carries its reason, and a blank rationale silently produces a
    transcript that looks rigorous and cannot be audited.
    """


class MissingInterviewerError(ValueError):
    """A turn was written without saying who produced it."""


class UnobservedAnswerError(ValueError):
    """The previous answer has no observation, so the next question is refused.

    Notes taken after the fact are reconstruction. This forces the note to be
    written while the answer is the most recent thing that happened.
    """


class ReasoningNotReplayableError(ValueError):
    """`shown` was asked for on an endpoint that drops inbound reasoning.

    Raised rather than downgraded to `withheld`: a session silently running the
    ablation while its transcript says otherwise is worse than no session.
    """


class QuoteNotFoundError(ValueError):
    """An observation cited text that is not in the turn it claims to quote.

    A rule this module enforces mechanically rather than trusting: a citation
    that cannot be found in its source never enters the record.
    """


class InterviewTurnRecord(TypedDict):
    """One JSONL line as it is read back off disk.

    Every field is `NotRequired` for the same reason as `RolloutRecord`: a file
    written before a field existed simply lacks it, and the reader's job is to
    cope with that rather than to assert that history matches the present.
    """

    session: NotRequired[str]
    turn: NotRequired[int]
    role: NotRequired[str]
    kind: NotRequired[str]
    content: NotRequired[str]
    rationale: NotRequired[str]
    reasoning_on_wire: NotRequired[bool]
    refusal: NotRequired[str | None]
    gen_id: NotRequired[str | None]
    observes_turn: NotRequired[int | None]
    quotes: NotRequired[list[str]]
    tags: NotRequired[list[str]]
    interviewer: NotRequired[str]
    model: NotRequired[str]
    snapshot: NotRequired[str]
    provider: NotRequired[str]
    source_file: NotRequired[str]
    treatment: NotRequired[str]
    index: NotRequired[int]
    seed_number: NotRequired[int | None]
    seed_parity: NotRequired[str]
    seed_reasoning_chars: NotRequired[int]
    reasoning: NotRequired[str]
    reasoning_kinds: NotRequired[list[str]]
    finish_reason: NotRequired[str]
    served_model: NotRequired[str | None]
    served_provider: NotRequired[str | None]
    cost_usd: NotRequired[float]
    seed: NotRequired[int | None]
    sampling: NotRequired[dict[str, Any]]
    error: NotRequired[str | None]


@dataclass(frozen=True, slots=True)
class InterviewTurn:
    """One turn, written as one JSONL line.

    Session and seed provenance repeat on every row rather than living in a
    header, so each line is self-describing — the same choice `Rollout` makes
    with `model`, `snapshot`, `provider` and `sampling`.
    """

    session: str
    turn: int
    role: str
    kind: str
    content: str
    #: Who produced this turn: an agent name, a model id, or a person. Required
    #: on every turn, because an elicited account cannot be read without knowing
    #: who elicited it.
    interviewer: str
    model: str
    snapshot: str
    provider: str
    source_file: str
    treatment: str
    index: int
    seed_number: int | None
    seed_parity: str
    seed_reasoning_chars: int
    #: Why the interviewer asked this. Empty on every turn that is not a question.
    rationale: str = ""
    #: A refusal arrives as empty `content` with no `error`, so without this a
    #: refused answer cannot be told from any other empty one. Refusals are a
    #: likely outcome when asking a model why it did something, which makes this
    #: one of the more informative fields on the turn rather than an edge case.
    refusal: str | None = None
    #: The handle for looking this generation up on OpenRouter afterwards.
    gen_id: str | None = None
    #: Which turn an observation is about. None on every turn that is not one.
    observes_turn: int | None = None
    #: Whether this turn's `reasoning` was sent to the model as well as recorded.
    #: Set on the replayed turn by the session's seed-reasoning mode.
    reasoning_on_wire: bool = False
    #: Verbatim spans from the observed turn, checked before the turn is built.
    quotes: list[str] = field(default_factory=list)
    #: Free vocabulary. See the module docstring for why there is no enum.
    tags: list[str] = field(default_factory=list)
    reasoning: str = ""
    reasoning_kinds: list[str] = field(default_factory=list)
    finish_reason: str = ""
    served_model: str | None = None
    served_provider: str | None = None
    cost_usd: float = 0.0
    seed: int | None = None
    sampling: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Interview:
    """A whole session, read back from its file."""

    session: str
    model: str
    interviewer: str
    source_file: str
    treatment: str
    index: int
    seed_number: int | None
    seed_parity: str
    seed_reasoning_chars: int
    turns: tuple[InterviewTurnRecord, ...]

    @property
    def question_count(self) -> int:
        return sum(1 for turn in self.turns if turn.get("kind") == QUESTION)

    @property
    def replays_seed_reasoning(self) -> bool:
        """Whether this session sends the seeded chain of thought to the model.

        Read off the replayed turn rather than stored on the session, so a
        rendered transcript can never disagree with what was actually sent.
        """
        return any(
            turn.get("kind") == REPLAYED and turn.get("reasoning_on_wire") for turn in self.turns
        )

    @property
    def observation_count(self) -> int:
        return sum(1 for turn in self.turns if turn.get("kind") == OBSERVATION)

    @property
    def cost_usd(self) -> float:
        return sum(turn.get("cost_usd") or 0.0 for turn in self.turns)


def interviews_dir(results_dir: Path) -> Path:
    """Where interviews live, derived from the results directory."""
    return results_dir / INTERVIEWS_DIRNAME


def interview_path(results_dir: Path, session: str) -> Path:
    return interviews_dir(results_dir) / f"{session}.jsonl"


def read_interview(path: Path) -> Interview | None:
    """Read a session back, or None if it does not exist yet.

    A torn final line is skipped rather than raised on, for the reason
    `read_rollouts` gives: the write path flushes each turn, so only the last
    line can be incomplete.
    """
    if not path.is_file():
        return None
    turns: list[InterviewTurnRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            turns.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not turns:
        return None
    first = turns[0]
    return Interview(
        session=first.get("session", path.stem),
        model=first.get("model", ""),
        interviewer=first.get("interviewer", ""),
        source_file=first.get("source_file", ""),
        treatment=first.get("treatment", ""),
        index=first.get("index", -1),
        seed_number=first.get("seed_number"),
        seed_parity=first.get("seed_parity", ""),
        seed_reasoning_chars=first.get("seed_reasoning_chars", 0),
        turns=tuple(turns),
    )


def is_abandoned_question(turns: Sequence[InterviewTurnRecord], position: int) -> bool:
    """Whether the question at `position` never got an answer worth keeping.

    A failed call, a refusal and a torn write all leave one. Re-sending it would
    put wording back on the wire that the model never answered.
    """
    following = turns[position + 1] if position + 1 < len(turns) else None
    if following is None or following.get("kind") != ANSWER:
        return True
    return bool(following.get("error")) or not following.get("content")


def build_conversation_messages(interview: Interview) -> list[dict[str, str]]:
    """The transcript in wire form.

    Rationales, observations and tags are never emitted, in either mode.
    `reasoning` is emitted only where `reasoning_on_wire` is set, which
    `build_seed_turns` decides once per session.

    Questions whose answers failed or came back empty are dropped with those
    answers, so a retry asks the next question rather than re-asking an
    abandoned one.
    """
    messages: list[dict[str, str]] = []
    for position, turn in enumerate(interview.turns):
        if turn.get("role") not in WIRE_ROLES or not turn.get("content"):
            continue
        if turn.get("kind") == QUESTION and is_abandoned_question(interview.turns, position):
            continue
        message = {"role": turn["role"], "content": turn["content"]}
        if turn.get("reasoning_on_wire") and turn.get("reasoning"):
            message["reasoning"] = turn["reasoning"]
        messages.append(message)
    return messages


def find_observed_turns(interview: Interview) -> set[int]:
    """Turn numbers that already carry an observation."""
    return {
        turn["observes_turn"]
        for turn in interview.turns
        if turn.get("kind") == OBSERVATION and turn.get("observes_turn") is not None
    }


def find_last_observable_turn(interview: Interview) -> InterviewTurnRecord | None:
    """The most recent turn from the model: an answer, or the replayed response.

    The replayed response counts, so an interviewer may take notes on the
    original answer before asking anything at all.
    """
    for turn in reversed(interview.turns):
        if turn.get("role") == "assistant":
            return turn
    return None


def collect_tags(interview: Interview) -> dict[str, int]:
    """Every observation tag in the session with its count."""
    counts: dict[str, int] = {}
    for turn in interview.turns:
        for tag in turn.get("tags", []) or []:
            counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def build_provenance_fields(interview: Interview, interviewer: str) -> dict[str, Any]:
    """The session and seed identity that every turn repeats.

    Read off the opening turn, so a turn appended later cannot disagree with it
    about which rollout is under interview. `snapshot` and `provider` are absent
    because they describe one call's endpoint rather than the seed; each caller
    supplies them from the `PinnedModel` it used.
    """
    return {
        "session": interview.session,
        "interviewer": interviewer,
        "model": interview.model,
        "source_file": interview.source_file,
        "treatment": interview.treatment,
        "index": interview.index,
        "seed_number": interview.seed_number,
        "seed_parity": interview.seed_parity,
        "seed_reasoning_chars": interview.seed_reasoning_chars,
    }


def normalise_for_quoting(text: str) -> str:
    """Collapse runs of whitespace, so a quote may be re-wrapped but not reworded."""
    return " ".join(text.split())


def verify_quotes(quotes: Sequence[str], turn: InterviewTurnRecord) -> None:
    """Check every quote against the turn it claims to come from.

    Reasoning counts as source, not only content: citing the chain of thought is
    why it is recorded.

    Raises:
        QuoteNotFoundError: on the first quote that is not present.
    """
    haystack = normalise_for_quoting(f"{turn.get('content', '')}\n{turn.get('reasoning', '')}")
    for quote in quotes:
        needle = normalise_for_quoting(quote)
        if not needle:
            raise QuoteNotFoundError("an empty quote cites nothing")
        if needle not in haystack:
            raise QuoteNotFoundError(
                f"not found in turn {turn.get('turn')}: {quote!r}. "
                "Quotes must be verbatim from that turn's content or reasoning; "
                "whitespace may differ, wording may not."
            )


def find_seed_traces(results_dir: Path, model_slug: str, parity: str | None = None) -> list[Trace]:
    """Every graded rollout of one model that an interview could start from.

    Graded through `load_traces`, so an interview seed is the same object a
    reading or a grade would see, rather than a second parse that could disagree
    with them about what the model answered.
    """
    return [
        trace
        for trace in load_traces(results_dir)
        if trace.model == model_slug
        and trace.finish_reason == "stop"
        and trace.response
        and trace.parity in ("odd", "even")
        and (parity is None or trace.parity == parity)
    ]


def select_seed_trace(
    traces: Sequence[Trace], source_file: str, treatment: str, index: int
) -> Trace | None:
    for trace in traces:
        if trace.file == source_file and trace.treatment == treatment and trace.index == index:
            return trace
    return None


def derive_turn_seed(session: str, turn: int) -> int:
    """A stable per-turn seed, also sent to the API.

    SHA-256 rather than `hash()`, for the reason `rollouts.derive_seed` gives:
    Python randomises string hashing per process, so a hash-derived seed
    reproduces nothing across runs.
    """
    return int(hashlib.sha256(f"{session}|{turn}".encode()).hexdigest()[:8], 16)


def build_seed_turns(
    session: str,
    model: PinnedModel,
    trace: Trace,
    interviewer: str,
    seed_reasoning: str = SEED_REASONING_SHOWN,
) -> tuple[InterviewTurn, InterviewTurn]:
    """The two replayed turns an interview starts from.

    The seeded rollout's chain of thought is recorded on the replayed turn
    either way; `seed_reasoning` decides whether it also goes to the model.

    Raises:
        MissingInterviewerError: when `interviewer` is blank.
    """
    if not interviewer.strip():
        raise MissingInterviewerError("every interview must record who is asking")
    if seed_reasoning not in SEED_REASONING_MODES:
        raise ValueError(f"seed_reasoning must be one of {SEED_REASONING_MODES}")
    shown = seed_reasoning == SEED_REASONING_SHOWN
    if shown and not model.replays_reasoning:
        raise ReasoningNotReplayableError(
            f"{model.provider} drops inbound reasoning for {model.slug}, so a "
            f"{SEED_REASONING_SHOWN!r} session would silently be a "
            f"{SEED_REASONING_WITHHELD!r} one. Ask for {SEED_REASONING_WITHHELD!r} explicitly."
        )
    common: dict[str, Any] = {
        "session": session,
        "model": model.slug,
        "snapshot": model.snapshot,
        "provider": model.provider,
        "source_file": trace.file,
        "treatment": trace.treatment,
        "index": trace.index,
        "seed_number": trace.number,
        "seed_parity": trace.parity,
        "seed_reasoning_chars": len(trace.reasoning),
        "interviewer": interviewer,
    }
    return (
        InterviewTurn(turn=0, role="user", kind=REPLAYED, content=trace.prompt, **common),
        InterviewTurn(
            turn=1,
            role="assistant",
            kind=REPLAYED,
            content=trace.response,
            reasoning=trace.reasoning,
            reasoning_on_wire=shown,
            **common,
        ),
    )


def build_observation(
    interview: Interview,
    content: str,
    interviewer: str,
    *,
    quotes: Sequence[str] = (),
    tags: Sequence[str] = (),
    about_turn: int | None = None,
) -> InterviewTurn:
    """The interviewer's note on one turn, with its citations checked.

    `about_turn` defaults to the model's most recent turn.

    Raises:
        MissingInterviewerError: when `interviewer` is blank.
        ValueError: when the note is empty or names a turn that does not exist.
        QuoteNotFoundError: when a quote is not verbatim in the observed turn.
    """
    if not interviewer.strip():
        raise MissingInterviewerError("every observation must record who made it")
    if not content.strip():
        raise ValueError("an observation needs a note")
    if about_turn is None:
        target = find_last_observable_turn(interview)
        if target is None:
            raise ValueError("nothing to observe yet: the model has not spoken")
    else:
        matches = [turn for turn in interview.turns if turn.get("turn") == about_turn]
        if not matches:
            raise ValueError(f"no turn {about_turn} in {interview.session}")
        target = matches[0]
    verify_quotes(quotes, target)
    first = interview.turns[0] if interview.turns else {}
    return InterviewTurn(
        turn=len(interview.turns),
        role=OBSERVER_ROLE,
        kind=OBSERVATION,
        content=content,
        snapshot=first.get("snapshot", ""),
        provider=first.get("provider", ""),
        observes_turn=target.get("turn"),
        quotes=list(quotes),
        tags=list(tags),
        **build_provenance_fields(interview, interviewer),
    )


def open_for_append(path: Path) -> TextIO:
    """Open an interview for appending, repairing a torn final line first.

    Appending after a kill would concatenate the next turn onto the fragment and
    lose both. Rollouts survive that because a resume re-collects; an interview
    has no resume.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size:
        with path.open("rb") as existing:
            existing.seek(-1, 2)
            torn = existing.read(1) != b"\n"
        if torn:
            with path.open("a", encoding="utf-8") as repair:
                repair.write("\n")
    return path.open("a", encoding="utf-8")


def append_turn(handle: TextIO, turn: InterviewTurn) -> None:
    """Write one turn and flush, so a kill loses at most the in-flight call."""
    handle.write(json.dumps(asdict(turn), ensure_ascii=False) + "\n")
    handle.flush()


def check_question_is_allowed(interview: Interview, rationale: str, interviewer: str) -> None:
    """Every precondition on asking, in one place.

    Raises:
        MissingInterviewerError: when `interviewer` is blank.
        EmptyRationaleError: when `rationale` is blank.
        UnobservedAnswerError: when the model's last turn has no observation.
    """
    if not interviewer.strip():
        raise MissingInterviewerError("every question must record who is asking")
    if not rationale.strip():
        raise EmptyRationaleError("every question needs a rationale")
    pending = find_last_observable_turn(interview)
    if pending is not None and pending.get("turn") not in find_observed_turns(interview):
        raise UnobservedAnswerError(
            f"turn {pending.get('turn')} has no observation. Record what that answer showed "
            "before asking the next question: notes written afterwards are reconstruction."
        )


def ask_question(
    client: OpenRouter,
    model: PinnedModel,
    interview: Interview,
    question: str,
    rationale: str,
    sampling: SamplingParams,
    interviewer: str,
) -> tuple[InterviewTurn, InterviewTurn]:
    """Put one question and take the answer, as two turns ready to be appended.

    A failed call still yields an answer turn carrying `error` and no content: a
    failure that leaves no row is one that gets silently retried into a
    different conversation.

    Raises:
        MissingInterviewerError: when `interviewer` is blank.
        EmptyRationaleError: when `rationale` is blank.
        UnobservedAnswerError: when the model's last turn has no observation.
    """
    check_question_is_allowed(interview, rationale, interviewer)
    next_turn = len(interview.turns)
    common = build_provenance_fields(interview, interviewer)
    question_turn = InterviewTurn(
        turn=next_turn,
        role="user",
        kind=QUESTION,
        content=question,
        rationale=rationale,
        snapshot=model.snapshot,
        provider=model.provider,
        **common,
    )
    messages = [*build_conversation_messages(interview), {"role": "user", "content": question}]
    seed = derive_turn_seed(interview.session, next_turn)
    try:
        completion = request_chat(client, model, messages, seed, sampling)
        error = None
    except Exception as exc:  # noqa: BLE001 — any provider failure becomes a recorded turn
        completion = None
        error = f"{type(exc).__name__}: {exc}"
    answer_turn = InterviewTurn(
        turn=next_turn + 1,
        role="assistant",
        kind=ANSWER,
        content=completion.response if completion else "",
        refusal=completion.refusal if completion else None,
        gen_id=completion.gen_id if completion else None,
        reasoning=completion.reasoning if completion else "",
        reasoning_kinds=list(completion.reasoning_kinds) if completion else [],
        finish_reason=completion.finish_reason if completion else "",
        served_model=completion.routing.served_model if completion else None,
        served_provider=completion.routing.served_provider if completion else None,
        cost_usd=completion.usage.cost_usd if completion else 0.0,
        seed=seed if model.seed_supported else None,
        sampling=sampling.as_record(),
        error=error,
        snapshot=model.snapshot,
        provider=model.provider,
        **common,
    )
    return question_turn, answer_turn


def render_interview(interview: Interview) -> str:
    """The transcript as a person reads it, rationale included."""
    tags = collect_tags(interview)
    lines = [
        f"# Interview {interview.session}",
        "",
        f"- model: `{interview.model}`",
        f"- interviewer: {interview.interviewer}",
        f"- seeded from: `{interview.source_file}` {interview.treatment} #{interview.index}",
        f"- answer under interview: {interview.seed_number} ({interview.seed_parity})",
        f"- questions: {interview.question_count}, cost: ${interview.cost_usd:.3f}",
        f"- seed reasoning: {interview.seed_reasoning_chars} characters,"
        f" {'replayed to the model' if interview.replays_seed_reasoning else 'withheld from the model'}"
        " and recorded for the reader",
    ]
    if tags:
        lines.append("- tags: " + ", ".join(f"`{tag}` x{count}" for tag, count in tags.items()))
    lines.append("")
    for turn in interview.turns:
        kind = turn.get("kind", "")
        role = turn.get("role", "")
        if kind == REPLAYED:
            lines.append(f"## replayed {role} (turn {turn.get('turn')})")
        elif kind == QUESTION:
            lines.append(f"## question {turn.get('turn')}")
            lines.append(f"*why asked:* {turn.get('rationale', '')}")
        elif kind == OBSERVATION:
            lines.append(f"## observation {turn.get('turn')} on turn {turn.get('observes_turn')}")
            if turn.get("tags"):
                lines.append("*tags:* " + ", ".join(f"`{tag}`" for tag in turn["tags"]))
        else:
            lines.append(f"## answer {turn.get('turn')}")
        lines.append("")
        if turn.get("error"):
            lines.append(f"**ERROR:** {turn['error']}")
        if turn.get("reasoning"):
            label = "original chain of thought" if kind == REPLAYED else "chain of thought"
            lines.extend(
                [
                    "<details><summary>" + label + "</summary>",
                    "",
                    turn["reasoning"],
                    "",
                    "</details>",
                    "",
                ]
            )
        lines.append(turn.get("content", ""))
        lines.append("")
        for quote in turn.get("quotes", []) or []:
            lines.append(f"> {quote}")
            lines.append("")
    return "\n".join(lines)
