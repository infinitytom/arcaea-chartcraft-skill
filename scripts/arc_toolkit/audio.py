from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import librosa
import numpy as np


FEATURE_NAMES = [
    "tempo_bpm",
    "detected_pulse_bpm",
    "onset_rate_hz",
    "pulse_clarity",
    "rms_mean",
    "rms_dynamic_range",
    "spectral_centroid_hz",
    "spectral_bandwidth_hz",
    "spectral_rolloff_hz",
    "spectral_flatness",
    "zero_crossing_rate",
    "percussive_ratio",
    "chroma_entropy",
]


def _scalar(value: Any) -> float:
    array = np.asarray(value, dtype=float).reshape(-1)
    return float(array[0]) if array.size else 0.0


def _safe_mean(values: np.ndarray) -> float:
    return float(np.mean(values)) if values.size else 0.0


def _normalized_entropy(values: np.ndarray) -> float:
    distribution = np.maximum(np.mean(values, axis=1), 1e-12)
    distribution = distribution / distribution.sum()
    entropy = -np.sum(distribution * np.log(distribution))
    return float(entropy / math.log(len(distribution)))


def _style_tags(features: dict[str, float]) -> list[str]:
    tags: list[str] = []
    tempo = features["detected_pulse_bpm"]
    while tempo < 65:
        tempo *= 2
    while tempo > 220:
        tempo /= 2
    if tempo >= 170:
        tags.append("fast")
    elif tempo <= 105:
        tags.append("slow")
    else:
        tags.append("midtempo")

    tags.append("dense" if features["onset_rate_hz"] >= 3.8 else "sparse")
    tags.append("percussive" if features["percussive_ratio"] >= 0.52 else "harmonic")
    tags.append("bright" if features["spectral_centroid_hz"] >= 2400 else "dark")
    tags.append("dynamic" if features["rms_dynamic_range"] >= 0.11 else "steady")
    tags.append("noisy" if features["spectral_flatness"] >= 0.025 else "tonal")
    return tags


def _section_role_hypotheses(
    index: int,
    count: int,
    energy: float,
    onset_rate: float,
    previous_energy: float | None,
    global_energy: float,
) -> list[dict[str, Any]]:
    """Rank coarse section-role hypotheses without presenting one as fact.

    These scores are intentionally heuristic. They expose ambiguity to the
    chart-planning model instead of hiding it behind a single hard label.
    """
    ratio = energy / max(global_energy, 1e-8)
    change = energy / max(previous_energy, 1e-8) if previous_energy is not None else 1.0
    raw_scores = {
        "intro": 0.05
        + (0.8 + max(0.0, 0.9 - ratio) * 0.9 if index == 0 else 0.0),
        "outro": 0.05
        + (0.8 + max(0.0, 0.9 - ratio) * 0.9 if index == count - 1 else 0.0),
        "peak": 0.08
        + max(0.0, ratio - 1.0) * 1.6
        + min(max(onset_rate, 0.0) / 6.0, 1.0) * 0.25,
        "build": 0.10
        + min(max(0.0, change - 1.0), 0.75) * 1.4
        + max(0.0, ratio - 0.9) * 0.2,
        "break": 0.08
        + max(0.0, 0.9 - ratio) * (1.25 if index in {0, count - 1} else 2.0),
        "main": 0.35 + max(0.0, 1.0 - abs(ratio - 1.0)) * 0.5,
    }
    roles = list(raw_scores)
    # A low temperature would manufacture certainty from coarse features.
    # Keep the distribution deliberately soft for downstream human/LLM review.
    logits = np.asarray([raw_scores[role] for role in roles], dtype=float) * 1.5
    logits -= float(np.max(logits))
    probabilities = np.exp(logits)
    probabilities /= max(float(np.sum(probabilities)), 1e-8)
    ranked = sorted(zip(roles, probabilities), key=lambda item: item[1], reverse=True)
    return [
        {"role": role, "confidence": round(float(confidence), 4)}
        for role, confidence in ranked[:3]
    ]


def _section_role(
    index: int,
    count: int,
    energy: float,
    onset_rate: float,
    previous_energy: float | None,
    global_energy: float,
) -> str:
    return _section_role_hypotheses(
        index,
        count,
        energy,
        onset_rate,
        previous_energy,
        global_energy,
    )[0]["role"]


