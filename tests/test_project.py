from pathlib import Path

import yaml

from arc_toolkit.project import (
    create_arc_project,
    create_official_format_project,
    validate_arc_project,
    validate_official_format_project,
)


def test_create_project(tmp_path: Path) -> None:
    audio = tmp_path / "input.ogg"
    audio.write_bytes(b"placeholder")
    output = tmp_path / "project"
    result = create_arc_project(
        output,
        audio,
        "AudioOffset:0\n-\ntiming(0,120.00,4.00);\n",
        "Title",
        "Artist",
        "FTR",
        120,
        9.0,
    )
    project = yaml.safe_load(Path(result["project"]).read_text(encoding="utf-8"))
    assert project["charts"][0]["chartPath"] == "2.aff"
    assert project["charts"][0]["audioPath"] == "base.ogg"
    assert result["project_validation"]["valid"]
    assert validate_arc_project(result["project"])["valid"]


def test_validate_arc_project_finds_missing_audio(tmp_path: Path) -> None:
    audio = tmp_path / "input.ogg"
    audio.write_bytes(b"placeholder")
    result = create_arc_project(
        tmp_path / "project-missing-audio",
        audio,
        "AudioOffset:0\n-\ntiming(0,120.00,4.00);\n",
        "Title",
        "Artist",
        "FTR",
        120,
        9.0,
    )
    Path(result["audio"]).unlink()
    validation = validate_arc_project(result["project"])
    assert not validation["valid"]
    assert validation["errors"] == ["Missing charts[0].audioPath: base.ogg"]


def test_create_project_displays_plus_rating(tmp_path: Path) -> None:
    audio = tmp_path / "input.ogg"
    audio.write_bytes(b"placeholder")
    result = create_arc_project(
        tmp_path / "project-plus",
        audio,
        "AudioOffset:0\n-\ntiming(0,150.00,4.00);\n",
        "Title",
        "Artist",
        "FTR",
        150,
        9.8,
    )
    project = yaml.safe_load(Path(result["project"]).read_text(encoding="utf-8"))
    assert project["charts"][0]["difficulty"] == "Future 9+"


def test_create_official_format_project(tmp_path: Path) -> None:
    audio = tmp_path / "input.ogg"
    audio.write_bytes(b"placeholder")
    result = create_official_format_project(
        tmp_path / "official",
        audio,
        "AudioOffset:0\n-\ntiming(0,120.00,4.00);\n",
        "Title",
        "Artist",
        "FTR",
        120,
        9.0,
        song_id="test-song",
    )
    songlist = yaml.safe_load(Path(result["songlist"]).read_text(encoding="utf-8"))
    assert songlist["songs"][0]["id"] == "testsong"
    assert Path(result["chart"]).name == "2.aff"
    assert result["project_validation"]["valid"]
    Path(result["audio"]).unlink()
    validation = validate_official_format_project(result["root"])
    assert not validation["valid"]
    assert validation["errors"] == ["Missing interchange asset: base.ogg"]
