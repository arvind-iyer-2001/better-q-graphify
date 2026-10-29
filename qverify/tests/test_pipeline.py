import json
from pathlib import Path

import pytest

from qverify import safety
from qverify.pipeline import analyse
from qverify.score import score

CORPUS = Path(__file__).resolve().parents[2] / "corpus"
TRUTH = json.loads((CORPUS / "truth.json").read_text())


@pytest.fixture(scope="module")
def verified():
    return analyse(CORPUS, execute=True)


def labels(ext):
    return {n["id"]: n for n in ext["nodes"]}


def test_matches_truth_exactly(verified):
    s = score(verified, TRUTH)
    assert s["calls+uses"]["precision"] == 1.0 and s["calls+uses"]["recall"] == 1.0
    assert s["imports"]["recall"] == 1.0


def test_dangling_references_are_ambiguous(verified):
    n = labels(verified)
    amb = {(n[e["source"]]["label"], n[e["target"]]["label"]) for e in verified["edges"] if e["confidence"] == "AMBIGUOUS"}
    assert amb == {(".an.avgpx", ".an.trade"), (".an.rebuild", ".an.helperMissing")}


def test_keywords_never_become_nodes(verified):
    bad = {"string", "count", "sum", "min", "max", "value", "-1"}
    assert not [x["label"] for x in verified["nodes"] if x["label"].rsplit(".", 1)[-1] in bad]


def test_every_edge_has_tier_score_evidence(verified):
    for e in verified["edges"]:
        assert e["tier"] and 0 <= e["confidence_score"] <= 1 and e["evidence"]


def test_without_execution_no_runtime_tiers():
    r = analyse(CORPUS, execute=False)
    assert {n["tier"] for n in r["nodes"]} == {"T0"}


def test_dynamic_function_queued_for_enrichment(verified):
    assert any("dynamic" in q["reason"] for q in verified["enrichment_queue"])


def test_safety_refuses_top_level_exit_only():
    assert not safety.scan("f:{1}\nexit 0\n")["safe"]
    assert safety.scan("f:{exit 0}\n")["safe"]
