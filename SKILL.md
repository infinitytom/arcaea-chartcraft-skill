---
name: arcaea-chart-generator
description: Create, revise and audit editable Arcaea-style AFF charts from actual song audio, including musical sampling, Arc/Arctap choreography, difficulty design and ArcCreate projects. Use for Arcaea or ARC custom-chart work, not other rhythm games.
---

# Arcaea Chart Generator

Produce an editable chart draft for listening review and device playtesting.
The bundled generators produce starting material; a successful process or valid
AFF does not establish musical quality, beauty, hand feel or a difficulty rating.

## Start with the right workflow

- For creation or substantial revision, read
  [phrase design and choreography](references/phrase-design.md).
- For Arc connections, contact geometry and proportional review, read
  [stable technical strategy](references/stable-strategy.md).
- For exact AFF syntax, consult [the format reference](references/aff_format.md).
- When diagnosing repetitive, underdeveloped or falsely difficult drafts, consult
  [the October 2026 revision case](references/revision-case.md). It records
  song-specific feedback, not a universal successful chart template.

Use available local tooling and user preferences. Do not assume a personal drive,
reference corpus, editor installation, GPU or stem-separation model exists.
Treat any reference corpus as read-only; never package its charts, music or art.

## Analyze before placing notes

Analyze the actual supplied audio. Preserve tempo candidates, phase/offset
conventions and section-label confidence. Use a confirmed BPM override when
available; re-check alignment across the whole song, not only the first phrase.
Use a fixed grid when the recording supports it; swing, tempo changes and expressive
timing must not be flattened merely to improve an onset score.

Choose a primary musical layer and a supporting layer per phrase. Mixed-audio
onsets and estimated pitch are evidence candidates. For dense mixtures or uncertain
layers, consider isolated Demucs stems and pitch transcription if available; record
model/settings and limitations. Do not call HPSS output an isolated vocal stem or
claim listening review when only signal analysis was performed.

Write a section brief before dense generation: musical layer, anchor timings,
configuration vocabulary, density/pressure budget, intended hands, preparation,
recovery and motif development. A global pattern loop, density multiplier, genre
preset or motion flag cannot replace this work.

## Author complete hand routes

Track the intended hand over the entire Arc chain, adjacent floor/sky inputs and
the next phrase. Arc color and floor lane are natural-hand hypotheses, not fixed
halves of the screen. Deliberate free-hand cross-field reaches are valid; review
their preparation, occupied hand, contact separation and return route explicitly.

Tension depends on motion over time, acceleration/braking, turns, sustained
control and the other hand's task. A larger span, more segments, color changes,
a high motion preset or arbitrary distant jumps is not proof of tension.
Use high anchors, cross-field sweeps, ground/sky relays, sustained phrases and
paired motion only where the music supports their role.

Develop phrases rather than repeating short snakes at fixed bar intervals.
A recurring musical idea may retain anchors while changing objects, hand
coordination, space and pressure. Use playable inputs for the core gesture;
decoration and gimmicks need a musical trigger, readable entrance and exit.

Keep same-color connected segments exact in timing/endpoint geometry. An internal
control point does not free the hand. Do not infer a one-hand color switch solely
from a visible cross-color connection. Judge fast movement using actual previous
contact, including a sustain's endpoint and the next sustain's start.

Difficulty labels are targets until playtested. When feedback says "too simple",
"mechanical" or "no beauty", reconsider musical selection, phrase organization and
combined tasks before increasing counts, travel or the displayed rating.
Create additional difficulties only when requested or within the agreed scope.

## Bundled tools

Install core dependencies with `python -m pip install -r requirements.txt`.
FFmpeg is required for video/non-OGG conversion and jacket resizing. Demucs and
Basic Pitch are optional separate environments; the core workflow does not install
or download their models automatically.

```bash
python scripts/arc.py analyze "song.mp4" --bpm 111 --output work/audio-analysis.json
python scripts/arc.py validate work/2.aff --difficulty FTR --output work/validation.json
python scripts/arc.py audit-hands work/2.aff --bpm 111 --output work/hands.json
python scripts/arc.py audit-playability work/2.aff --bpm 111 --output work/playability.json
python scripts/arc.py audit-special work/2.aff --output work/effects.json
python scripts/arc.py package work/2.aff "song.mp4" --title "Song" --artist "Artist" --bpm 111 --difficulty FTR --chart-constant 10 --jacket cover.jpg --output work/package
```

`package` preserves the authored AFF and creates both an ArcCreate
`arccreate/project.arcproj` and an `official-format/` interchange folder with
`base.ogg`, chart and non-empty `songlist.json`. It is not an installable game mod
or an Arcade-Chan proprietary project.

`prepare` creates analysis, a reference-conditioned brief and a **safe skeleton**;
replace the skeleton with authored work before delivery. Use `package` for the
revised AFF rather than running `prepare` over it. Optional corpus indexing:

```bash
python scripts/arc.py build-index --corpus "/path/to/user-owned/songs" --output cache/index.json
```

Set `ARC_CORPUS_ROOT` or supply `--corpus` explicitly. Set `ARC_CREATE_EXE` only if
editor launch is wanted. Editor/corpus availability is optional for other tasks.
The older `generate_chart.py` and `generate_chart_pack.py` remain compatible
sketch tools. Their preset motion, ground-density or generated-cover defaults do
not implement the phrase-authoring workflow or prove a finished chart.

## Covers and delivery

Prefer a verified network cover of the actual song/release, especially when the
user requests one. Record source page/image, credit, preprocessing and permission
status. Do not substitute generated art for an explicit web-cover request.
For this owner's local workflow the user has requested network artwork; public
redistribution is a separate permission question. Do not bundle unlicensed media
in public skill repositories or releases.

Before delivering, validate AFF separately from project/resource completeness.
Verify every chart/audio and non-empty jacket/background/video reference, actual
cover files and the interchange songlist. Do not fabricate ACBA or
`Arcade/Project.arcade`; let the relevant editor create proprietary formats.

Run hand/contact, density, continuity and effect reviews proportional to the
difficulty. Natural-hand warnings are prompts; resolve intentional cross-hand
routes with an explicit hand plan instead of deleting them to reach zero.
Arctap contact geometry and two-hand sustain spacing are separate checks.
Record unresolved review points and distinguish syntax/resource checks, analysis,
render inspection, listening review and actual device playtesting.

Report the editable outputs and what changed. Counts, exact-repeat diagnostics,
coordinate distances and a target FTR rating are not certificates of novelty,
beauty or playability. Do not present an automated or schematic preview as an
ArcCreate render or an actual playtest.