def _regular_beat_grid(
    onset_times: np.ndarray,
    onset_strengths: np.ndarray,
    bpm: float,
    duration: float,
) -> np.ndarray:
    period = 60.0 / max(bpm, 1e-6)
    early_mask = onset_times < min(duration, 15.0)
    candidates = onset_times[early_mask][:80]
    if candidates.size == 0:
        phase = 0.0
    else:
        strengths = onset_strengths[early_mask][: len(candidates)]
        strengths = strengths / max(float(np.max(strengths)), 1e-8)
        phases = np.unique(np.mod(candidates, period))
        best_score, phase = -1.0, 0.0
        for candidate in phases:
            residual = np.mod(candidates - candidate + period / 2, period) - period / 2
            score = float(np.sum(strengths * np.exp(-0.5 * (residual / max(period * 0.12, 0.025)) ** 2)))
            if score > best_score:
                best_score, phase = score, float(candidate)
    first = phase % period
    return np.arange(first, duration, period, dtype=float)


def analyze_audio(
    path: str | Path,
    sample_rate: int = 16000,
    tempo_override: float | None = None,
) -> dict[str, Any]:
    audio_path = Path(path)
    y, sr = librosa.load(audio_path, sr=sample_rate, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    if duration <= 0 or y.size == 0:
        raise ValueError(f"Audio is empty: {audio_path}")

    hop = 512
    y_harmonic, y_percussive = librosa.effects.hpss(y)
    onset_envelope = librosa.onset.onset_strength(y=y_percussive, sr=sr, hop_length=hop)
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_envelope,
        sr=sr,
        hop_length=hop,
        backtrack=False,
        units="frames",
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop)
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=sr,
        hop_length=hop,
        trim=False,
    )
    detected_tempo = _scalar(tempo)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)

    magnitude = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    power = magnitude**2
    rms = librosa.feature.rms(S=magnitude)[0]
    centroid = librosa.feature.spectral_centroid(S=magnitude, sr=sr)[0]
    bandwidth = librosa.feature.spectral_bandwidth(S=magnitude, sr=sr)[0]
    rolloff = librosa.feature.spectral_rolloff(S=magnitude, sr=sr, roll_percent=0.85)[0]
    flatness = librosa.feature.spectral_flatness(S=power)[0]
    zcr = librosa.feature.zero_crossing_rate(y, hop_length=hop)[0]
    chroma = librosa.feature.chroma_stft(S=power, sr=sr)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop)

    harmonic_rms = _safe_mean(librosa.feature.rms(y=y_harmonic, hop_length=hop)[0])
    percussive_rms = _safe_mean(librosa.feature.rms(y=y_percussive, hop_length=hop)[0])
    percussive_ratio = percussive_rms / max(harmonic_rms + percussive_rms, 1e-8)
    autocorrelation = librosa.autocorrelate(onset_envelope, max_size=min(len(onset_envelope), 512))
    pulse_clarity = float(np.max(autocorrelation[1:]) / max(autocorrelation[0], 1e-8)) if len(autocorrelation) > 1 else 0.0

    onset_strengths = onset_envelope[onset_frames] if len(onset_frames) else np.array([])
    tempo_value = float(tempo_override) if tempo_override else detected_tempo
    if tempo_override:
        beat_times = _regular_beat_grid(onset_times, onset_strengths, tempo_value, duration)

    candidates = sorted(
        {
            round(value, 4)
            for value in (detected_tempo / 2, detected_tempo, detected_tempo * 1.5, detected_tempo * 2)
            if 55 <= value <= 240
        }
    )
    if tempo_override:
        candidates = sorted(set(candidates + [round(float(tempo_override), 4)]))

    features = {
        "tempo_bpm": tempo_value,
        "detected_pulse_bpm": detected_tempo,
        "onset_rate_hz": float(len(onset_times) / duration),
        "pulse_clarity": pulse_clarity,
        "rms_mean": _safe_mean(rms),
        "rms_dynamic_range": float(np.percentile(rms, 90) - np.percentile(rms, 10)),
        "spectral_centroid_hz": _safe_mean(centroid),
        "spectral_bandwidth_hz": _safe_mean(bandwidth),
        "spectral_rolloff_hz": _safe_mean(rolloff),
        "spectral_flatness": _safe_mean(flatness),
        "zero_crossing_rate": _safe_mean(zcr),
        "percussive_ratio": percussive_ratio,
        "chroma_entropy": _normalized_entropy(chroma),
    }

    frame_count = min(mfcc.shape[1], chroma.shape[1], len(rms), len(onset_envelope))
    combined = np.vstack(
        [
            librosa.util.normalize(mfcc[:8, :frame_count], axis=1),
            librosa.util.normalize(chroma[:, :frame_count], axis=1),
            librosa.util.normalize(rms[None, :frame_count], axis=1),
            librosa.util.normalize(onset_envelope[None, :frame_count], axis=1),
        ]
    )
    valid_beats = beat_frames[(beat_frames > 0) & (beat_frames < frame_count)]
    sync_boundaries = np.unique(np.concatenate(([0], valid_beats, [frame_count])))
    beat_features = librosa.util.sync(combined, sync_boundaries, aggregate=np.mean)
    target_sections = max(3, min(12, round(duration / 20)))
    target_sections = min(target_sections, beat_features.shape[1])
    if target_sections >= 2 and beat_features.shape[1] >= target_sections:
        section_columns = librosa.segment.agglomerative(beat_features, target_sections)
        section_frames = [int(sync_boundaries[min(int(i), len(sync_boundaries) - 1)]) for i in section_columns]
    else:
        section_frames = [0]
    section_times = sorted(set(float(librosa.frames_to_time(frame, sr=sr, hop_length=hop)) for frame in section_frames))
    if not section_times or section_times[0] > 0.01:
        section_times.insert(0, 0.0)
    section_times.append(duration)

    frame_times = librosa.frames_to_time(np.arange(frame_count), sr=sr, hop_length=hop)
    sections: list[dict[str, Any]] = []
    previous_energy: float | None = None
    for index, (start, end) in enumerate(zip(section_times, section_times[1:])):
        mask = (frame_times >= start) & (frame_times < end)
        section_rms = rms[:frame_count][mask]
        section_onsets = onset_times[(onset_times >= start) & (onset_times < end)]
        section_energy = _safe_mean(section_rms)
        section_onset_rate = float(len(section_onsets) / max(end - start, 1e-6))
        section_centroid = _safe_mean(centroid[:frame_count][mask])
        section_flatness = _safe_mean(flatness[:frame_count][mask])
        role_candidates = _section_role_hypotheses(
            index,
            len(section_times) - 1,
            section_energy,
            section_onset_rate,
            previous_energy,
            features["rms_mean"],
        )
        sections.append(
            {
                "index": index,
                "start_s": round(start, 3),
                "end_s": round(end, 3),
                "role_candidate": role_candidates[0]["role"],
                "role_confidence": role_candidates[0]["confidence"],
                "role_candidates": role_candidates,
                "energy": round(section_energy, 6),
                "energy_relative": round(section_energy / max(features["rms_mean"], 1e-8), 3),
                "onset_rate_hz": round(section_onset_rate, 3),
                "brightness_hz": round(section_centroid, 1),
                "flatness": round(section_flatness, 5),
            }
        )
        previous_energy = section_energy

    ranked = np.argsort(onset_strengths)[::-1][: min(300, len(onset_strengths))]
    salient_onsets = sorted(
        (
            {
                "time_s": round(float(onset_times[i]), 4),
                "strength": round(float(onset_strengths[i]), 5),
            }
            for i in ranked
        ),
        key=lambda event: event["time_s"],
    )

    return {
        "schema_version": 1,
        "audio_path": str(audio_path.resolve()),
        "sample_rate": sr,
        "duration_s": round(duration, 4),
        "tempo_bpm": round(tempo_value, 4),
        "tempo_detected_bpm": round(detected_tempo, 4),
        "tempo_source": "override" if tempo_override else "detected",
        "tempo_candidates_bpm": candidates,
        "tempo_confidence": round(min(1.0, max(0.0, pulse_clarity)), 4),
        "beat_times_s": [round(float(value), 4) for value in beat_times],
        "downbeat_candidates_s": [round(float(value), 4) for value in beat_times[::4]],
        "onset_times_s": [round(float(value), 4) for value in onset_times],
        "salient_onsets": salient_onsets,
        "global_features": {key: round(value, 6) for key, value in features.items()},
        "style_vector": [round(features[name], 6) for name in FEATURE_NAMES],
        "style_vector_names": FEATURE_NAMES,
        "style_tags": _style_tags(features),
        "sections": sections,
        "limitations": [
            "style tags are acoustic descriptors, not authoritative genre labels",
            "automatic tempo can select a metrical multiple or unrelated pulse; review candidates or pass a BPM override",
            "downbeats are four-beat candidates and may be wrong for non-4/4 music",
            "section role labels are hypotheses for the LLM to review",
        ],
    }
