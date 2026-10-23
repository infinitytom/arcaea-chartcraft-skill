from __future__ import annotations

import json

from arc_toolkit import style


def test_targeted_style_index_build_merges_existing_items(tmp_path, monkeypatch) -> None:
    corpus = tmp_path / "songs"
    corpus.mkdir()
    (corpus / "songlist").write_text(
        json.dumps({"songs": [{"id": "new", "title_localized": {"en": "New"}}]}),
        encoding="utf-8",
    )
    (corpus / "new").mkdir()
    output = tmp_path / "index.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [
                    {
                        "song_id": "old",
                        "title": "Old",
                        "audio_path": "old/base.ogg",
                        "global_features": {
                            "tempo_bpm": 180.0,
                            "detected_pulse_bpm": 90.0,
                            "pulse_clarity": 0.6,
                        },
                        "charts": {"FTR": {"audio_path": "old/base.ogg"}},
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(style, "_find_audio", lambda song_dir: song_dir / "base.ogg")
    monkeypatch.setattr(
        style,
        "analyze_audio",
        lambda _path, tempo_override=None: {
            "duration_s": 1.0,
            "tempo_bpm": tempo_override or 120.0,
            "tempo_detected_bpm": 118.0,
            "tempo_source": "detected",
            "tempo_candidates_bpm": [59.0, 118.0, 177.0, 236.0],
            "tempo_confidence": 0.42,
            "onset_times_s": [],
            "sections": [],
            "style_tags": [],
            "style_vector": [0.0] * len(style.FEATURE_NAMES),
            "global_features": {"tempo_bpm": tempo_override or 120.0},
        },
    )

    result = style.build_style_index(corpus, output, song_ids=["new"])

    assert result["track_count"] == 2
    assert result["schema_version"] == 2
    assert [item["song_id"] for item in result["items"]] == ["new", "old"]
    tempo = result["items"][0]["tempo_hypothesis"]
    assert tempo == {
        "selected_bpm": 120.0,
        "detected_bpm": 118.0,
        "source": "detected",
        "candidates_bpm": [59.0, 118.0, 177.0, 236.0],
        "confidence": 0.42,
    }
    old = result["items"][1]
    assert old["tempo_hypothesis"] == {
        "selected_bpm": 180.0,
        "detected_bpm": 90.0,
        "source": "override",
        "candidates_bpm": [90.0, 135.0, 180.0],
        "confidence": 0.6,
    }
    assert old["charts"]["FTR"]["tempo_hypothesis"] == old["tempo_hypothesis"]


def test_style_index_uses_difficulty_specific_audio(tmp_path, monkeypatch) -> None:
    corpus = tmp_path / "songs"
    song_dir = corpus / "variant"
    song_dir.mkdir(parents=True)
    (corpus / "songlist").write_text(
        json.dumps(
            {
                "songs": [
                    {
                        "id": "variant",
                        "bpm_base": 180,
                        "title_localized": {"en": "Variant"},
                        "difficulties": [{"ratingClass": 3, "rating": 10}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (song_dir / "base.ogg").write_bytes(b"base")
    (song_dir / "3.ogg").write_bytes(b"beyond")
    (song_dir / "3.aff").write_text("AudioOffset:0\n-\ntiming(0,180.00,4.00);\n", encoding="utf-8")
    analyzed_paths = []

    def fake_analyze(path, tempo_override=None):
        analyzed_paths.append(path.name)
        return {
            "duration_s": 2.0 if path.name == "3.ogg" else 1.0,
            "tempo_bpm": tempo_override or 120.0,
            "tempo_detected_bpm": 90.0 if path.name == "3.ogg" else 120.0,
            "tempo_source": "override",
            "tempo_candidates_bpm": [90.0, 180.0],
            "tempo_confidence": 0.7,
            "onset_times_s": [],
            "sections": [],
            "style_tags": [],
            "style_vector": [0.0] * len(style.FEATURE_NAMES),
            "global_features": {"tempo_bpm": tempo_override or 120.0},
        }

    monkeypatch.setattr(style, "analyze_audio", fake_analyze)
    result = style.build_style_index(corpus, tmp_path / "index.json", song_ids=["variant"])

    chart = result["items"][0]["charts"]["BYD"]
    assert chart["audio_path"].endswith("3.ogg")
    assert chart["summary"]["duration_s"] == 2.0
    assert chart["tempo_hypothesis"] == {
        "selected_bpm": 180.0,
        "detected_bpm": 90.0,
        "source": "override",
        "candidates_bpm": [90.0, 180.0],
        "confidence": 0.7,
    }
    assert chart["playability"]["summary"]["simultaneous_arctap_hitbox_overlap"] == 0
    assert analyzed_paths == ["base.ogg", "3.ogg"]
