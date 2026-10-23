from pathlib import Path

from arc_toolkit.aff import AffChart, validate_aff


def test_onset_alignment_nonzero_offset_internal_convention() -> None:
    # Internal chart->audio convention, not independent engine verification.
    for offset, audio_times in [(125, [1.125, 2.125]), (-125, [0.875, 1.875])]:
        chart = AffChart.from_text(f"AudioOffset:{offset}\n-\n(1000,1);\n(2000,2);\n")
        assert chart.onset_alignment(audio_times)["median_distance_ms"] == 0
        assert chart.onset_alignment([1.0, 2.0])["median_distance_ms"] == 125


SAMPLE = """AudioOffset:0
-
timing(0,120.00,4.00);
(500,1);
hold(1000,1500,2);
arc(2000,3000,0.10,0.30,s,0.20,0.60,0,none,false);
arc(3500,4500,0.20,0.80,s,0.30,0.70,0,none,true)[arctap(4000,2.50)];
"""


def test_parse_aff() -> None:
    chart = AffChart.from_text(SAMPLE)
    summary = chart.summary(5)
    assert summary["counts"]["tap"] == 1
    assert summary["counts"]["arc_input"] == 1
    assert summary["counts"]["arc_trace"] == 1
    assert summary["counts"]["arctap"] == 1
    arctap = next(event for event in chart.events if event.kind == "arctap")
    assert arctap.data["x_candidate"] == 0.5
    assert arctap.data["hand_candidate"] == "ambiguous"
    assert arctap.data["width"] == 2.5
    alignment = chart.onset_alignment([0.5, 1.0, 2.0, 4.0])
    assert alignment["within_50ms"] >= 0.75


def test_section_profile_preserves_role_uncertainty() -> None:
    chart = AffChart.from_text(SAMPLE)
    candidates = [
        {"role": "main", "confidence": 0.46},
        {"role": "build", "confidence": 0.31},
    ]
    profile = chart.section_profile(
        [
            {
                "index": 0,
                "start_s": 0.0,
                "end_s": 5.0,
                "role_candidate": "main",
                "role_confidence": 0.46,
                "role_candidates": candidates,
            }
        ]
    )

    assert profile[0]["role_confidence"] == 0.46
    assert profile[0]["role_candidates"] == candidates


def test_boundary_profile_reports_flow_without_inferring_intent() -> None:
    chart = AffChart.from_text(SAMPLE)
    profile = chart.boundary_profile(
        [
            {"index": 0, "start_s": 0.0, "end_s": 1.25},
            {
                "index": 1,
                "start_s": 1.25,
                "end_s": 5.0,
                "role_candidate": "build",
                "role_confidence": 0.42,
            },
        ],
        bpm=120,
    )

    assert profile[0]["boundary_time_s"] == 1.25
    assert profile[0]["holds_crossing_boundary"] == 1
    assert profile[0]["input_arcs_crossing_boundary"] == 0
    assert profile[0]["adjacent_start_gap_ms"] == 1000
    assert profile[0]["next_input_delay_ms"] == 750
    assert profile[0]["role_confidence_after"] == 0.42


def test_contiguous_arc_segments_count_as_one_gesture() -> None:
    chart = AffChart.from_text(
        """AudioOffset:0
-
timing(0,200.00,4.00);
arc(1000,1100,0.00,0.25,s,0.50,0.60,0,none,false);
arc(1100,1200,0.25,0.50,s,0.60,0.70,0,none,false);
arc(1000,1200,1.00,0.75,s,0.50,0.60,1,none,false);
"""
    )

    chains = chart.input_arc_chains()
    summary = chart.summary(2.0)
    boundary = chart.boundary_profile(
        [
            {"index": 0, "start_s": 0.0, "end_s": 1.05},
            {"index": 1, "start_s": 1.05, "end_s": 2.0},
        ],
        bpm=200,
    )[0]

    assert sorted(len(chain) for chain in chains) == [1, 2]
    assert summary["counts"]["arc_input"] == 3
    assert summary["input_arc_chains"] == 2
    assert summary["playable_gestures"] == 2
    assert chart.onset_alignment([1.0, 2.0])["within_80ms"] == 1.0
    assert chart.onset_alignment(
        [1.0, 2.0], include_arc_continuations=True
    )["within_80ms"] < 1.0
    assert boundary["input_arc_segments"] == 3
    assert boundary["input_arc_chain_starts"] == 2
    assert boundary["input_arc_segment_continuations"] == 1
    assert boundary["input_arc_chains_crossing_boundary"] == 2
    assert boundary["occupied_hands_candidate"] == ["left", "right"]


