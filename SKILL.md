---
name: arcaea-chart-generator
description: >-
  Generate a complete, playable Arcaea fan-made chart package (2.aff chart,
  songlist.json, jacket image, base.ogg audio, zipped) from an audio file. Use
  this skill whenever the user wants to make an Arcaea chart, beatmap, or
  "自制谱面/谱面" from a song or .mp3, mentions a 2.aff file, Arcaea songlist.json,
  arc/arctap/hold/tap notes, AudioOffset/timing groups, or asks to auto-generate
  a rhythm-game chart that follows a song's melody and beat. Trigger even when
  the user only says "make a chart for this song" in an Arcaea context, or asks
  to improve the note placement / arc feel / timing accuracy of an existing
  generated chart.
---

# Arcaea Chart Generator

Turn an audio file into a full Arcaea chart package. The heavy lifting lives in
`scripts/generate_chart.py`; this document explains how to run it and — more
importantly — the **musical principles** that separate a chart that "follows the
drums and feels off" from one that expresses the song. Read
`references/aff_format.md` for exact `.aff` syntax and scoring rules.

## What it produces

A folder (and `output.zip`) containing the files Arcaea needs: one or more
difficulty charts (`0.aff`/`1.aff`/`2.aff`/`3.aff`), `songlist.json`,
`base.jpg` (+`base_256.jpg`), and `base.ogg`. Drop the zip into a custom-song
slot in an Arcaea fan client.

For jacket art, prefer a real online cover image when available (official song,
album, artist, streaming, or high-quality listing artwork). Crop it square and
export `base.jpg`/`base_256.jpg`. Generated placeholder art is only a fallback
when no suitable cover can be found or web access is unavailable. Record the
source URL in the work notes/final response when a web image is used.

## Workflow

1. **Install deps** (once): `pip install librosa numpy pillow soundfile`.
   `soundfile` writes OGG directly, so **ffmpeg is not required**. (On Windows
   the song's filename may contain non-ASCII characters — pass the path as an
   argument; the script reads it with librosa, which handles Unicode.)

2. **Run the generator:**
   ```bash
   python scripts/generate_chart.py --input "song.mp3" --outdir ./out \
       --title "Song Title" --artist "Artist" --rating 9
   ```
   Useful flags: `--jacket cover.jpg` (use a real/online cover instead of a generated
   gradient), `--difficulty 2` (0=Past,1=Present,2=Future,3=Beyond),
   `--density 2.4` (target ground notes/sec), `--clip 34 106` (only chart a
   time window — **avoid unless asked**, see principle 5), `--seed N`.
   It prints a full diagnostic + audit and writes `output.zip`. Use
   `--style auto|edm|rock|funk|vocal|ambient|hyper` to choose the charting
   language and arc-height palette. Use
   `--motion auto|compact|normal|bold|wild` to control hand-travel intensity
   and groove-accent strength.

   For a multi-difficulty pack:
   ```bash
   python scripts/generate_chart_pack.py --input "song.mp3" --outdir ./out \
       --title "Song Title" --artist "Artist" --difficulties 0 1 2 \
       --style auto
   ```
   Use `--difficulties 0 1 2 3` when the song deserves a Beyond chart. The pack
   helper uses different density/rating defaults per difficulty, merges
   `songlist.json`, and zips all generated `.aff` files together. It also
   supports `--clip START END`, `--jacket cover.jpg`, `--motion bold|wild`,
   `--chart-designer NAME`, and `--jacket-designer NAME`.

3. **Report** the detected BPM, AudioOffset, note breakdown, and the validation
   line. Then offer to tune (see "Tuning" below). If the user playtested and
   gave feedback, map it to the principles below rather than guessing.

## The principles that actually matter

These are the lessons that make the difference. The script implements them, but
you need to understand them to diagnose feedback and tune correctly.

