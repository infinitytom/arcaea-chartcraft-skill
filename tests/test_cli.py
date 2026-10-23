import json
from pathlib import Path

import pytest

from arc_toolkit.cli import build_parser


def test_package_preserves_authored_chart_and_both_editable_outputs(tmp_path: Path) -> None:
    chart = tmp_path / "authored.aff"
    text = "AudioOffset:0\n-\ntiming(0,111,4);\n(500,1);\n(770,4);\n"
    chart.write_text(text, encoding="utf-8")
    audio = tmp_path / "audio.ogg"
    # Project/resource completeness is independent of audio decoding.
    audio.write_bytes(b"test resource")
    output = tmp_path / "out"
    args = build_parser().parse_args([
        "package", str(chart), str(audio), "--title", "Original",
        "--artist", "Test", "--bpm", "111", "--output", str(output),
    ])
    assert args.func(args) == 0
    assert (output / "arccreate/2.aff").read_text(encoding="utf-8") == text
    assert (output / "official-format/2.aff").read_bytes() == (output / "arccreate/2.aff").read_bytes()
    report = json.loads((output / "package-validation.json").read_text(encoding="utf-8"))
    assert report["arccreate"]["valid"] and report["official_format"]["valid"]


def test_invalid_chart_is_rejected_before_creating_output(tmp_path: Path) -> None:
    chart = tmp_path / "invalid.aff"
    chart.write_text("AudioOffset:0\n-\nhold(1000,500,1);\n", encoding="utf-8")
    audio = tmp_path / "audio.ogg"
    audio.write_bytes(b"test resource")
    output = tmp_path / "out"
    args = build_parser().parse_args([
        "package", str(chart), str(audio), "--title", "Original",
        "--artist", "Test", "--bpm", "111", "--output", str(output),
    ])
    assert args.func(args) == 1
    assert not output.exists()


def test_index_requires_a_reference_corpus_when_unconfigured(monkeypatch) -> None:
    from arc_toolkit import cli

    monkeypatch.setattr(cli, "DEFAULT_CORPUS", None)
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["build-index"])