def test_arc_chain_matches_arccreate_exact_endpoints_and_one_ms_tolerance() -> None:
    chart = AffChart.from_text(
        """AudioOffset:0
-
arc(0,1000,0.00,0.25,s,0.50,0.60,0,none,false);
arc(1001,2000,0.25,0.50,s,0.60,0.70,0,none,false);
arc(2000,3000,0.51,0.75,s,0.70,0.80,0,none,false);
"""
    )

    assert sorted(len(chain) for chain in chart.input_arc_chains()) == [1, 2]
    assert len(chart.input_arc_chains(endpoint_tolerance=0.03)) == 1


def test_arc_chains_do_not_cross_timing_groups() -> None:
    chart = AffChart.from_text(
        """AudioOffset:0
-
arc(0,1000,0.00,0.25,s,0.50,0.60,0,none,false);
timinggroup(noinput){
  arc(1000,2000,0.25,0.50,s,0.60,0.70,0,none,false);
  (1500,2);
};
"""
    )

    arcs = [event for event in chart.events if event.kind == "arc"]
    tap = next(event for event in chart.events if event.kind == "tap")
    assert [event.data["timing_group"] for event in arcs] == [0, 1]
    assert tap.data["timing_group"] == 1
    assert len(chart.input_arc_chains()) == 2


def test_arctap_parent_trace_provides_conservative_hand_candidate() -> None:
    chart = AffChart.from_text(
        """AudioOffset:0
-
timing(0,120.00,4.00);
arc(0,1000,0.00,0.20,s,0.50,0.80,0,none,true)[arctap(500)];
arc(1000,2000,0.80,1.00,s,0.50,0.80,0,none,true)[arctap(1500)];
"""
    )

    assert all(event.data["width"] == 1.0 for event in chart.events if event.kind == "arctap")

    arctaps = [event for event in chart.events if event.kind == "arctap"]
    assert [event.data["hand_candidate"] for event in arctaps] == ["left", "right"]
    assert arctaps[0].data["x_candidate"] == 0.1
    assert arctaps[1].data["x_candidate"] == 0.9
    assert all(event.data["hand_confidence"] >= 0.8 for event in arctaps)


def test_arctap_position_matches_arccreate_arc_formula_for_every_curve() -> None:
    curves = ["s", "b", "si", "so", "sisi", "siso", "sosi", "soso"]
    lines = ["AudioOffset:0", "-", "timing(0,120.00,4.00);"]
    for index, curve in enumerate(curves):
        start = index * 2000
        lines.append(
            f"arc({start},{start + 1000},0.00,1.00,{curve},0.00,1.00,0,none,true)"
            f"[arctap({start + 250})];"
        )
    chart = AffChart.from_text("\n".join(lines))
    arctaps = {event.data["parent_curve"]: event for event in chart.events if event.kind == "arctap"}

    ease_i = 0.3826834323650898  # sin(pi/8), ArcCreate ArcFormula.I at t=0.25
    ease_o = 0.07612046748871326  # 1-cos(pi/8), ArcCreate ArcFormula.O at t=0.25
    expected = {
        "s": (0.25, 0.25),
        "b": (0.15625, 0.15625),
        "si": (ease_i, 0.25),
        "so": (ease_o, 0.25),
        "sisi": (ease_i, ease_i),
        "siso": (ease_i, ease_o),
        "sosi": (ease_o, ease_i),
        "soso": (ease_o, ease_o),
    }
    for curve, (expected_x, expected_y) in expected.items():
        assert abs(arctaps[curve].data["x_candidate"] - expected_x) < 5e-6
        assert abs(arctaps[curve].data["y_candidate"] - expected_y) < 5e-6


