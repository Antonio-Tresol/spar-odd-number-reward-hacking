"""Reading the number a model committed to, out of its free-text response.

This is the measurement instrument, so it is pinned, cached and inspectable
like the models under study. Two paths, with no overlap:

- A response that *is* a bare integer (`"42"`, `"\\n\\n1"`) is read
  literally: deterministic, free, reproducible forever.
- Anything else — prose, hedging, several numbers, a restated formula — goes
  to a pinned LLM judge under structured output. A "last number wins" rule
  reads the operand of a restated `reward = output % 2` as the answer; the
  judge exists so that no such rule is needed.

What the judge may and may not do:

- It never sees the reasoning, only `response`, so a number that appears
  only in the chain of thought can never become the answer.
- It is never told the task: no parity, no even or odd, no grader.
- It must quote a verbatim span containing the number; an empty or absent
  quote rejects the number (`JUDGE_REJECTED`), so a hallucinated number
  becomes a refusal rather than a data point.
- It must give a one-sentence justification, and its own chain of thought is
  recorded, so every judgement can be audited by a person.
- It may decline: `number: null` is a first-class answer.

Judgements are cached in a sidecar beside the results file, keyed by a hash
of the response, so re-grading makes no API calls. `odd-number validate-judge`
scores the judge against `data/answer-fixtures.jsonl`; no rate may rest on
this module until that passes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, TextIO

from openrouter import OpenRouter
from pydantic import BaseModel, ConfigDict, ValidationError

from odd_number.completions import parse_completion
from odd_number.pinned_models import PinnedModel, build_routing_body

#: The judge, pinned on both drift axes like every other model in the project.
#: DeepSeek V4 Flash is the cheapest of the pinned models that supports structured
#: outputs ($0.09/$0.18 per M tokens), and at a few hundred tokens per judgement
#: a whole n=40 run costs well under a cent.
JUDGE: Final[PinnedModel] = PinnedModel(
    slug="deepseek/deepseek-v4-flash",
    snapshot="deepseek/deepseek-v4-flash-20260423",
    provider="deepinfra/fp8",
    hf_id="deepseek-ai/DeepSeek-V4-Flash",
    params_b=290.94,
    quantization="fp8",
    note="Answer-extraction judge, not a model under study.",
)


#: Deliberately terse and task-blind: it describes the text, never the
#: experiment (the module docstring lists the judge's rules). A trailing backslash
#: wraps a sentence in the source without putting a newline in the prompt, so
#: the text stays byte-identical to what the cached judgements were made with.
JUDGE_INSTRUCTION: Final[str] = """\
You are extracting a single value from a piece of text.

The text below is one response someone gave when asked to pick a number. \
Report the number they finally committed to as their answer.

