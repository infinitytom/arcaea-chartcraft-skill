from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .aff import AffChart, validate_aff
from .audio import analyze_audio
from .generate import create_chart_brief, generate_safe_skeleton, render_llm_prompt
from .project import ARCCREATE_EXE, create_arc_project, create_official_format_project, launch_arccreate, validate_arc_project, validate_official_format_project
from .style import aggregate_reference_profile, build_style_index, load_style_index, retrieve_similar


DEFAULT_CORPUS = Path(os.environ["ARC_CORPUS_ROOT"]).expanduser() if os.environ.get("ARC_CORPUS_ROOT") else None


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def command_doctor(_args: argparse.Namespace) -> int:
    packages = {}
    for name in ("librosa", "soundfile", "PyYAML", "numpy", "scipy", "scikit-learn"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    result = {
        "python": sys.version.split()[0],
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "arccreate": str(ARCCREATE_EXE) if ARCCREATE_EXE.exists() else None,
        "official_corpus": str(DEFAULT_CORPUS) if DEFAULT_CORPUS and DEFAULT_CORPUS.exists() else None,
        "optional_features": "ArcCreate and a user-owned reference corpus are optional; configure ARC_CREATE_EXE and ARC_CORPUS_ROOT when used.",
        "packages": packages,
        "ready": bool(
            shutil.which("ffmpeg")
            and all(packages[name] for name in ("librosa", "soundfile", "PyYAML"))
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


def command_analyze(args: argparse.Namespace) -> int:
    result = analyze_audio(args.audio, tempo_override=args.bpm)
    _write_json(Path(args.output), result)
    print(Path(args.output).resolve())
    return 0


def command_build_index(args: argparse.Namespace) -> int:
    result = build_style_index(
        args.corpus,
        args.output,
        song_ids=args.song_id,
        max_tracks=args.max_tracks,
    )
    print(json.dumps({"output": str(Path(args.output).resolve()), "tracks": result["track_count"], "failures": len(result["failures"])}, ensure_ascii=False))
    return 0 if result["track_count"] else 1


def command_validate(args: argparse.Namespace) -> int:
    result = validate_aff(args.chart, args.difficulty)
    if args.output:
        _write_json(Path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


def command_audit_hands(args: argparse.Namespace) -> int:
    result = AffChart.from_path(args.chart).hand_lock_audit(args.bpm)
    if args.output:
        _write_json(Path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["risky_input_arcs"] == 0 else 2


def command_audit_playability(args: argparse.Namespace) -> int:
    result = AffChart.from_path(args.chart).playability_audit(args.bpm)
    if args.output:
        _write_json(Path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["review_issue_count"] == 0 else 2


def command_audit_special(args: argparse.Namespace) -> int:
    result = AffChart.from_path(args.chart).special_effects_audit()
    if args.output:
        _write_json(Path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    analysis = analyze_audio(args.audio, tempo_override=args.bpm)
    references: list[dict[str, Any]] = []
    if args.index:
        references = retrieve_similar(
            analysis,
            load_style_index(args.index),
            difficulty=args.difficulty,
            count=args.reference_count,
        )
    reference_profile = aggregate_reference_profile(references)
    brief = create_chart_brief(
        analysis,
        references,
        reference_profile,
        args.title,
        args.artist,
        args.difficulty,
    )
    skeleton = generate_safe_skeleton(analysis, args.difficulty)
    project_paths = create_arc_project(
        output / "arccreate",
        args.audio,
        skeleton,
        args.title,
        args.artist,
        args.difficulty,
        analysis["tempo_bpm"],
        args.chart_constant,
        jacket_path=args.jacket,
    )
    interchange_paths = create_official_format_project(
        output / "official-format",
        args.audio,
        skeleton,
        args.title,
        args.artist,
        args.difficulty,
        analysis["tempo_bpm"],
        args.chart_constant,
        jacket_path=args.jacket,
        song_id=args.song_id,
    )
    validation = validate_aff(project_paths["chart"], args.difficulty)
    _write_json(output / "audio-analysis.json", analysis)
    _write_json(output / "chart-brief.json", brief)
    _write_json(output / "validation.json", validation)
    (output / "llm-prompt.md").write_text(render_llm_prompt(brief), encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": 1,
        "stage": "safe-skeleton-ready-for-llm-and-human-editing",
        "audio_analysis": str((output / "audio-analysis.json").resolve()),
        "chart_brief": str((output / "chart-brief.json").resolve()),
        "llm_prompt": str((output / "llm-prompt.md").resolve()),
        "validation": str((output / "validation.json").resolve()),
        "arccreate": project_paths,
        "official_format": interchange_paths,
    }
    _write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if validation["valid"] else 1


def command_open(_args: argparse.Namespace) -> int:
    process = launch_arccreate()
    print(json.dumps({"pid": process.pid, "executable": str(ARCCREATE_EXE)}, ensure_ascii=False))
    return 0


def command_package(args: argparse.Namespace) -> int:
    """Package an authored AFF without replacing it with the safe skeleton."""
    validation = validate_aff(args.chart, args.difficulty)
    if not validation["valid"]:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 1
    output = Path(args.output)
    aff_text = Path(args.chart).read_text(encoding="utf-8-sig")
    # Convert media once; ArcCreate receives the same OGG as the interchange folder.
    interchange = create_official_format_project(
        output / "official-format", args.audio, aff_text, args.title, args.artist,
        args.difficulty, args.bpm, args.chart_constant, jacket_path=args.jacket,
        song_id=args.song_id, charter=args.charter,
    )
    project = create_arc_project(
        output / "arccreate", interchange["audio"], aff_text, args.title, args.artist,
        args.difficulty, args.bpm, args.chart_constant, jacket_path=args.jacket,
        charter=args.charter,
    )
    report = {
        "validation": validation,
        "arccreate": validate_arc_project(project["project"]),
        "official_format": validate_official_format_project(output / "official-format"),
        "difficulty_status": "target, not a verified rating",
        "device_playtest": "not established by packaging",
    }
    _write_json(output / "package-validation.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["arccreate"]["valid"] and report["official_format"]["valid"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arc", description="Style-aware ARC chart preparation toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check the local workflow dependencies")
    doctor.set_defaults(func=command_doctor)

    analyze = subparsers.add_parser("analyze", help="analyze one audio file")
    analyze.add_argument("audio")
    analyze.add_argument("--output", "-o", required=True)
    analyze.add_argument("--bpm", type=float, help="confirmed BPM override")
    analyze.set_defaults(func=command_analyze)

    index = subparsers.add_parser("build-index", help="build an incremental official style index")
    index.add_argument("--corpus", default=str(DEFAULT_CORPUS) if DEFAULT_CORPUS else None, required=DEFAULT_CORPUS is None)
    index.add_argument("--output", "-o", default="cache/official-style-index.json")
    index.add_argument("--song-id", action="append", help="only analyze these song ids; repeatable")
    index.add_argument("--max-tracks", type=int)
    index.set_defaults(func=command_build_index)

    validate = subparsers.add_parser("validate", help="validate an AFF draft")
    validate.add_argument("chart")
    validate.add_argument("--difficulty", default="FTR", choices=["PST", "PRS", "FTR", "ETR", "BYD"])
    validate.add_argument("--output", "-o")
    validate.set_defaults(func=command_validate)

    audit_hands = subparsers.add_parser("audit-hands", help="flag risky opposite-hand patterns during input arcs")
    audit_hands.add_argument("chart")
    audit_hands.add_argument("--bpm", type=float, required=True)
    audit_hands.add_argument("--output", "-o")
    audit_hands.set_defaults(func=command_audit_hands)

    audit_playability = subparsers.add_parser(
        "audit-playability",
        help="flag cramped objects, near-misaligned trace joints and abrupt hand or arc tension",
    )
    audit_playability.add_argument("chart")
    audit_playability.add_argument("--bpm", type=float, required=True)
    audit_playability.add_argument("--output", "-o")
    audit_playability.set_defaults(func=command_audit_playability)

    audit_special = subparsers.add_parser("audit-special", help="summarize sparse SV, camera and staging effects")
    audit_special.add_argument("chart")
    audit_special.add_argument("--output", "-o")
    audit_special.set_defaults(func=command_audit_special)

    prepare = subparsers.add_parser("prepare", help="prepare analysis, LLM brief and ArcCreate draft project")
    prepare.add_argument("audio")
    prepare.add_argument("--title", required=True)
    prepare.add_argument("--artist", required=True)
    prepare.add_argument("--song-id")
    prepare.add_argument("--difficulty", default="FTR", choices=["PST", "PRS", "FTR", "ETR", "BYD"])
    prepare.add_argument("--chart-constant", type=float, default=9.0)
    prepare.add_argument("--bpm", type=float, help="confirmed BPM override; recommended when automatic tempo is uncertain")
    prepare.add_argument("--jacket")
    prepare.add_argument("--index")
    prepare.add_argument("--reference-count", type=int, default=5)
    prepare.add_argument("--output", "-o", required=True)
    prepare.set_defaults(func=command_prepare)

    package = subparsers.add_parser("package", help="package an authored AFF into editable ArcCreate and interchange projects")
    package.add_argument("chart")
    package.add_argument("audio")
    package.add_argument("--title", required=True)
    package.add_argument("--artist", required=True)
    package.add_argument("--bpm", type=float, required=True)
    package.add_argument("--difficulty", default="FTR", choices=["PST", "PRS", "FTR", "ETR", "BYD"])
    package.add_argument("--chart-constant", type=float, default=9.0)
    package.add_argument("--jacket")
    package.add_argument("--song-id")
    package.add_argument("--charter", default="Codex + Human")
    package.add_argument("--output", "-o", required=True)
    package.set_defaults(func=command_package)

    open_editor = subparsers.add_parser("open", help="launch the configured ArcCreate editor")
    open_editor.set_defaults(func=command_open)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
