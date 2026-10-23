from __future__ import annotations

import shutil
import subprocess
import json
import re
import time
import os
from pathlib import Path
from typing import Any

import yaml


ARCCREATE_EXE = Path(os.environ.get("ARC_CREATE_EXE") or shutil.which("ArcCreate") or "ArcCreate.exe").expanduser()
DIFFICULTY_FILE = {"PST": "0.aff", "PRS": "1.aff", "FTR": "2.aff", "BYD": "3.aff", "ETR": "4.aff"}
DIFFICULTY_NAME = {"PST": "Past", "PRS": "Present", "FTR": "Future", "BYD": "Beyond", "ETR": "Eternal"}
DIFFICULTY_COLOR = {"PST": "#5B9BD5", "PRS": "#70AD47", "FTR": "#A64DFF", "BYD": "#C00000", "ETR": "#7F6000"}
DIFFICULTY_CLASS = {"PST": 0, "PRS": 1, "FTR": 2, "BYD": 3, "ETR": 4}


def validate_arc_project(project_path: str | Path) -> dict[str, Any]:
    """Check that an ArcCreate project is readable and its asset paths exist.

    AFF validation is intentionally separate: a syntactically valid chart can
    still belong to an unusable project when its audio or jacket was moved.
    """
    project = Path(project_path)
    errors: list[str] = []
    references: list[dict[str, Any]] = []
    if not project.is_file():
        return {"valid": False, "errors": [f"Project not found: {project}"], "references": []}
    try:
        payload = yaml.safe_load(project.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return {"valid": False, "errors": [f"Project could not be read: {exc}"], "references": []}
    charts = payload.get("charts") if isinstance(payload, dict) else None
    if not isinstance(charts, list) or not charts:
        return {"valid": False, "errors": ["Project must contain at least one chart entry"], "references": []}
    for index, chart in enumerate(charts):
        if not isinstance(chart, dict):
            errors.append(f"charts[{index}] is not a mapping")
            continue
        for field in ("chartPath", "audioPath", "jacketPath", "backgroundPath", "videoPath"):
            value = chart.get(field)
            required = field in {"chartPath", "audioPath"}
            if value in {None, ""}:
                if required:
                    errors.append(f"charts[{index}].{field} is required")
                continue
            if not isinstance(value, str):
                errors.append(f"charts[{index}].{field} must be a path string")
                continue
            candidate = Path(value)
            resolved = candidate if candidate.is_absolute() else project.parent / candidate
            exists = resolved.is_file()
            references.append(
                {
                    "chart_index": index,
                    "field": field,
                    "value": value,
                    "resolved": str(resolved.resolve()),
                    "exists": exists,
                }
            )
            if not exists:
                errors.append(f"Missing charts[{index}].{field}: {value}")
    return {"valid": not errors, "errors": errors, "references": references}


def validate_official_format_project(output_dir: str | Path) -> dict[str, Any]:
    """Check the minimum self-contained official-style interchange assets."""
    output = Path(output_dir)
    errors: list[str] = []
    required = [output / "base.ogg", output / "songlist.json"]
    charts = sorted(path for path in output.glob("[0-4].aff") if path.is_file()) if output.is_dir() else []
    for path in required:
        if not path.is_file():
            errors.append(f"Missing interchange asset: {path.name}")
    if not charts:
        errors.append("Missing interchange chart: expected 0.aff through 4.aff")
    song_count = 0
    songlist = output / "songlist.json"
    if songlist.is_file():
        try:
            payload = json.loads(songlist.read_text(encoding="utf-8"))
            songs = payload.get("songs") if isinstance(payload, dict) else None
            if not isinstance(songs, list) or not songs:
                errors.append("songlist.json must contain a non-empty songs array")
            else:
                song_count = len(songs)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"songlist.json could not be read: {exc}")
    return {
        "valid": not errors,
        "errors": errors,
        "charts": [str(path.resolve()) for path in charts],
        "song_count": song_count,
    }


