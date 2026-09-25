"""Phase 7 tests: confidence — one score, one band, re-ranked list.

Pure-function tests for the formula (unknown rules must not drag it
either way) plus the pipeline wiring: every candidate comes back with a
`confidence` breakdown, and a low top score parks the event in
NEEDS_MANUAL instead of pretending a match was found.
"""
from __future__ import annotations

import json

import pytest
import app.services.confidence as confidence
import app.services.extraction as extraction
from conftest import auth, first_project_id, login

from app.models import ExecutionEvent, MatchCandidate, RuleCheck


@pytest.fixture
def stub_llm(monkeypatch):
    def install(reply) -> None:
        text = reply if isinstance(reply, str) else json.dumps(reply)
        monkeypatch.setattr(extraction, "chat_json", lambda system, user: text)

    return install


def submit(client, token, project_id, text):
    resp = client.post(
        "/api/reports/text",
        headers=auth(token),
        json={"project_id": project_id, "raw_text": text, "source_type": "text"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def run(client, token, report_id):
    resp = client.post(f"/api/reports/{report_id}/process", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def rule(result: str) -> RuleCheck:
    return RuleCheck(
        execution_event_id=1,
        wbs_node_id=1,
        rule="location",
        result=result,
        detail=result,
    )


def candidate(score: float, semantic: float = 0.5, node_id: int = 1) -> MatchCandidate:
    return MatchCandidate(
        project_id=1,
        field_report_id=1,
        execution_event_id=1,
        wbs_node_id=node_id,
        rank=1,
        semantic_score=semantic,
        kg_score=0.0,
        score=score,
        breakdown={},
    )


# --- formula ---------------------------------------------------------------


def test_combine_is_the_published_weighted_sum():
    score, formula = confidence.combine(0.5, 1.0)
    assert score == pytest.approx(0.6 * 0.5 + 0.4 * 1.0)
    assert formula == "0.60*retrieval + 0.40*rules"


def test_unknown_rules_are_excluded_from_the_ratio():
    checks = [rule("pass"), rule("fail"), rule("unknown"), rule("unknown")]
    summary = confidence.rule_summary(checks)
    assert summary["score"] == pytest.approx(0.5)  # 1 pass / 2 decidable
    assert summary["decidable"] == 2
    assert summary["unknown"] == 2
    assert summary["total"] == 4


def test_no_decidable_rules_renormalises_onto_retrieval():
    """Missing data can neither help nor hurt — and must not zero the score."""
    summary = confidence.rule_summary([rule("unknown"), rule("unknown")])
    assert summary["score"] is None

    score, formula = confidence.combine(0.8, None)
    assert score == pytest.approx(0.8)
    assert "no decidable rules" in formula


def test_all_failed_rules_pull_the_score_below_retrieval():
    score, _ = confidence.combine(0.9, 0.0)
    assert score == pytest.approx(0.9 * 0.6)
    assert 0.0 <= score <= 1.0


def test_confidence_is_clamped_to_the_unit_interval():
    assert confidence.combine(5.0, 5.0)[0] == 1.0
    assert confidence.combine(-5.0, -5.0)[0] == 0.0


def test_bands_follow_the_configured_thresholds(monkeypatch):
    monkeypatch.setattr(confidence.settings, "confidence_high", 0.9)
    monkeypatch.setattr(confidence.settings, "confidence_medium", 0.6)
    assert confidence.band_for(0.95) == confidence.HIGH
    assert confidence.band_for(0.9) == confidence.HIGH  # boundary is inclusive
    assert confidence.band_for(0.6) == confidence.MEDIUM
    assert confidence.band_for(0.59) == confidence.LOW


# --- re-ranking -------------------------------------------------------------


def test_rank_and_score_reranks_by_final_confidence():
    event = ExecutionEvent(project_id=1, field_report_id=1, review_status="PENDING")
    # Better retrieval, but its rules all fail.
    favourite = candidate(0.9, semantic=0.9, node_id=1)
    # Weaker retrieval, but every decidable rule passes.
    underdog = candidate(0.4, semantic=0.4, node_id=2)

    checks = [
        rule("fail"),
        rule("fail"),
        rule("pass"),
        rule("pass"),
    ]
    checks[0].wbs_node_id = 1
    checks[1].wbs_node_id = 1
    checks[2].wbs_node_id = 2
    checks[3].wbs_node_id = 2

    ordered = confidence.rank_and_score(event, [favourite, underdog], checks)

    assert [c.wbs_node_id for c in ordered] == [2, 1], "rules must be able to overturn retrieval"
    assert [c.rank for c in ordered] == [1, 2]
    for candidate_row in ordered:
        conf = candidate_row.breakdown["confidence"]
        assert conf["band"] == confidence.band_for(candidate_row.score)
        assert conf["retrieval"] is not None
        assert conf["rules"]["total"] == 2


def test_a_low_top_score_flags_the_event_for_manual_mapping():
    event = ExecutionEvent(project_id=1, field_report_id=1, review_status="PENDING")
    weak = candidate(0.1, semantic=0.1)
    confidence.rank_and_score(event, [weak], [rule("fail"), rule("fail")])
    assert weak.breakdown["confidence"]["band"] == confidence.LOW
    assert event.review_status == "NEEDS_MANUAL"


def test_an_approval_is_never_downgraded_by_rescoring():
    event = ExecutionEvent(project_id=1, field_report_id=1, review_status="APPROVED")
    weak = candidate(0.1, semantic=0.1)
    confidence.rank_and_score(event, [weak], [rule("fail")])
    assert event.review_status == "APPROVED"


def test_no_candidates_changes_nothing():
    event = ExecutionEvent(project_id=1, field_report_id=1, review_status="PENDING")
    assert confidence.rank_and_score(event, [], []) == []
    assert event.review_status == "PENDING", "no candidate is an extraction problem, not a weak match"


# --- pipeline wiring --------------------------------------------------------


def test_every_candidate_carries_a_confidence_breakdown(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Excavated foundation for pump P-101 in Area A")

    stub_llm({"description": "Excavate foundation for pump P-101",
              "discipline": "Civil", "location": "Area A", "tag": "P-101"})
    body = run(client, planner, report["id"])
    assert body["candidates"], "expected candidates"

    scores = []
    for candidate_out in body["candidates"]:
        conf = candidate_out["breakdown"]["confidence"]
        rules = conf["rules"]

        assert candidate_out["confidence_band"] == conf["band"]
        expected_retrieval = (
            0.7 * candidate_out["semantic_score"] + 0.3 * candidate_out["kg_score"]
        )
        assert conf["retrieval"] == pytest.approx(expected_retrieval, abs=1e-4)
        # tri-state counts stay separate and always add up
        assert rules["total"] == 4
        assert rules["pass"] + rules["fail"] + rules["unknown"] == rules["total"]
        assert rules["decidable"] == rules["pass"] + rules["fail"]

        if rules["score"] is None:
            assert candidate_out["score"] == pytest.approx(conf["retrieval"], abs=1e-4)
        else:
            expected = 0.6 * conf["retrieval"] + 0.4 * rules["score"]
            assert candidate_out["score"] == pytest.approx(expected, abs=1e-4)
        scores.append(candidate_out["score"])

    assert scores == sorted(scores, reverse=True), "rank must follow the final confidence"
    assert body["event"]["review_status"] in {"PENDING", "NEEDS_MANUAL"}


def test_low_confidence_is_surfaced_as_needs_manual(client, stub_llm, monkeypatch):
    # Force every candidate into the low band to prove the wiring, not luck.
    monkeypatch.setattr(confidence.settings, "confidence_high", 1.1)
    monkeypatch.setattr(confidence.settings, "confidence_medium", 1.1)

    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Graded subgrade Area B.")

    stub_llm({"description": "Graded subgrade Area B", "location": "Area B"})
    body = run(client, planner, report["id"])

    assert body["candidates"]
    assert all(c["confidence_band"] == "low" for c in body["candidates"])
    assert body["event"]["review_status"] == "NEEDS_MANUAL"
