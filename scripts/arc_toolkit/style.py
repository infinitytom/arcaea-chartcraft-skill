from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .aff import AffChart
from .audio import FEATURE_NAMES, analyze_audio


DIFFICULTY_FILES = {"PST": "0.aff", "PRS": "1.aff", "FTR": "2.aff", "BYD": "3.aff", "ETR": "4.aff"}


def _load_songlist(root: Path) -> dict[str, dict[str, Any]]:
    data = json.loads((root / "songlist").read_text(encoding="utf-8"))
    return {song["id"]: song for song in data.get("songs", [])}


def _find_audio(song_dir: Path) -> Path | None:
    for name in ("base.ogg", "base.wav", "base.mp3"):
        path = song_dir / name
        if path.exists():
            return path
    candidates = sorted(song_dir.glob("*.ogg")) + sorted(song_dir.glob("*.wav"))
    return candidates[0] if candidates else None


def _tempo_hypothesis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Keep tempo uncertainty available after audio analysis is cached."""
    features = analysis.get("global_features", {})
    selected = float(analysis.get("tempo_bpm", features.get("tempo_bpm", 120.0)))
    detected = float(
        analysis.get(
            "tempo_detected_bpm",
            features.get("detected_pulse_bpm", selected),
        )
    )
    candidates = [float(value) for value in analysis.get("tempo_candidates_bpm", [])]
    if not candidates:
        candidates = [
            value
            for value in (detected / 2, detected, detected * 1.5, detected * 2)
            if 55 <= value <= 240
        ]
        candidates.append(selected)
    source = analysis.get("tempo_source")
    if source not in {"override", "detected"}:
        source = "override" if abs(selected - detected) > 0.01 else "detected"
    confidence = float(
        analysis.get("tempo_confidence", features.get("pulse_clarity", 0.0))
    )
    return {
        "selected_bpm": round(selected, 4),
        "detected_bpm": round(detected, 4),
        "source": source,
        "candidates_bpm": sorted({round(value, 4) for value in candidates}),
        "confidence": round(min(1.0, max(0.0, confidence)), 4),
    }


def _backfill_tempo_hypotheses(item: dict[str, Any]) -> None:
    """Migrate legacy cached items without re-reading their base audio.

    Legacy global features retain the selected tempo, detected pulse and pulse
    clarity. Candidate multiples are reconstructed with the same deterministic
    rule as ``analyze_audio``. A difficulty-specific audio file cannot be
    reconstructed from the base features and must be re-analyzed instead.
    """
    features = item.get("global_features", {})
    if "tempo_hypothesis" not in item and features:
        item["tempo_hypothesis"] = _tempo_hypothesis({"global_features": features})
    base_audio = str(item.get("audio_path", "")).casefold()
    base_tempo = item.get("tempo_hypothesis")
    if not base_audio or not base_tempo:
        return
    for chart in item.get("charts", {}).values():
        if "tempo_hypothesis" in chart:
            continue
        if str(chart.get("audio_path", "")).casefold() == base_audio:
            chart["tempo_hypothesis"] = dict(base_tempo)


def build_style_index(
    corpus_root: str | Path,
    output_path: str | Path,
    song_ids: Iterable[str] | None = None,
    max_tracks: int | None = None,
) -> dict[str, Any]:
    root = Path(corpus_root)
    output = Path(output_path)
    metadata = _load_songlist(root)
    requested = set(song_ids or [])
    directories = [path for path in sorted(root.iterdir()) if path.is_dir()]
    if requested:
        directories = [path for path in directories if path.name in requested]
    if max_tracks is not None:
        directories = directories[:max_tracks]

    items: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for song_dir in directories:
        audio_path = _find_audio(song_dir)
        if audio_path is None:
            continue
        try:
            song = metadata.get(song_dir.name, {})
            bpm_override = song.get("bpm_base")
            audio = analyze_audio(audio_path, tempo_override=float(bpm_override) if bpm_override else None)
            charts: dict[str, Any] = {}
            difficulty_meta = {entry.get("ratingClass"): entry for entry in song.get("difficulties", [])}
            for difficulty, filename in DIFFICULTY_FILES.items():
                chart_path = song_dir / filename
                if not chart_path.exists():
                    continue
                rating_class = int(filename[0])
                difficulty_audio_path = song_dir / f"{rating_class}.ogg"
                if not difficulty_audio_path.exists():
                    difficulty_audio_path = audio_path
                if difficulty_audio_path == audio_path:
                    chart_audio = audio
                else:
                    chart_audio = analyze_audio(
                        difficulty_audio_path,
                        tempo_override=float(bpm_override) if bpm_override else None,
                    )
                chart = AffChart.from_path(chart_path)
                chart_meta = difficulty_meta.get(rating_class, {})
                chart_bpm = float(
                    chart_audio.get(
                        "tempo_bpm",
                        chart_audio.get("global_features", {}).get("tempo_bpm", 120.0),
                    )
                )
                playability = chart.playability_audit(chart_bpm)
                charts[difficulty] = {
                    "rating": chart_meta.get("rating"),
                    "rating_plus": bool(chart_meta.get("ratingPlus", False)),
                    "chart_designer": chart_meta.get("chartDesigner", ""),
                    "audio_path": str(difficulty_audio_path.resolve()),
                    "tempo_hypothesis": _tempo_hypothesis(chart_audio),
                    "summary": chart.summary(chart_audio["duration_s"]),
                    "onset_alignment": chart.onset_alignment(chart_audio["onset_times_s"]),
                    "segment_onset_alignment": chart.onset_alignment(
                        chart_audio["onset_times_s"],
                        include_arc_continuations=True,
                    ),
                    "playability": {
                        "summary": playability["summary"],
                        "thresholds_ms": playability["thresholds_ms"],
                        "spatial_thresholds_aff": playability["spatial_thresholds_aff"],
                    },
                    "sections": chart.section_profile(chart_audio["sections"]),
                    "boundaries": chart.boundary_profile(
                        chart_audio["sections"],
                        chart_bpm,
                    ),
                }
            items.append(
                {
                    "song_id": song_dir.name,
                    "title": song.get("title_localized", {}).get("en", song_dir.name),
                    "artist": song.get("artist", ""),
                    "audio_path": str(audio_path.resolve()),
                    "tempo_hypothesis": _tempo_hypothesis(audio),
                    "style_tags": audio["style_tags"],
                    "style_vector": audio["style_vector"],
                    "global_features": audio["global_features"],
                    "sections": audio["sections"],
                    "charts": charts,
                }
            )
        except Exception as exc:  # Keep a long corpus run incremental and inspectable.
            failures.append({"song_id": song_dir.name, "error": str(exc)})

    # A targeted run updates only the requested tracks instead of discarding
    # everything learned on earlier days. A full run also benefits from this
    # if it is interrupted: successfully processed tracks replace old entries,
    # while unrelated cached tracks remain available.
    existing_items: dict[str, dict[str, Any]] = {}
    existing_failures: dict[str, dict[str, str]] = {}
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            existing_items = {
                str(item["song_id"]): item
                for item in previous.get("items", [])
                if item.get("song_id")
            }
            for item in existing_items.values():
                _backfill_tempo_hypotheses(item)
            existing_failures = {
                str(item["song_id"]): item
                for item in previous.get("failures", [])
                if item.get("song_id")
            }
        except (OSError, ValueError, TypeError):
            # A corrupt cache should not block rebuilding the selected tracks.
            existing_items = {}
            existing_failures = {}

    for item in items:
        song_id = str(item["song_id"])
        existing_items[song_id] = item
        existing_failures.pop(song_id, None)
    for item in failures:
        existing_failures[str(item["song_id"])] = item

    merged_items = [existing_items[key] for key in sorted(existing_items)]
    merged_failures = [existing_failures[key] for key in sorted(existing_failures)]
    payload = {
        "schema_version": 2,
        "corpus_root": str(root.resolve()),
        "feature_names": FEATURE_NAMES,
        "track_count": len(merged_items),
        "items": merged_items,
        "failures": merged_failures,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_style_index(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def retrieve_similar(
    analysis: dict[str, Any],
    index: dict[str, Any],
    difficulty: str = "FTR",
    count: int = 5,
    exclude_song_id: str | None = None,
) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in index.get("items", [])
        if difficulty.upper() in item.get("charts", {}) and item.get("song_id") != exclude_song_id
    ]
    if not candidates:
        return []
    matrix = np.asarray([item["style_vector"] for item in candidates], dtype=float)
    query = np.asarray(analysis["style_vector"], dtype=float)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale[scale < 1e-8] = 1.0
    distances = np.linalg.norm((matrix - mean) / scale - (query - mean) / scale, axis=1)
    order = np.argsort(distances)[: min(count, len(candidates))]
    return [
        {
            "rank": rank + 1,
            "distance": round(float(distances[index_value]), 5),
            "song_id": candidates[index_value]["song_id"],
            "title": candidates[index_value]["title"],
            "artist": candidates[index_value]["artist"],
            "style_tags": candidates[index_value]["style_tags"],
            "chart": candidates[index_value]["charts"][difficulty.upper()],
        }
        for rank, index_value in enumerate(order)
    ]


def aggregate_reference_profile(references: list[dict[str, Any]]) -> dict[str, Any]:
    if not references:
        return {}
    weights = np.asarray([1 / max(reference["distance"], 0.05) for reference in references], dtype=float)
    weights /= weights.sum()
    keys = ["playable_objects_per_second", "mean_arc_movement", "lane_entropy"]
    result: dict[str, Any] = {}
    for key in keys:
        values = np.asarray([reference["chart"]["summary"].get(key, 0) for reference in references], dtype=float)
        result[key] = round(float(np.dot(values, weights)), 4)
    count_keys = ["tap", "hold", "arctap", "arc_input", "arc_trace", "timing"]
    totals = {key: 0.0 for key in count_keys}
    for weight, reference in zip(weights, references):
        counts = reference["chart"]["summary"].get("counts", {})
        playable = max(reference["chart"]["summary"].get("playable_objects", 1), 1)
        for key in count_keys:
            totals[key] += weight * counts.get(key, 0) / playable
    result["object_ratios"] = {key: round(value, 4) for key, value in totals.items()}
    result["reference_song_ids"] = [reference["song_id"] for reference in references]
    return result