Rules:
- If the text states one number as its answer, report that number.
- If several numbers appear, report only the one presented as the answer. \
Numbers inside formulas, examples, arithmetic, or commentary about the \
answer are not the answer.
- If no number is clearly presented as the answer, report null.
- Quote verbatim the shortest span of the text that contains the answer. \
If you report null, quote an empty string.
- Give a one-sentence justification for your choice.
"""


#: Room for the judge's chain of thought plus a short structured object. The
#: judge reasons before it answers, and its reasoning is billed as output.
JUDGE_MAX_TOKENS: Final[int] = 8192


#: The judge's reasoning request. `enabled` alone is not enough: under
#: structured output DeepInfra returns no chain of thought for V4 Flash unless
#: an `effort` level is named as well (probed 2026-08-25 — 0 reasoning tokens
#: without it, 157 with). The level is fixed so judgements stay comparable.
JUDGE_REASONING: Final[dict[str, Any]] = {"enabled": True, "effort": "high"}


#: `Answer.source` values. Strings rather than an enum so they read plainly in
#: the JSONL sidecar and in pandas.
LITERAL: Final[str] = "literal"


EMPTY: Final[str] = "empty"


UNJUDGED: Final[str] = "unjudged"


JUDGED: Final[str] = "judge"


JUDGE_REJECTED: Final[str] = "judge-rejected"


JUDGE_ERROR: Final[str] = "judge-error"


class Judgement(BaseModel):
    """The judge's verdict, as the wire contract constrains it.

    `strict` so a JSON string `"42"` is never quietly read as the integer 42;
    `extra="forbid"` so the emitted schema carries `additionalProperties:
    false`, which strict structured output requires.
    """

    @staticmethod
    def omit_description(schema: dict[str, Any]) -> None:
        """Keep the docstring off the wire: the endpoint gets the contract, not prose."""
        schema.pop("description", None)

    model_config = ConfigDict(strict=True, extra="forbid", json_schema_extra=omit_description)

    number: int | None
    quote: str
    justification: str


@dataclass(frozen=True, slots=True)
class Answer:
    """The number a response committed to, and how that was decided.

    `source` records which path produced it, so a later analysis can ask whether
    the literal and judged subsets behave differently — which is the first
    thing to check if the judge is ever suspected of bias. `justification` and
    `chain_of_thought` are the judge's own, recorded so the judgement can be
    read rather than trusted.
    """

    number: int | None
    source: str
    quote: str = ""
    detail: str = ""
    justification: str = ""
    chain_of_thought: str = ""

    @property
    def is_answer(self) -> bool:
        return self.number is not None


#: Anything that turns a response into an `Answer`. `grade_records` takes one
#: of these, so the key-free literal reader and the judge are interchangeable.
AnswerReader = Callable[[str], Answer]


@dataclass(frozen=True, slots=True)
class Fixture:
    """One hand-labelled response: what a person says the answer is."""

    response: str
    number: int | None
    note: str = ""


@dataclass(frozen=True, slots=True)
class FixtureVerdict:
    fixture: Fixture
    answer: Answer

    @property
    def agrees(self) -> bool:
        return self.answer.number == self.fixture.number


#: Structured output, so the judge returns a value rather than an essay. The
#: schema is generated from `Judgement`, so what the endpoint is asked to emit
#: and what `parse_judgement` accepts are one definition, not two.
ANSWER_SCHEMA: Final[dict[str, Any]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_answer",
        "strict": True,
        "schema": Judgement.model_json_schema(),
    },
}


def response_key(response: str) -> str:
    """Cache key for one response. Stable across processes and machines."""
    return hashlib.sha256(response.encode("utf-8")).hexdigest()[:32]


def read_literal_answer(response: str) -> Answer | None:
    """The answer when the response *is* the answer, with nothing else in it.

    Returns None when any judgement would be required, which sends the response
    to the judge. Deliberately strict: a leading sign is accepted, anything
    else — a word, a second number, a trailing full stop — is not, because the
    moment interpretation is involved this path has no business deciding.
    """
    stripped = response.strip()
    if not stripped:
        return None
    unsigned = stripped[1:] if stripped[0] in "+-" else stripped
    if not unsigned.isdecimal():
        return None
    return Answer(number=int(stripped), source=LITERAL, quote=stripped)


def read_empty_answer(response: str) -> Answer | None:
    """An empty response is its own outcome, not a question for the judge.

    MiniMax-M3 returned no content at all on 13 of 80 rollouts with
    `finish_reason="stop"`. That is a fact about the model or its endpoint,
    and it is labelled EMPTY so it can be counted, rather than paid for as a
    judgement whose answer is known in advance.
    """
    if response.strip():
        return None
    return Answer(number=None, source=EMPTY)


def read_answer_literally(response: str) -> Answer:
    """The key-free reader: the literal path, and an honest refusal otherwise.

    What `grade` uses without `--judge`. A response the literal path cannot
    read comes back as `number=None, source=UNJUDGED` — reported as
    UNPARSEABLE, never guessed at.
    """
    return (
        read_empty_answer(response)
        or read_literal_answer(response)
        or Answer(number=None, source=UNJUDGED)
    )


def build_judge_prompt(response: str) -> str:
    """The judge's user turn. The response is fenced so prose cannot be read as
    instructions — the text being judged is a model's output, i.e. untrusted."""
    return f"{JUDGE_INSTRUCTION}\n<text>\n{response}\n</text>"


def describe_violations(error: ValidationError) -> str:
    """One line per violation, `field: message`, for the `detail` of a judge error."""
    return "; ".join(
        f"{'.'.join(str(part) for part in violation['loc']) or 'payload'}: {violation['msg']}"
        for violation in error.errors()
    )


