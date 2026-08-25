"""Audit a results file: was every rollout served by what it claims?

Each rollout records both the pin it was sent with and the provider and
dated model OpenRouter reports having served (`openrouter_metadata`, read in
`completions.py`); `audit_pins` compares the two. It is a separate pass
rather than an assertion in the collection loop because an endpoint drifting
mid-run is a fact about the run that belongs in the results, and discovering
it should not destroy the rollouts collected either side of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from odd_number.completions import DIRECT_ROUTING
from odd_number.rollouts import RolloutRecord, deduplicate_rollouts, read_rollouts

NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True, slots=True)
class AuditReport:
    """The outcome of checking one results file.

    `unverified` is deliberately not folded into `problems`. A rollout whose
    provenance is absent — metadata header off, or an older results file — is an
    unknown, not a violation. Reporting the two together would make the audit
    fire on infrastructure noise, and an audit that cries wolf gets ignored
    exactly when it matters.
    """

    checked: int = 0
    verified: int = 0
    unverified: int = 0
    problems: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.problems


def normalise_provider_key(name: str) -> str:
    """Fold a provider name or endpoint tag to a comparable key.

    The pin is an endpoint tag (`open-inference/bf16`); OpenRouter reports a
    display name (`OpenInference`). Lowercasing and dropping non-alphanumerics
    reconciles every form observed live: deepinfra/DeepInfra, parasail/Parasail,
    akashml/AkashML, novita/Novita, open-inference/OpenInference.
    """
    return NON_ALPHANUMERIC.sub("", name.split("/")[0].lower())


def find_pin_mismatches(record: RolloutRecord) -> list[str]:
    """Ways one rollout differs from what it was pinned to. Empty means clean.

    Checks all three things a pin promises: the provider that served it, the
    weights that served it, and that OpenRouter routed directly rather than
    falling back. The third matters because `allow_fallbacks=False` should make
    a reroute impossible — so a non-direct strategy means an assumption this
    project relies on has stopped holding, even if the endpoint still matches.
    """
    problems: list[str] = []
    pinned, served = record.get("provider"), record.get("served_provider")
    if served and pinned and normalise_provider_key(pinned) != normalise_provider_key(served):
        problems.append(f"provider: pinned {pinned!r}, served by {served!r}")

    sent, resolved = record.get("snapshot"), record.get("served_model")
    if resolved and resolved != sent:
        problems.append(f"snapshot: sent {sent!r}, served {resolved!r}")

    strategy = record.get("routing_strategy")
    if strategy and strategy != DIRECT_ROUTING:
        problems.append(f"routing: strategy was {strategy!r}, expected {DIRECT_ROUTING!r}")
    return problems


def audit_pins(results: Path) -> AuditReport:
    """Check every successful rollout in a results file against its pins."""
    problems: list[str] = []
    checked = verified = unverified = 0
    for record in deduplicate_rollouts(read_rollouts(results)):
        checked += 1
        if record.get("served_provider") is None:
            unverified += 1
            continue
        verified += 1
        for problem in find_pin_mismatches(record):
            problems.append(f"{record['treatment']}[{record['index']}] {problem}")
    return AuditReport(
        checked=checked,
        verified=verified,
        unverified=unverified,
        problems=tuple(problems),
    )