def create_arc_project(
    output_dir: str | Path,
    audio_path: str | Path,
    aff_text: str,
    title: str,
    artist: str,
    difficulty: str,
    base_bpm: float,
    chart_constant: float,
    jacket_path: str | Path | None = None,
    charter: str = "ARC Assistant + Human",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    difficulty = difficulty.upper()
    chart_name = DIFFICULTY_FILE[difficulty]

    source_audio = Path(audio_path)
    audio_name = "base" + source_audio.suffix.lower()
    destination_audio = output / audio_name
    if source_audio.resolve() != destination_audio.resolve():
        shutil.copy2(source_audio, destination_audio)

    jacket_name: str | None = None
    if jacket_path:
        source_jacket = Path(jacket_path)
        jacket_name = "base" + source_jacket.suffix.lower()
        destination_jacket = output / jacket_name
        if source_jacket.resolve() != destination_jacket.resolve():
            shutil.copy2(source_jacket, destination_jacket)

    chart_path = output / chart_name
    chart_path.write_text(aff_text, encoding="utf-8", newline="\n")
    project_path = output / "project.arcproj"
    rating_integer = int(chart_constant)
    rating_label = f"{rating_integer}+" if rating_integer >= 7 and chart_constant - rating_integer >= 0.7 else str(rating_integer)
    chart_settings: dict[str, Any] = {
        "chartPath": chart_name,
        "audioPath": audio_name,
        "jacketPath": jacket_name,
        "baseBpm": round(float(base_bpm), 4),
        "bpmText": f"{float(base_bpm):.2f}",
        "syncBaseBpm": True,
        "backgroundPath": None,
        "videoPath": None,
        "title": title,
        "composer": artist,
        "charter": charter,
        "alias": "",
        "illustrator": "",
        "difficulty": f"{DIFFICULTY_NAME[difficulty]} {rating_label}",
        "chartConstant": float(chart_constant),
        "difficultyColor": DIFFICULTY_COLOR[difficulty],
        "skin": None,
        "colors": None,
        "lastWorkingTiming": 0,
        "previewStart": 0,
        "previewEnd": 0,
        "searchTags": "AI draft, human review required",
    }
    payload = {
        "lastOpenedChartPath": chart_name,
        "charts": [chart_settings],
        "editorSettings": {
            "lastUsedPublisher": "arc-assistant",
            "lastUsedPackageName": output.name,
            "lastUsedVersionNumber": 0,
            "timestamps": {},
        },
    }
    project_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    project_validation = validate_arc_project(project_path)
    if not project_validation["valid"]:
        raise RuntimeError(f"ArcCreate project has missing references: {project_validation['errors']}")
    return {
        "project": str(project_path.resolve()),
        "chart": str(chart_path.resolve()),
        "audio": str(destination_audio.resolve()),
        "jacket": str((output / jacket_name).resolve()) if jacket_name else "",
        "project_validation": project_validation,
    }


def launch_arccreate() -> subprocess.Popen[bytes]:
    if not ARCCREATE_EXE.exists():
        raise FileNotFoundError(f"ArcCreate not found: {ARCCREATE_EXE}")
    return subprocess.Popen([str(ARCCREATE_EXE)], cwd=str(ARCCREATE_EXE.parent))


def _song_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", value.lower())
    return cleaned[:64] or "customsong"


def _convert_with_ffmpeg(source: Path, destination: Path, extra_args: list[str]) -> None:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise FileNotFoundError("ffmpeg is required for official-format media conversion")
    subprocess.run(
        [executable, "-y", "-i", str(source), *extra_args, str(destination)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def create_official_format_project(
    output_dir: str | Path,
    audio_path: str | Path,
    aff_text: str,
    title: str,
    artist: str,
    difficulty: str,
    base_bpm: float,
    chart_constant: float,
    jacket_path: str | Path | None = None,
    song_id: str | None = None,
    charter: str = "ARC Assistant + Human",
) -> dict[str, Any]:
    """Create a plain official-style folder usable as an interchange source.

    Arcade-Chan may add its own Arcade/Project.arcade and convert AFF to ACBA.
    This function intentionally does not fabricate either proprietary file.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    difficulty = difficulty.upper()
    chart_name = DIFFICULTY_FILE[difficulty]
    (output / chart_name).write_text(aff_text, encoding="utf-8", newline="\n")

    source_audio = Path(audio_path)
    destination_audio = output / "base.ogg"
    if source_audio.suffix.lower() == ".ogg":
        if source_audio.resolve() != destination_audio.resolve():
            shutil.copy2(source_audio, destination_audio)
    else:
        _convert_with_ffmpeg(source_audio, destination_audio, ["-vn", "-c:a", "libvorbis", "-q:a", "6"])

    jacket_result = ""
    if jacket_path:
        source_jacket = Path(jacket_path)
        destination_jacket = output / "base.jpg"
        small_jacket = output / "base_256.jpg"
        _convert_with_ffmpeg(source_jacket, destination_jacket, ["-frames:v", "1", "-q:v", "2"])
        _convert_with_ffmpeg(source_jacket, small_jacket, ["-vf", "scale=256:256:force_original_aspect_ratio=decrease,pad=256:256:(ow-iw)/2:(oh-ih)/2", "-frames:v", "1", "-q:v", "2"])
        jacket_result = str(destination_jacket.resolve())

    identifier = _song_id(song_id or title)
    rating = int(chart_constant)
    difficulty_entry: dict[str, Any] = {
        "ratingClass": DIFFICULTY_CLASS[difficulty],
        "chartDesigner": charter,
        "jacketDesigner": "See source/permission record",
        "rating": rating,
    }
    if rating >= 7 and chart_constant - rating >= 0.7:
        difficulty_entry["ratingPlus"] = True
    song = {
        "idx": 0,
        "id": identifier,
        "title_localized": {"en": title},
        "artist": artist,
        "bpm": f"{base_bpm:.2f}",
        "bpm_base": round(float(base_bpm), 4),
        "set": "single",
        "purchase": "",
        "audioPreview": 0,
        "audioPreviewEnd": 0,
        "side": 0,
        "bg": "base",
        "date": int(time.time()),
        "version": "0.1",
        "difficulties": [difficulty_entry],
    }
    songlist_path = output / "songlist.json"
    songlist_path.write_text(json.dumps({"songs": [song]}, ensure_ascii=False, indent=2), encoding="utf-8")
    project_validation = validate_official_format_project(output)
    if not project_validation["valid"]:
        raise RuntimeError(f"Official-style project has missing assets: {project_validation['errors']}")
    return {
        "root": str(output.resolve()),
        "chart": str((output / chart_name).resolve()),
        "audio": str(destination_audio.resolve()),
        "jacket": jacket_result,
        "songlist": str(songlist_path.resolve()),
        "arcade_chan_note": "Open/import this plain project, then let Arcade-Chan create Project.arcade or save ACBA itself.",
        "project_validation": project_validation,
    }