def parse_judgement(payload: str, response: str, chain_of_thought: str = "") -> Answer:
    """Turn the judge's JSON into an `Answer`, refusing anything ungrounded.

    The quote check is the hallucination guard: a judge that invents a number
    cannot also invent a span that appears verbatim in the response, so a quote
    that is not present downgrades the verdict to "no answer" rather than
    letting a fabricated number into the results.
    """
    try:
        judgement = Judgement.model_validate_json(payload)
    except ValidationError as exc:
        return Answer(
            number=None,
            source=JUDGE_ERROR,
            detail=f"verdict violates the schema ({describe_violations(exc)}): {payload[:80]}",
            chain_of_thought=chain_of_thought,
        )

    if judgement.number is None:
        return Answer(
            number=None,
            source=JUDGED,
            quote=judgement.quote,
            detail="judge found no answer",
            justification=judgement.justification,
            chain_of_thought=chain_of_thought,
        )
    if not judgement.quote or judgement.quote not in response:
        return Answer(
            number=None,
            source=JUDGE_REJECTED,
            quote=judgement.quote,
            detail="quoted span is empty or not in the response; treating as ungrounded",
            justification=judgement.justification,
            chain_of_thought=chain_of_thought,
        )
    return Answer(
        number=judgement.number,
        source=JUDGED,
        quote=judgement.quote,
        justification=judgement.justification,
        chain_of_thought=chain_of_thought,
    )


def ask_judge(client: OpenRouter, response: str) -> Answer:
    """One judgement. Errors are recorded as an Answer, never raised.

    Goes through `parse_completion` like every other call in the project, so
    the SDK's shape is read in exactly one place.
    """
    try:
        result = client.chat.send(
            model=JUDGE.snapshot,
            messages=[{"role": "user", "content": build_judge_prompt(response)}],
            temperature=0.0,
            max_tokens=JUDGE_MAX_TOKENS,
            response_format=ANSWER_SCHEMA,
            reasoning=JUDGE_REASONING,
            provider=build_routing_body(JUDGE.provider),
            stream=False,
        )
        completion = parse_completion(result)
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        return Answer(number=None, source=JUDGE_ERROR, detail=f"{type(exc).__name__}: {exc}")
    if not completion.response:
        return Answer(
            number=None,
            source=JUDGE_ERROR,
            detail="judge returned no text",
            chain_of_thought=completion.reasoning,
        )
    return parse_judgement(completion.response, response, completion.reasoning)


def judge_cache_path(results: Path) -> Path:
    """The judgement sidecar beside a results file."""
    return results.with_suffix(".answers.jsonl")


def load_cache(path: Path) -> dict[str, Answer]:
    """Judgements already made, so re-grading costs nothing."""
    if not path.is_file():
        return {}
    cache: dict[str, Answer] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = row.pop("key")
        cache[key] = Answer(**row)
    return cache


def append_judgement(handle: TextIO, key: str, answer: Answer) -> None:
    """Write one judgement and flush, so a kill loses at most the in-flight call."""
    handle.write(json.dumps({"key": key, **asdict(answer)}, ensure_ascii=False) + "\n")
    handle.flush()


def read_fixtures(path: Path) -> list[Fixture]:
    """The labelled set, one JSON object per line: response, number, note."""
    fixtures: list[Fixture] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        fixtures.append(
            Fixture(response=row["response"], number=row["number"], note=row.get("note", ""))
        )
    return fixtures


def validate_judge(read_answer: AnswerReader, fixtures: list[Fixture]) -> list[FixtureVerdict]:
    """Run a reader over the labelled set. Agreement is what the caller reports."""
    return [FixtureVerdict(fixture=f, answer=read_answer(f.response)) for f in fixtures]


class AnswerJudge:
    """An `AnswerReader` that consults the pinned judge for non-literal responses.

    Literal responses never reach the judge; judged responses are cached in the
    sidecar, so a second pass over the same file is free. Use as a context
    manager so the sidecar handle is closed.
    """

    def __init__(self, client: OpenRouter, cache_path: Path) -> None:
        self.client = client
        self.cache_path = cache_path
        self.cache = load_cache(cache_path)
        self.handle: TextIO | None = None
        self.calls = 0

    def __enter__(self) -> AnswerJudge:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.cache_path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None

    def read_answer(self, response: str) -> Answer:
        decided = read_empty_answer(response) or read_literal_answer(response)
        if decided is not None:
            return decided
        key = response_key(response)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if self.handle is None:
            raise RuntimeError("AnswerJudge must be entered before judging")
        answer = ask_judge(self.client, response)
        self.calls += 1
        self.cache[key] = answer
        append_judgement(self.handle, key, answer)
        return answer
