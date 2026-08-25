"""Reading the number a model committed to, out of its free-text response.

**STATUS: unfinished scaffold. Nothing imports this module yet.**

`grades.extract_number` still raises `NotImplementedError` and does NOT call
anything here. The design below is settled and the code runs, but three things
are missing before it can be trusted as the project's measurement instrument,
and they are tracked as `Q1.H7.E3` in TREE.md:

1. The judge must return its own justification *and* its chain of thought, both
   recorded — `Answer` currently has neither. A judge that cannot be inspected
   is not better than a regex, it is a regex you cannot read.
2. It must be smoke-tested against a hand-labelled fixture set before any rate
   depends on it, with agreement reported. An unvalidated judge is an unmeasured
   instrument.
3. It must be wired into `grades.py` behind a flag, so `grade` stays runnable
   with no API key.

Do not use this to produce a number that appears in a deliverable until those
are done.

This is the measurement instrument. Every rate the project reports is a function
of what this module decides, so it gets the same treatment as the models under
study: pinned, cached, and unable to guess quietly.

## Why not a regex

The obvious rule — "last number wins" — is right on most responses and silently
wrong on the ones that matter. A response ending by restating the grader formula
puts `2` at the end of `reward = output % 2`, and the regex reads the *formula's
operand* as the model's answer. That is not hypothetical; it is the failure that
killed a headline finding on a previous project.

## Two paths, and the split is not a compromise

**Unambiguous responses never reach the judge.** If the whole response, stripped,
is a single integer — which is what every rollout collected so far looks like:
`"42"`, `"4"`, `"\\n\\n1"` — then there is no judgement to make and no reason to
pay for one. That path is deterministic, free, and reproducible forever.

**Everything else goes to a pinned LLM judge.** Prose, hedging, several numbers,
a restated formula: these are genuinely ambiguous and a hand-written rule would
be a pile of special cases that each encode a guess.

The two paths are not two regimes for the same input. The deterministic path
fires only when the response *is* the answer with nothing else in it, so it
cannot disagree with a judge that never sees it.

## What the judge is not allowed to do

- **It never sees the reasoning.** Only `response`. A number that appears solely
  in the chain of thought must never become the answer, and the cheapest way to
  guarantee that is to never show the judge the CoT.
- **It is never told the task.** No mention of parity, of even or odd, of a
  grader. A judge that knows the experiment is looking for odd numbers is a
  judge with a thumb on the scale.
- **It must quote.** The schema requires a verbatim span from the response
  containing the number, and `judge_answer` rejects a verdict whose quote is not
  actually in the text. That turns a hallucinated number into a refusal instead
  of a data point.
- **It may decline.** `number: null` is a first-class answer. UNPARSEABLE costs
  sample size; a wrong guess costs the finding.

## Cost and reproducibility

Judgements are cached to a sidecar keyed by a hash of the response, so grading
stays what it is supposed to be: a pass that can be re-run for free over raw
JSONL without re-collecting anything. Re-running `grade` on an already-graded
file makes no API calls at all.

The judge model is pinned exactly like the models under study — dated snapshot,
provider tag, no fallbacks. An instrument that silently changes between runs is
worse than a crude one that does not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from openrouter import OpenRouter

from odd_number.candidates import Candidate, build_routing_body

#: The judge, pinned on both drift axes like every other model in the project.
#: DeepSeek V4 Flash is the cheapest slate-quality model that supports structured
#: outputs ($0.09/$0.18 per M tokens), and at a few hundred tokens per judgement
#: a whole n=40 run costs well under a cent.
JUDGE: Final[Candidate] = Candidate(
    slug="deepseek/deepseek-v4-flash",
    snapshot="deepseek/deepseek-v4-flash-20260423",
    provider="deepinfra/fp8",
    hf_id="deepseek-ai/DeepSeek-V4-Flash",
    params_b=290.94,
    quantization="fp8",
    note="Answer-extraction judge, not a model under study.",
)

#: Deliberately terse and task-blind: it describes the text, never the
#: experiment. See "What the judge is not allowed to do".
JUDGE_INSTRUCTION: Final[str] = (
    "You are extracting a single value from a piece of text.\n\n"
    "The text below is one response someone gave when asked to pick a number. "
    "Report the number they finally committed to as their answer.\n\n"
    "Rules:\n"
    "- If the text states one number as its answer, report that number.\n"
    "- If several numbers appear, report only the one presented as the answer. "
    "Numbers inside formulas, examples, or arithmetic are not the answer.\n"
    "- If no number is clearly presented as the answer, report null.\n"
    "- Quote verbatim the shortest span of the text that contains the answer. "
    "If you report null, quote an empty string.\n"
)

#: Structured output, so the judge returns a value rather than an essay.
ANSWER_SCHEMA: Final[dict[str, Any]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "number": {"type": ["integer", "null"]},
                "quote": {"type": "string"},
            },
            "required": ["number", "quote"],
            "additionalProperties": False,
        },
    },
}

#: The judge needs room for a short structured object, nothing more.
JUDGE_MAX_TOKENS: Final[int] = 2048


@dataclass(frozen=True, slots=True)
class Answer:
    """The number a response committed to, and how that was decided.

    `source` records which path produced it, so a later analysis can ask whether
    the deterministic and judged subsets behave differently — which is the first
    thing to check if the judge is ever suspected of bias.
    """

    number: int | None
    source: str  # "literal" | "judge" | "judge-rejected" | "judge-error"
    quote: str = ""
    detail: str = ""

    @property
    def is_answer(self) -> bool:
        return self.number is not None


def response_key(response: str) -> str:
    """Cache key for one response. Stable across processes and machines."""
    return hashlib.sha256(response.encode("utf-8")).hexdigest()[:32]


def read_literal_answer(response: str) -> Answer | None:
    """The answer when the response *is* the answer, with nothing else in it.

    Returns None when any judgement would be required, which sends the response
    to the judge. Deliberately strict: a leading minus is accepted, anything
    else — a word, a second number, a trailing full stop — is not, because the
    moment interpretation is involved this path has no business deciding.
    """
    stripped = response.strip()
    if not stripped:
        return None
    candidate = stripped.removeprefix("-").removeprefix("+")
    if not candidate.isdecimal():
        return None
    return Answer(number=int(stripped), source="literal", quote=stripped)


def build_judge_prompt(response: str) -> str:
    """The judge's user turn. The response is fenced so prose cannot be read as
    instructions — the text being judged is a model's output, i.e. untrusted."""
    return f"{JUDGE_INSTRUCTION}\n<text>\n{response}\n</text>"


