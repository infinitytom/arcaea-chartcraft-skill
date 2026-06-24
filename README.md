# Arcaea Chart Generator Skill

Codex skill for generating Arcaea fan-made chart packages from audio files.

It can create single-difficulty or multi-difficulty packages containing:

- `0.aff` / `1.aff` / `2.aff` / `3.aff`
- `songlist.json`
- `base.jpg`
- `base_256.jpg`
- `base.ogg`
- `output.zip`

The skill emphasizes BPM verification, melody-aware arcs, genre-specific chart
language, multi-difficulty design, real scoring objects, wider motion options,
and post-generation audit metrics.

## Download

Download the packaged skill from the latest release:

https://github.com/infinitytom/arcaea-chartcraft-skill/releases/download/v0.1.0/arcaea-chartcraft-skill.skill

The `.skill` file is a zip-compatible package containing this skill directory.

## 打赏主播

![打赏主播](assets/alipay-reward.jpg)

## Usage

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

Install dependencies:

```bash
pip install librosa numpy pillow soundfile
```

See `SKILL.md` for the full design principles and tuning guide.
