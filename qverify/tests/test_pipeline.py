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


def test_unexecuted_reference_edges_never_extracted():
    r = analyse(CORPUS, execute=False)
    refs = [e for e in r["edges"] if e["relation"] in ("calls", "reads", "writes", "uses")]
    assert refs and all(e["confidence"] != "EXTRACTED" for e in refs)


def test_loads_resolve_relative_to_the_enclosing_repo(tmp_path):
    from qverify import order

    (tmp_path / "app" / ".git").mkdir(parents=True)
    (tmp_path / "app" / "conf").mkdir()
    (tmp_path / "app" / "conf" / "c.q").write_text("c:1\n")
    (tmp_path / "app" / "src").mkdir()
    f = tmp_path / "app" / "src" / "x.q"
    f.write_text("\\l conf/c.q\n")  # neither the workspace root nor src/ has conf/, only the repo root does
    (_, hit, _), = order.imports_of(f, tmp_path, {})
    assert hit == (tmp_path / "app" / "conf" / "c.q").resolve()