### 1. Verify BPM empirically — do not trust the first estimate
`librosa.beat.beat_track` is frequently wrong (it picks octaves/related tempos,
and its estimate shifts with sample rate). A BPM that is even ~1 off
**progressively misaligns the entire chart** — this is the #1 cause of "some
notes feel off / 不太准". The script instead **grid-searches the BPM** (and grid
phase) that minimizes the snap error of detected onsets, then builds **one fixed
uniform 16th-note lattice** at that tempo. A fixed lattice also avoids the
jitter you get from per-beat detected positions. If the user reports timing
feels off, re-check the searched BPM before touching anything else.

### 2. Express the melody, not just the drums (HPSS + pitch)
A naive onset detector fires mostly on percussive transients, so the chart
becomes a drum transcription that ignores the vocal and the airy synth/piano
lines — it feels expressionless. Fix: **HPSS** (`librosa.effects.hpss`) splits
the audio into harmonic (vocal + synth) and percussive (drums). Then:
- **Drums** drive a *light* ground-tap backbone.
- **Vocals/synth** drive the melodic content. Run `librosa.pyin` to track the
  melody's pitch, and make **arcs trace that pitch contour** — high pitch → high
  x, low pitch → low x. This is what makes the chart feel connected to what the
  player hears.
- Map ground-tap **lanes to vocal pitch** when a melodic note is present.