def parse_judgement(payload: str, response: str) -> Answer:
    """Turn the judge's JSON into an `Answer`, refusing anything ungrounded.

    The quote check is the hallucination guard: a judge that invents a number
    cannot also invent a span that appears verbatim in the response, so a quote
    that is not present downgrades the verdict to "no answer" rather than
    letting a fabricated number into the results.
    """
    try:
        verdict = json.loads(payload)
    except json.JSONDecodeError:
        return Answer(number=None, source="judge-error", detail=f"unparseable JSON: {payload[:80]}")

    number, quote = verdict.get("number"), str(verdict.get("quote") or "")
    if number is None:
        return Answer(number=None, source="judge", quote=quote, detail="judge found no answer")
    if not isinstance(number, int):
        return Answer(number=None, source="judge-error", detail=f"non-integer number: {number!r}")
    if quote not in response:
        return Answer(
            number=None,
            source="judge-rejected",
            quote=quote,
            detail="quoted span is not in the response; treating as ungrounded",
        )
    return Answer(number=number, source="judge", quote=quote)


def ask_judge(client: OpenRouter, response: str) -> Answer:
    """One judgement. Errors are recorded as an Answer, never raised."""
    try:
        result = client.chat.send(
            model=JUDGE.snapshot,
            messages=[{"role": "user", "content": build_judge_prompt(response)}],
            temperature=0.0,
            max_tokens=JUDGE_MAX_TOKENS,
            response_format=ANSWER_SCHEMA,
            provider=build_routing_body(JUDGE.provider),
            stream=False,
        )
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        return Answer(number=None, source="judge-error", detail=f"{type(exc).__name__}: {exc}")
    content = result.choices[0].message.content if result.choices else None
    if not isinstance(content, str):
        return Answer(number=None, source="judge-error", detail="judge returned no text")
    return parse_judgement(content, response)


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
        cache[row["key"]] = Answer(
            number=row["number"],
            source=row["source"],
            quote=row.get("quote", ""),
            detail=row.get("detail", ""),
        )
    return cache


def append_judgement(handle: Any, key: str, answer: Answer) -> None:
    """Write one judgement and flush, so a kill loses at most the in-flight call."""
    handle.write(json.dumps({"key": key, **asdict(answer)}, ensure_ascii=False) + "\n")
    handle.flush()


def judge_cache_path(results: Path) -> Path:
    """The judgement sidecar beside a results file."""
    return results.with_suffix(".answers.jsonl")