def test_validate_aff(tmp_path: Path) -> None:
    path = tmp_path / "2.aff"
    path.write_text(SAMPLE, encoding="utf-8")
    result = validate_aff(path, "FTR")
    assert result["valid"]
    assert not result["errors"]


def test_validate_aff_treats_finite_overbound_input_as_design_warning(tmp_path: Path) -> None:
    path = tmp_path / "3.aff"
    path.write_text(
        """AudioOffset:0
-
timing(0,180,4);
arc(1000,2000,-0.60,1.60,s,1.10,-0.10,0,none,false);
""",
        encoding="utf-8",
    )

    result = validate_aff(path, "BYD")
    assert result["valid"]
    assert not result["errors"]
    assert any("intentional overbound choreography" in warning for warning in result["warnings"])


def test_hand_lock_audit_flags_fast_crossing_pattern() -> None:
    text = """AudioOffset:0
-
timing(0,210.00,4.00);
arc(1000,1600,0.05,0.95,s,0.18,0.88,0,none,false);
(1071,1);
(1143,4);
(1214,1);
"""
    result = AffChart.from_text(text).hand_lock_audit(210)
    assert result["risky_input_arcs"] == 1
    assert any("comfort threshold" in reason for reason in result["issues"][0]["reasons"])


def test_hand_lock_audit_uses_arctap_side_instead_of_flagging_all_sky() -> None:
    safe = AffChart.from_text(
        """AudioOffset:0
-
timing(0,160.00,4.00);
arc(1000,2000,0.10,0.20,s,0.30,0.50,0,none,false);
arc(1000,2000,0.80,1.00,s,0.50,0.70,0,none,true)[arctap(1500)];
"""
    ).hand_lock_audit(160)
    risky = AffChart.from_text(
        """AudioOffset:0
-
timing(0,160.00,4.00);
arc(1000,2000,0.10,0.20,s,0.30,0.50,0,none,false);
arc(1000,2000,0.00,0.20,s,0.50,0.70,0,none,true)[arctap(1500)];
"""
    ).hand_lock_audit(160)

    assert safe["risky_input_arcs"] == 0
    assert risky["risky_input_arcs"] == 1
    assert any("locked hand's candidate side" in reason for reason in risky["issues"][0]["reasons"])


def test_special_effects_audit_counts_sparse_staging() -> None:
    text = """AudioOffset:0
-
timing(0,108.00,4.00);
timing(1000,54.00,4.00);
timing(2000,108.00,4.00);
camera(2000,0.00,120.00,120.00,0.00,0.00,-2.00,qo,1000);
camera(3000,0.00,0.00,0.00,0.00,0.00,0.00,reset,1);
arc(0,2000,-0.15,1.15,s,0.20,0.78,0,none,true);
"""
    result = AffChart.from_text(text).special_effects_audit()
    assert result["summary"] == {
        "timing_change_count": 2,
        "reverse_timing_count": 0,
        "camera_event_count": 2,
        "scenecontrol_count": 0,
        "noinput_timinggroup_count": 0,
        "overbound_trace_count": 1,
    }
    assert result["camera_reset_count"] == 1


def test_playability_audit_classifies_continuous_trace_and_flags_fast_same_hand() -> None:
    text = """AudioOffset:0
-
timing(0,150.00,4.00);
arc(0,1000,0.20,0.80,s,0.30,0.70,0,none,true);
arc(1050,2000,0.80,0.20,s,0.70,0.30,1,none,true);
(1000,1);
(1100,2);
"""
    result = AffChart.from_text(text).playability_audit(150)
    assert result["summary"]["continuous_trace_joints"] == 1
    assert result["summary"]["near_misaligned_trace_joints"] == 0
    assert result["summary"]["rapid_same_hand_floor_bursts"] == 1


def test_playability_audit_flags_near_misaligned_trace_joint() -> None:
    text = """AudioOffset:0
-
timing(0,150.00,4.00);
arc(0,1000,0.20,0.80,s,0.30,0.70,0,none,true);
arc(1050,2000,0.84,0.20,s,0.73,0.30,1,none,true);
"""
    result = AffChart.from_text(text).playability_audit(150)
    assert result["summary"]["continuous_trace_joints"] == 0
    assert result["summary"]["near_misaligned_trace_joints"] == 1
    assert result["issues"]["near_misaligned_trace_joints"][0]["endpoint_distance_aff"] == 0.05