### 3. Two ways to chart a melody — pick by syllable density
- **Busy vocal phrase** (many syllables/sec): a **pitch-guide trace arc**
  (`isTrace=true`) following the contour, with **one arctap per syllable**
  (thin them so no two are closer than an 8th note — machine-gun arctaps feel
  awful and don't match airy music).
- **Sustained / ethereal glide** (few onsets, long held notes): a **playable
  arc** (`isTrace=false`) the player traces. This is the "空灵" airy feel.

### 4. Arc color = hand. This is the single most common feel-killer.
A **connected arc trace must stay ONE color** — segments chain end-to-end
(`end_x` of one = `start_x` of the next), same color, so a single hand traces it
without switching. **Colors only differ when two arcs play at the same instant**
(one per hand — e.g. a two-hand mirror converging at center). Putting blue→red
on a *joined* path forces a mid-trace hand switch and feels terrible. Also keep
x-motion smooth: clamp per-step jumps (≈≤0.5 of the field) so arcs are
ergonomic, not spastic.

### 5. Don't hard-clip the song into an abrupt start/stop
Charting the full song is the default. A blunt clip that begins and ends
mid-phrase feels jarring. Only clip when the user explicitly asks, and prefer a
window that starts/ends on phrase boundaries (or splice sections) so the audio
still feels whole. Use `--clip` sparingly.

### 6. Know the scoring rule, and keep real scoring notes
Max score = **10,000,000 + (total combo)**; each note's PURE value =
`10,000,000 / total_combo`, FAR = half, plus +1 per shiny (max) PURE. The game
normalizes automatically, so any *valid* chart "satisfies" the rule — there is
no number you author that must sum to 10M. The real trap: **trace arcs
(`isTrace=true`) score nothing** (only the arctaps on them do). A chart made
mostly of traces looks busy but plays empty. Ensure plenty of genuine scoring
objects: taps, holds, arctaps, and playable arcs. The script prints the discrete
scoring count; the in-game Notes count is higher because holds and long playable
arcs add tick-combo (computed by the engine, scaled by `TimingPointDensityFactor`
which defaults to 1).

### 7. Shorten audio by musical editing, not by blunt truncation
When the user asks for a shorter chart, make a radio-edit style arrangement
instead of simply clipping seconds off the front or back. Prefer cuts at bar
boundaries and phrase boundaries: intro -> verse -> chorus -> bridge/drop ->
final chorus/outro. Preserve downbeat alignment after every splice. Use short
equal-power crossfades (roughly 30-120 ms) only where the material can mask the
join; for drum-heavy edits, cut exactly before the transient instead. Re-check
BPM grid and AudioOffset after splicing because even a clean-sounding edit can
move the musical anchor.

Practical editing recipe:
- Detect candidate sections by onset novelty, harmonic change, and low vocal
  activity.
- Snap cut points to the fixed beat grid, usually whole bars.
- Keep at least one setup phrase before a chorus/drop so the chart has musical
  breathing room.
- After export, listen to the joins before charting; if a splice calls attention
  to itself, move it by one or two beats or include the phrase tail.

### 8. Learn from previews as pattern vocabulary, not as copies
Use public chart previews (Bilibili, YouTube, ArcCreate communities, and local
renderers) as a study source for readability and hand-feel. Extract principles,
not exact note strings:
- Identify the musical role of a pattern: vocal trace, percussion stream,
  sustained synth arc, accent hit, camera/scroll gimmick, or two-hand set piece.
- For novelty, give a song-specific visual idea a small recurring motif. Example:
  a song about unstable space can use sparse mirrored trace rails or height
  shifts; keep it readable and avoid covering the main melody with decorations.
- Separate "spectacle" from "input burden": trace rails can sell an idea without
  forcing extra fingers, while arctaps/holds provide the real scoring texture.
- Check that each hard pattern has a preparation beat and a release beat. A cool
  idea that surprises the hands unfairly should become a trace or be delayed.
- Use preview/render tools to audit dense sections for overlap, hidden arctaps,
  hand-color confusion, and long empty stretches.

### 9. Let the music genre choose the charting language
Different songs should not all become the same tap-stream plus pitch arc chart.
Before generating or tuning, identify the dominant musical language and choose
patterns that express it:
- EDM / rhythm-game core: strong grid, clear drops, repeatable motifs, higher
  arctap density, and more deliberate two-hand sky patterns. Save the hardest
  density for drops or climax phrases.
- Rock / metal: drums and guitar attacks matter. Use ground taps for kick/snare
  accents, short holds for power chords or sustained guitar, and rougher angular
  arcs for riffs. Avoid over-smoothing everything into vocal-like curves.
- Funk / jazz / city pop: chart the groove and syncopation. Use off-beat taps,
  short holds, lane shifts, and tasteful sky accents. Leave room for swing and
  bass movement; do not quantize the feel into a flat constant stream.
- Vocal pop / ballad / anime song: the vocal line leads. Use pitch-following
  playable arcs or trace rails with syllable arctaps, and keep percussion support
  lighter unless the arrangement opens up.
- Ambient / cinematic / orchestral: prioritize long playable arcs, slow height
  changes, sparse taps, and phrase-scale motion. Silence and held notes should
  feel intentional, not empty.
- Hyperpop / breakcore / very dense electronic: use bursts, stutters, and visual
  glitches sparingly. Thin impossible subdivisions into readable accents, and
  use trace effects to imply chaos without making the hands unreadable.

Genre is a starting point, not a cage. If a song changes section style, change
the chart language with it: verse can be vocal-led, chorus can be groove-led,
bridge can be arc-led, and final chorus can combine the established motifs.

### 10. Build a difficulty ladder, not one isolated chart
One song can and often should have multiple difficulties. Do not make lower
difficulties by blindly deleting notes from the hardest chart; each level should
teach the same song with a different amount of information:
- Past / 0: keep the beat, phrase starts, obvious vocal or lead accents, and
  simple long arcs. Avoid dense arctaps and confusing hand switches.
- Present / 1: add syncopation, short holds, clearer melody tracing, and a few
  easy sky taps. Preserve readability more than spectacle.
- Future / 2: express the full arrangement: melody arcs, percussion accents,
  off-beat groove, section motifs, and moderate two-hand sky patterns.
- Beyond / 3: add the song-specific "thesis": harder hand choreography, timing
  or camera gimmicks, denser arctap bursts, off-field sweeps, or unusual arc
  height language. It still needs to be musically justified.

Across difficulties, keep the same identity motifs but change their burden. A
BYD mirrored trace set piece can become one high arc in FTR, a simple sky tap
phrase in PRS, and a ground-tap accent in PST.

### 11. Use the full Arcaea height and arc vocabulary
A local corpus study of 249 `.aff` charts showed why the old generator felt too
samey: strong charts do not live only at `y=1.00`. In Future charts, low arc
endpoints were common, high endpoints were common, mid-height was used sparingly,
and many charts used some off-field x movement. Treat this as vocabulary:
- High arcs (`y≈0.75-1.00`) are good for vocal peaks, bright synths, and climax
  identity motifs.
- Low arcs (`y≈0.00-0.35`) are good for bass, guitar/riff pressure, darker
  sections, crouched tension, and "under the hand" motion.
- Mid arcs (`y≈0.35-0.75`) should be transitional or ergonomic, not the default
  resting place for every phrase.
- Off-field x (`x<0` or `x>1`) works for sweeps, drops, and visual release, but
  keep playable arcs ergonomic; use trace rails when the motion is spectacle.
- Short arc cuts and point-like arcs can express stutters/glitches. Long arcs
  express sustained melody, pads, strings, or vocal slides.
- Timing/camera/scene tricks are a spice, not a substitute for采音. Use them only
  when the song has a clear stop, glitch, impact, reverse, or dramatic transition.

### 12. Study tutorials and previews as a chart-design workflow
Public ArcCreate lessons, "how I charted" videos, Bilibili fan-chart tags, and
chart preview playlists all point to the same workflow: do not jump straight
from audio analysis to notes. Create a chart concept first, then implement and
audit it.

Use this pre-chart checklist:
- Song thesis: one sentence that says what the chart should feel like. Examples:
  "glass fragments drifting upward", "low wind pressure with sudden lift",
  "mechanical grid breaking apart", or "vocal duet as two hand colors".
- Section map: mark intro, verse, buildup, drop/chorus, bridge, final chorus,
  outro. Give each section a role: teach, develop, contrast, climax, release.
- Motif bank: define 2-4 recurring pattern families before placing details.
  Reuse them with variation instead of inventing unrelated gimmicks every bar.
- Hand story: decide which hand owns each long arc or repeated sky lane. A cool
  visual is not good if it forces ambiguous hand swaps.
- Difficulty story: decide what each difficulty reveals. Lower difficulties
  should preview motifs; higher difficulties complete or invert them.

Innovation rules:
- A gimmick needs a musical trigger: stop, reverse, lyric image, riser, drop,
  instrument entrance, rhythmic break, or timbral change.
- New visual ideas should appear first in a readable form, then intensify later.
  Surprise the eyes before surprising the hands.
- Prefer "spectacle as trace, burden as scoring notes": use non-scoring trace
  rails, camera, or scenecontrol to sell an idea, and use taps/holds/arctaps for
  the playable core.
- Do not let effects hide采音. After adding a gimmick, re-check that the notes a
  player actually hits still align with the music.
- If a motif appears only once and does not connect to the song's thesis, remove
  it or turn it into a quieter background trace.

Audit workflow after generation:
- Watch or render at least the densest and most unusual sections, not only the
  first 30 seconds.
- Check for "same-height fatigue": too many arcs living in the same y band.
- Check for "same-input fatigue": long runs of only playable arcs, only arctaps,
  or only ground taps without section reason.
- Check for "unearned BYD language": camera/timing/off-field tricks in lower
  difficulties should be rare and gentle.
- Keep a short study log: source/video type, observed pattern, when to use it,
  and when not to use it. Never copy exact patterns from a chart preview.

### 13. Reflect after every generated chart
After each real chart request, do a short postmortem and update either the chart
or this skill when the same weakness appears twice. Do not treat generation as
finished just because the `.aff` parser says it is valid.

Known failure modes to watch:
- Same-height fatigue: too many arcs in one y band, especially mid/high arcs.
- Same-input fatigue: long stretches of only playable arcs, only arctaps, or only
  ground taps without a section reason.
- Melody-only blindness: the vocal contour is followed, but drums, bass, guitar,
  piano comping, or sound-design accents are ignored.
- Decoration drift: hand-added motifs look cool but are not snapped to the BPM
  lattice or a detected onset.
- Trace overload: the chart looks busy, but real scoring notes are too sparse.
- Difficulty cloning: 0/1/2/3 charts differ only by density instead of teaching
  different layers of the same song.
- Weak identity: the chart has no song-specific thesis or recurring motif.
- Metadata shortcuts: missing artist, placeholder jacket, wrong preview window,
  or generated art when a real cover is easy to find.

Minimum reflection checklist before delivery:
- Report BPM, AudioOffset, validation count, note breakdown, and audit metrics:
  max grid error, low/mid/high arc-height ratio, off-field x ratio, average
  lane jump, and wide-lane jump ratio.
- If `maxGridErr` is more than a few milliseconds for hand-added objects,
  re-snap or remove those objects.
- If one height band dominates without musical reason, remap some arcs into low,
  high, off-field, short-cut, or sustained-arc vocabulary.
- If a difficulty ladder was generated, compare the identities of 0/1/2/3, not
  only their note counts.
- If a real online jacket was used, include its source URL in the final response.

### 14. Be bold when the music wants body movement
Avoid over-correcting into safe, small, polite charts. A good Arcaea chart often
feels physical: the hands travel, accents land with the beat, and repeated
motifs make the player "dance" through the chart. Boldness is not random
difficulty; it is larger motion attached to clear musical triggers.

Use `--motion auto` by default. It maps lower difficulties to smaller movement
and higher difficulties to larger movement: Past is compact, Present is normal,
Future is bold, Beyond is wild. Override it when the user asks for a calmer or
more explosive chart.

Bold-motion tools:
- Wider ground-lane jumps on strong beats, especially 1<->4 or 4<->1 responses.
- Off-field trace sweeps for drops, fills, lyric images, and strong drum hits.
- Low-to-high or high-to-low arcs that make the hand travel vertically with the
  phrase energy.
- Short arctap accent rails on percussion hits to make the rhythm tactile.
- Repeated left/right motifs that develop over sections instead of isolated
  one-off decorations.

Guardrails:
- Big movement must still be snapped to the BPM lattice or detected onset.
- Do not stack wide jumps every beat; give preparation and release beats.
- Playable arcs can be bold, but extreme off-field motion should often be trace
  plus arctaps so the spectacle does not become unreadable.
- For groove-heavy songs, emphasize syncopated accents and lane travel rather
  than only raising density.

## Tuning (map feedback → action)
- "too dense / too hard" → lower `--density`; "too empty" → raise it.
- "arcs not smooth / 不顺手" → principle 4 (color continuity + jump clamp).
- "timing off / 不准" → principle 1 (re-verify BPM).
- "doesn't capture the vocals/synth" → principle 2–3 (melody coverage).
- "want more holds/texture" → the script exposes hold thresholds near the
  bottom of its drum-backbone loop; relax the gap/strength gates.
- "too conservative / not enough movement / no groove" → raise `--motion` to
  `bold` or `wild`, then re-check grid accuracy and hand readability.

## Validate before delivering
The script self-audits (lanes 1–4, hold/arc `end>start`, arctaps inside their
parent arc's time range, no duplicate/stacked notes, color-continuity, density
gaps). Always confirm `validate: 0 problems` and that there are no unexplained
multi-second empty gaps (unless the song is genuinely silent there). See
`references/aff_format.md` for the full grammar and more checks.

For manual post-processing, never place decorative motifs by raw timestamps
alone. Snap every added tap, hold endpoint, arctap, and arc endpoint back to the
searched BPM lattice (usually 16ths or deliberate 8ths/quarters), then compare
important accents against detected onsets. If a visual idea lands more than a
few milliseconds away from the intended grid/onset, move it or remove it; chart
accuracy beats novelty.

The generator prints an audit line for this purpose. Treat `validate: 0 problems`
as the syntax floor, not the quality ceiling.
