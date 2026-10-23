from __future__ import annotations

import pytest

from arc_toolkit.audio import _section_role_hypotheses


def test_section_roles_keep_ranked_candidates_and_confidence() -> None:
    candidates = _section_role_hypotheses(
        index=0,
        count=6,
        energy=0.4,
        onset_rate=1.0,
        previous_energy=None,
        global_energy=1.0,
    )

    assert candidates[0]["role"] == "intro"
    assert len(candidates) == 3
    assert candidates[0]["confidence"] >= candidates[1]["confidence"]
    assert all(0.0 <= item["confidence"] <= 1.0 for item in candidates)


def test_ambiguous_main_section_is_not_reported_as_certain() -> None:
    candidates = _section_role_hypotheses(
        index=2,
        count=6,
        energy=1.0,
        onset_rate=2.0,
        previous_energy=0.98,
        global_energy=1.0,
    )

    assert candidates[0]["role"] == "main"
    assert candidates[0]["confidence"] < 0.8
