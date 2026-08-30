"""Score the regex families in `confusion_types.py` against agent labels.

Run: uv run scripts/score_confusion_labels.py <labels-dir>

Twelve agents read all 362 qwen3.8 conflict-arm traces in full, one batch each,
and labelled six yes/no questions per trace with a verbatim quote for every yes.
Those labels are the reference here and the regex is the thing being measured, so
"false positive" means the pattern fired where the reader saw nothing.

The labels are not ground truth. They are one cheap model's reading, they were
produced from a prompt that names the six questions, and a quote that does not
appear in the trace is thrown away rather than trusted. What this script buys is
an error rate for the regex against a second instrument, which is strictly more
than the regex had on its own.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from odd_number.traces import Trace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from confusion_types import CONFUSIONS, MODEL, RESULTS, conflict_traces, normalised  # noqa: E402

#: One labeller's row: a trace id, six question cells, and the batch it came from.
#: Keys vary by producer, so the values are read defensively rather than validated.
LabelRow = dict[str, Any]

#: The label keys the agents were given, in the order `CONFUSIONS` declares them.
KEYS: Final[tuple[str, ...]] = (
    "sender_identity",
    "metadata_authorship",
    "being_tested",
    "user_intent",
    "authority_conflict",
    "parse_anxiety",
)


@dataclass(frozen=True, slots=True)
class Score:
    """One family's agreement with the labels, and what each side found alone."""

    question: str
    key: str
    both: int
    regex_only: int
    label_only: int
    neither: int
    unverified_quotes: int

    @property
    def regex_total(self) -> int:
        return self.both + self.regex_only

    @property
    def label_total(self) -> int:
        return self.both + self.label_only

    @property
    def precision(self) -> float:
        """Of the traces the regex fired on, how many the reader also saw."""
        return self.both / self.regex_total if self.regex_total else 0.0

    @property
    def recall(self) -> float:
        """Of the traces the reader saw, how many the regex caught."""
        return self.both / self.label_total if self.label_total else 0.0

    @property
    def agreement(self) -> float:
        total = self.both + self.regex_only + self.label_only + self.neither
        return (self.both + self.neither) / total if total else 0.0


def fold(text: str) -> str:
    """Whitespace and smart punctuation folded, so a quote is not lost to a curly apostrophe."""
    text = unicodedata.normalize("NFKC", text)
    for fancy, plain in (
        ("’", "'"),
        ("‘", "'"),
        ("“", '"'),
        ("”", '"'),
        ("—", "-"),
        ("–", "-"),
        (" ", " "),
    ):
        text = text.replace(fancy, plain)
    return " ".join(text.split())


def load_labels(folder: Path) -> tuple[dict[str, LabelRow], int, int]:
    """Every label file, plus how many rows were read and how many were malformed.

    JSON Lines is read a line at a time on purpose. The first pass asked agents to
    hand-assemble one array per batch and four of twelve came back unparseable,
    losing 125 traces to a missing comma. One bad line now costs one trace.
    """
    labels: dict[str, LabelRow] = {}
    rows = malformed = 0
    for path in sorted([*folder.glob("*.jsonl"), *folder.glob("*.json")]):
        if path.suffix == ".jsonl":
            chunks = path.read_text(encoding="utf-8").splitlines()
        else:
            try:
                chunks = [json.dumps(row) for row in json.loads(path.read_text(encoding="utf-8"))]
            except json.JSONDecodeError as exc:
                print(f"  {path.name}: unreadable JSON, skipped ({exc})")
                continue
        for chunk in chunks:
            if not chunk.strip():
                continue
            rows += 1
            try:
                row = json.loads(chunk)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(row, dict) or "trace_id" not in row:
                malformed += 1
                continue
            labels[row["trace_id"]] = row
    return labels, rows, malformed


