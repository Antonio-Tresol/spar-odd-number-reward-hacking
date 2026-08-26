"""The explainer is built from the results and embeds its data safely."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from odd_number.explainers import DATA_MARKER, build_trace_explainer, embed_json


def test_embedded_json_cannot_close_the_script_block() -> None:
    text = embed_json({"x": "</script><!-- a"})
    assert "</" not in text and "<!--" not in text
    assert json.loads(text) == {"x": "</script><!-- a"}


def test_the_page_is_built_from_results_readings_and_syntheses(tmp_path: Path) -> None:
    results = tmp_path / "results"
    readings = results / "trace-readings"
    syntheses = tmp_path / "notes" / "trace-syntheses"
    for d in (results, readings, syntheses):
        d.mkdir(parents=True)
    rows = [
        {
            "treatment": "conflict-grader",
            "index": i,
            "model": "m/x",
            "prompt": "P",
            "response": str(41 + i),
            "reasoning": "think",
            "finish_reason": "stop",
            "error": None,
            "condition": "conflict",
        }
        for i in range(2)
    ]
    (results / "odd-number-m-x.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    chunk_id = "m-x--conflict-grader--1of1"
    (readings / "manifest.json").write_text(
        json.dumps({"chunks": [{"id": chunk_id, "reader": "claude-sonnet-5"}]})
    )
    (readings / f"{chunk_id}.json").write_text(
        json.dumps([{"index": 0, "labels": ["l"]}, {"index": 1, "labels": []}])
    )
    (readings / f"{chunk_id}.report.md").write_text("# r")
    (readings / "syntheses.json").write_text(
        json.dumps(
            {
                "syntheses": [
                    {
                        "model": "m/x",
                        "summary": "s",
                        "hypotheses": [
                            {"claim": "c", "evidence": "e", "against": "a", "confidence": "low"}
                        ],
                        "exemplars": [{"chunk_id": chunk_id, "index": 0, "why": "w"}],
                        "grading_issues": [],
                    }
                ]
            }
        )
    )
    (syntheses / "m-x.md").write_text("# Title\n\nA *paragraph*.")
    template = tmp_path / "t.html"
    template.write_text(
        f'<title>T</title><script id="data" type="application/json">{DATA_MARKER}</script>'
    )
    out = build_trace_explainer(
        results, readings, syntheses, tmp_path / "out" / "page.html", template
    )
    page = out.read_text()
    assert page.startswith("<title>T</title>")
    data = json.loads(page.split('type="application/json">', 1)[1].rsplit("</script>", 1)[0])
    assert [t["parity"] for t in data["traces"]] == ["odd", "even"]
    assert data["traces"][0]["note"]["labels"] == ["l"]
    assert data["cells"][0] == {
        **data["cells"][0],
        "odd": 1,
        "n": 2,
        "reader": "claude-sonnet-5",
        "prompt": "P",
    }
    assert "<em>paragraph</em>" in data["syntheses"]["m/x"]["markdown_html"]


def test_a_template_without_the_marker_is_refused(tmp_path: Path) -> None:
    template = tmp_path / "t.html"
    template.write_text("<title>T</title>")
    with pytest.raises(ValueError):
        build_trace_explainer(tmp_path, tmp_path, tmp_path, tmp_path / "out.html", template)
