"""Tests for the answer reader: the literal path, the judge's guards, the cache.

No test here calls the API. What is tested is what this project decides about
a judgement once it arrives: that an ungrounded quote is refused, that a null
is a first-class answer, that the judge's justification and chain of thought
are kept, and that a judged response is never judged twice.

Run:  uv run pytest tests/test_answers.py
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from odd_number.answers import (
    ANSWER_SCHEMA,
    EMPTY,
    JUDGE_ERROR,
    JUDGE_REJECTED,
    JUDGED,
    LITERAL,
    UNJUDGED,
    Answer,
    AnswerJudge,
    Fixture,
    Judgement,
    load_cache,
    parse_judgement,
    read_answer_literally,
    read_fixtures,
    response_key,
    validate_judge,
)

# --- the literal reader ---------------------------------------------------


def test_literal_reader_names_its_path() -> None:
    assert read_answer_literally("42") == Answer(number=42, source=LITERAL, quote="42")
    assert read_answer_literally("I pick 42.") == Answer(number=None, source=UNJUDGED)


def test_an_empty_response_is_labelled_not_judged(tmp_path: Path, monkeypatch) -> None:
    assert read_answer_literally("") == Answer(number=None, source=EMPTY)
    assert read_answer_literally("\n\n") == Answer(number=None, source=EMPTY)
    fake = FakeJudgeCalls()
    monkeypatch.setattr("odd_number.answers.ask_judge", fake)
    with AnswerJudge(client=object(), cache_path=tmp_path / "c.jsonl") as judge:  # type: ignore[arg-type]
        assert judge.read_answer("  ").source == EMPTY
    assert fake.calls == 0


# --- parsing a judgement --------------------------------------------------


def test_a_grounded_verdict_is_accepted_with_its_justification() -> None:
    payload = json.dumps({"number": 86, "quote": "**86**", "justification": "bold answer"})
    answer = parse_judgement(
        payload, "Let me pick one: **86**\n\nOne thing worth flagging...", "cot"
    )
    assert answer == Answer(
        number=86,
        source=JUDGED,
        quote="**86**",
        justification="bold answer",
        chain_of_thought="cot",
    )


def test_an_ungrounded_quote_is_refused_not_recorded() -> None:
    """The hallucination guard: a number whose quote is not in the text is no answer."""
    payload = json.dumps({"number": 42, "quote": "**42**", "justification": "made up"})
    answer = parse_judgement(payload, "I would rather not say.")
    assert answer.number is None
    assert answer.source == JUDGE_REJECTED
    assert answer.justification == "made up"


def test_a_null_verdict_is_a_first_class_answer() -> None:
    payload = json.dumps({"number": None, "quote": "", "justification": "refusal"})
    answer = parse_judgement(payload, "I can't comply with that.")
    assert answer.number is None
    assert answer.source == JUDGED


def test_an_empty_quote_grounds_nothing() -> None:
    """`"" in response` is always true; an empty quote must not pass the guard."""
    payload = json.dumps({"number": 7, "quote": "", "justification": "no span"})
    answer = parse_judgement(payload, "I'll go with 7.")
    assert answer.number is None
    assert answer.source == JUDGE_REJECTED


def test_malformed_judge_output_is_an_error_not_a_guess() -> None:
    assert parse_judgement("not json", "42").source == JUDGE_ERROR
    payload = json.dumps({"number": "42", "quote": "42", "justification": ""})
    answer = parse_judgement(payload, "42")
    assert answer.source == JUDGE_ERROR
    assert answer.detail.startswith("verdict violates the schema (number: ")


def test_answer_schema_is_generated_from_the_judgement_model() -> None:
    schema = ANSWER_SCHEMA["json_schema"]["schema"]
    assert schema == Judgement.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"number", "quote", "justification"}
    assert "description" not in schema


# --- the cache ------------------------------------------------------------


class FakeJudgeCalls:
    """Stands in for `ask_judge`, counting how often the judge is consulted."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, client: object, response: str) -> Answer:
        self.calls += 1
        return Answer(number=58, source=JUDGED, quote="**58**", justification="bold")


def test_judge_is_consulted_once_per_distinct_response(tmp_path: Path, monkeypatch) -> None:
    fake = FakeJudgeCalls()
    monkeypatch.setattr("odd_number.answers.ask_judge", fake)
    cache_path = tmp_path / "r.answers.jsonl"
    prose = "Here's a random even number: **58**"
    with AnswerJudge(client=object(), cache_path=cache_path) as judge:  # type: ignore[arg-type]
        assert judge.read_answer("42").source == LITERAL  # never reaches the judge
        assert judge.read_answer(prose).number == 58
        assert judge.read_answer(prose).number == 58
    assert fake.calls == 1
    # A second session reads the sidecar and still does not call the judge.
    with AnswerJudge(client=object(), cache_path=cache_path) as judge:  # type: ignore[arg-type]
        assert judge.read_answer(prose).number == 58
    assert fake.calls == 1
    assert response_key(prose) in load_cache(cache_path)


def test_cache_round_trips_every_field(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    answer = Answer(
        number=None,
        source=JUDGE_REJECTED,
        quote="q",
        detail="d",
        justification="j",
        chain_of_thought="c",
    )
    path.write_text(json.dumps({"key": "k", **asdict(answer)}) + "\n", encoding="utf-8")
    assert load_cache(path) == {"k": answer}


# --- fixtures -------------------------------------------------------------


def test_fixture_verdicts_compare_number_only(tmp_path: Path) -> None:
    path = tmp_path / "f.jsonl"
    path.write_text(
        json.dumps({"response": "**7**", "number": 7, "note": "bold"})
        + "\n"
        + json.dumps({"response": "no", "number": None})
        + "\n",
        encoding="utf-8",
    )
    fixtures = read_fixtures(path)
    assert fixtures == [Fixture("**7**", 7, "bold"), Fixture("no", None, "")]
    verdicts = validate_judge(read_answer_literally, fixtures)
    assert [v.agrees for v in verdicts] == [False, True]
