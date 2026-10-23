# Arcaea Chart Generator Skill

Codex skill for authoring and reviewing editable Arcaea-style chart drafts from
actual audio. Phrase development and whole-hand choreography come before
generator presets; automated checks do not establish musical quality or rating.

It can create single-difficulty or multi-difficulty packages containing:

- `0.aff` / `1.aff` / `2.aff` / `3.aff` / `4.aff`
- `arccreate/project.arcproj`
- `songlist.json`
- `base.jpg`
- `base_256.jpg`
- `base.ogg`
- `output.zip`

The current workflow includes audio/tempo hypotheses, reference-conditioned
briefs, AFF/contact audits, and both an ArcCreate `.arcproj` project and a plain
interchange folder. Official reference assets and song media are not included.

## Download

Download the packaged skill from the latest release:

[Download the latest packaged skill](https://github.com/infinitytom/arcaea-chartcraft-skill/releases/latest/download/arcaea-chartcraft-skill.skill)

The `.skill` file is a zip-compatible package containing this skill directory.

## 打赏主播

![打赏主播](assets/alipay-reward.jpg)

## Usage

Install Python dependencies and make FFmpeg available for media conversion:

```bash
python -m pip install -r requirements.txt
```

Analyze the supplied recording, then author/revise the AFF using the phrase brief:

```bash
python scripts/arc.py analyze song.mp4 --bpm 111 --output work/analysis.json
python scripts/arc.py validate work/2.aff --difficulty FTR
python scripts/arc.py audit-playability work/2.aff --bpm 111 --output work/review.json
```

Package the authored chart, preserving its notes:

```bash
python scripts/arc.py package work/2.aff song.mp4 --title "Song" --artist "Artist" \
  --bpm 111 --difficulty FTR --chart-constant 10 --jacket cover.jpg --output work/package
```

This creates `arccreate/project.arcproj` and `official-format/`. They are editable
drafts, not a guaranteed installable game mod. Verify network-cover provenance
and media permissions separately before public redistribution.

Reference indexing and editor launch are optional. Supply `build-index --corpus`
or set `ARC_CORPUS_ROOT`; set `ARC_CREATE_EXE` for `arc.py open`. There are no
hard-coded personal drive locations. Demucs/Basic Pitch are optional analysis
tools, not dependencies of basic validation and packaging.

## Legacy sketch generators

The earlier commands remain available for starting material. Their successful
execution, density and motion presets do not complete phrase design or calibrate
the displayed difficulty. In particular, do not use a generated cover when the
user has requested a real network cover.

Single difficulty:

```bash
python scripts/generate_chart.py --input "song.mp3" --outdir ./out \
  --title "Song Title" --artist "Artist" --rating 9 \
  --difficulty 2 --style auto --motion auto
```

Multi-difficulty pack:

```bash
python scripts/generate_chart_pack.py --input "song.mp3" --outdir ./out \
  --title "Song Title" --artist "Artist" --difficulties 0 1 2 3 \
  --style auto --motion auto
```

## Validation

```bash
python -m pip install pytest
python -m pytest tests -q
```

See [SKILL.md](SKILL.md), [phrase design](references/phrase-design.md) and the
[revision case](references/revision-case.md) for the design and evidence boundaries.