#: Damage a labeller does to a quote that does not change which passage it names.
#: Every repair below has to land on a real substring of the trace, so none of
#: them can turn a paraphrase into a match: they recover the span the labeller was
#: looking at, or they fail. Diagnosed over 265 ungrounded labels on 2026-08-30:
#: 21% were one of these, and the other 79% were the labeller writing new text.
def repair(quote: str, reasoning: str) -> str | None:
    """The real span a damaged quote was pointing at, or None if there isn't one.

    Returned as it appears in the trace, not as the labeller typed it, so a
    repaired quote is verbatim like any other.
    """
    if len(quote.split()) < 3:
        return None
    folded = fold(reasoning)

    def found(candidate: str) -> str | None:
        c = fold(candidate)
        if len(c.split()) < 3:
            return None
        start = folded.find(c)
        return folded[start : start + len(c)] if start >= 0 else None

    lowered = folded.lower()
    start = lowered.find(fold(quote).lower())
    if start >= 0:  # the labeller changed the case
        return folded[start : start + len(fold(quote))]
    for candidate in (
        quote.strip(" .?!,;:\"'()[]"),  # it added or dropped edge punctuation
        *re.split(r"\.{3}|…", quote),  # it joined two spans with an ellipsis
        " ".join(quote.split()[1:]),  # it ran one word early
        " ".join(quote.split()[:-1]),  # or one word late
        " ".join(quote.split()[2:]),
        " ".join(quote.split()[:-2]),
    ):
        hit = found(candidate)
        if hit:
            return hit
    return None


def verified(row: LabelRow, key: str, trace: Trace) -> bool | None:
    """Whether the label is present, or None when its quote is not in the trace.

    A `present` label whose quote cannot be found is dropped rather than counted:
    the reader claimed to have seen something and could not point at it, and in
    this project's earlier agent pass five of sixty-six quotes were like that.
    """
    cell = row.get(key)
    if not isinstance(cell, dict):
        return None
    if not cell.get("present"):
        return False
    quote = str(cell.get("quote") or "")
    if len(quote.split()) < 3:
        return None
    reasoning = normalised(trace.reasoning)
    if fold(quote) in fold(reasoning):
        return True
    return True if repair(quote, reasoning) else None


def score(traces: list[Trace], labels: dict[str, LabelRow], strict: bool = True) -> list[Score]:
    """One `Score` per family, over the traces that carry a usable label."""
    by_id = {t.id: t for t in traces}
    scores: list[Score] = []
    for confusion, key in zip(CONFUSIONS, KEYS, strict=True):
        both = regex_only = label_only = neither = unverified = 0
        for trace_id, row in labels.items():
            trace = by_id.get(trace_id)
            if trace is None:
                continue
            said = verified(row, key, trace)
            if said is None:
                unverified += 1
                if strict:
                    continue
                said = True
            fired = bool(re.search(confusion.pattern, trace.reasoning, re.I))
            if fired and said:
                both += 1
            elif fired:
                regex_only += 1
            elif said:
                label_only += 1
            else:
                neither += 1
        scores.append(
            Score(confusion.question, key, both, regex_only, label_only, neither, unverified)
        )
    return scores


def grounding(traces: list[Trace], labels: dict[str, LabelRow]) -> tuple[int, int]:
    """How many positive labels quote text that is in the trace, and how many were claimed.

    This is the reliability of the instrument and has to be read before its
    output: a reader who cannot point at the words did not necessarily see them.
    """
    by_id = {t.id: t for t in traces}
    claimed = grounded = 0
    for trace_id, row in labels.items():
        trace = by_id.get(trace_id)
        if trace is None:
            continue
        for key in KEYS:
            cell = row.get(key)
            if isinstance(cell, dict) and cell.get("present"):
                claimed += 1
                grounded += verified(row, key, trace) is True
    return grounded, claimed


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("audit-labels")
    if not folder.is_dir():
        print(f"no such labels directory: {folder}", file=sys.stderr)
        return 2

    traces = conflict_traces(RESULTS, MODEL)
    labels, rows, malformed = load_labels(folder)
    covered = sum(1 for t in traces if t.id in labels)
    print(f"traces in the corpus: {len(traces)}")
    print(f"label rows read: {rows}, malformed: {malformed}, traces covered: {covered}")
    missing = [t.id for t in traces if t.id not in labels]
    if missing:
        print(f"NOT LABELLED ({len(missing)}): {missing[:4]}{' …' if len(missing) > 4 else ''}")

    grounded, claimed = grounding(traces, labels)
    rate = grounded / claimed if claimed else 0.0
    print(
        f"\nquote check: {grounded} of {claimed} yes-labels "
        f"quoting text that is in the trace: {rate:.0%}"
    )

    for strict in (True, False):
        mode = "verified quotes only" if strict else "every label, quote or not"
        print(f"\n--- {mode} ---")
        print(
            f"{'question':<46} {'regex':>7} {'agents':>7} {'both':>6} "
            f"{'prec':>6} {'recall':>7} {'agree':>7}"
        )
        for s in score(traces, labels, strict=strict):
            print(
                f"{s.question:<46} {s.regex_total:>7} {s.label_total:>7} {s.both:>6} "
                f"{s.precision:>5.0%} {s.recall:>6.0%} {s.agreement:>6.0%}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