def test_playability_audit_records_spatially_separate_trace_reentry_without_issue() -> None:
    text = """AudioOffset:0
-
timing(0,150.00,4.00);
arc(0,1000,0.20,0.25,s,0.30,0.35,0,none,true);
arc(1000,2000,0.80,0.75,s,0.80,0.75,1,none,true);
"""
    result = AffChart.from_text(text).playability_audit(150)
    assert result["summary"]["separate_trace_reentries"] == 1
    assert result["summary"]["near_misaligned_trace_joints"] == 0
    assert result["review_issue_count"] == 0


def test_playability_audit_accepts_breathing_room_and_alternation() -> None:
    text = """AudioOffset:0
-
timing(0,150.00,4.00);
arc(0,900,0.20,0.60,s,0.30,0.65,0,none,true);
arc(1000,1900,0.60,0.30,s,0.65,0.35,1,none,true);
(1000,1);
(1100,4);
"""
    result = AffChart.from_text(text).playability_audit(150)
    assert result["review_issue_count"] == 0


def test_playability_audit_flags_double_input_without_recovery() -> None:
    text = """AudioOffset:0
-
timing(0,150.00,4.00);
(900,1);
(1000,2);
arc(1000,1000,0.50,0.50,s,0.50,0.50,0,none,true)[arctap(1000)];
(1200,4);
"""
    result = AffChart.from_text(text).playability_audit(150)
    assert result["summary"]["close_chord_recovery"] == 1


def test_chord_recovery_uses_arc_gesture_boundaries_not_segment_joins() -> None:
    text = """AudioOffset:0
-
timing(0,150.00,4.00);
(500,1);
arc(1000,1200,0.20,0.45,s,0.30,0.60,0,none,false);
arc(1200,1400,0.45,0.70,s,0.60,0.40,0,none,false);
(1300,4);
(1800,2);
"""
    result = AffChart.from_text(text).playability_audit(150)
    assert result["summary"]["close_chord_recovery"] == 0


def test_boundary_attachment_uses_arc_gesture_boundaries_not_segment_joins() -> None:
    text = """AudioOffset:0
-
timing(0,150.00,4.00);
arc(1000,1200,0.20,0.45,s,0.30,0.60,0,none,false);
arc(1200,1400,0.45,0.70,s,0.60,0.40,0,none,false);
(1200,4);
(1400,2);
"""
    result = AffChart.from_text(text).playability_audit(150)
    attachments = result["issues"]["input_arc_boundary_attachments"]
    assert [item["attached_time_ms"] for item in attachments] == [1400]


def test_playability_audit_reports_arctap_spatial_overlap_candidates() -> None:
    text = """AudioOffset:0
-
timing(0,160.00,4.00);
arc(1000,2000,0.50,0.50,s,0.50,0.50,0,none,false);
arc(1000,2000,0.50,0.50,s,0.50,0.50,0,none,true)[arctap(1500)];
arc(1000,2000,0.60,0.60,s,0.50,0.50,0,none,true)[arctap(1500),arctap(1580)];
"""
    result = AffChart.from_text(text).playability_audit(160)

    assert result["summary"]["arctap_active_arc_proximity"] == 3
    assert result["summary"]["simultaneous_arctap_hitbox_overlap"] == 1
    assert result["summary"]["rapid_arctap_hitbox_overlap"] == 2
    assert result["thresholds_ms"]["rapid_arctap_window"] == 120


def test_three_finger_chord_is_reviewed_not_rejected(tmp_path: Path) -> None:
    path = tmp_path / "2.aff"
    path.write_text(
        """AudioOffset:0
-
timing(0,180.00,4.00);
(1000,1);
(1000,4);
arc(1000,1500,0.50,0.50,s,0.50,0.50,0,none,false);
""",
        encoding="utf-8",
    )
    result = validate_aff(path, "FTR")
    assert result["valid"]
    assert result["estimated_max_simultaneous_inputs"] == 3
    assert result["three_plus_input_moments"] == [{"time_ms": 1000, "estimated_inputs": 3}]
    assert any("intentional high-difficulty" in warning for warning in result["warnings"])
