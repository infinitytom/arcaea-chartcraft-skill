# Arcaea `.aff` format & scoring reference

Concise spec for authoring/validating `2.aff` charts. Times are **integer
milliseconds**. Sources: Arcaea charting community (aff.arcaea.icu, arcfutil
docs, ArcCreate), cross-checked against real charts.

## File structure

```
AudioOffset:464
-
timing(0,115.94,4.00);
(261,2);
hold(522,914,4);
arc(0,522,0.00,1.00,si,1.00,1.00,0,none,true)[arctap(0),arctap(261)];
```

- **Line 1 — header.** `AudioOffset:<ms>` = milliseconds of audio before chart
  time 0 (i.e. the audio position of musical time 0). May be negative.
  Optional extra header field `TimingPointDensityFactor:<float>` (default `1`)
  scales how many tick-combos holds/arcs generate. The minimal header is just
  the `AudioOffset` line.
- **Line 2 — `-`** literal separator.
- **Line 3+ — timing groups & notes.** At least one `timing` command must come
  first.

## Timing
`timing(t, bpm, beats_per_bar);` e.g. `timing(0,115.94,4.00);`
- A chart needs a `timing` at `t=0`. Additional `timing(...)` lines create
  tempo/scroll changes (BPM and beats-per-bar). Setting an extreme bpm/divisor
  is how charters do "stops" and SV (scroll-velocity) tricks. Note timestamps
  are absolute ms regardless of timing — timing affects **visual scroll**, not
  when a note is judged. So a single representative BPM in the timing line is
  fine as long as note ms values are accurate.

## Note types

### Ground tap
`(t, lane);` — `lane` ∈ {1,2,3,4}. One tap = 1 combo.

### Hold
`hold(t, t_end, lane);` — `t_end > t`. Generates tick-combo over its length.

### Arc (the sky lines)
`arc(t, t_end, x1, x2, easing, y1, y2, color, fx, isTrace)[arctaps];`
- `x1,x2` — horizontal position at start/end. `0.0`=left edge of lane 1 area,
  `1.0`=right edge of lane 4 area. Values **may go below 0 or above 1**
  (e.g. `-0.25`, `1.25`) for off-field swings.
- `easing` — see below.
- `y1,y2` — height on the sky plane. `0.0`=bottom (near the lanes), `1.0`=top.
- `color` — `0` blue, `1` red, `2` green (rare). **Color = which hand.**
- `fx` — effect name or `none`.
- `isTrace` — `true` = a **trace/skyline guide that scores nothing** (purely
  visual; only arctaps placed on it score). `false` = a **playable arc** the
  player must trace (scores, generates tick-combo).
- Optional `[arctap(t1),arctap(t2),...]` — sky taps placed *on* this arc. Each
  arctap time must lie within `[t, t_end]`. In practice arctaps are attached to
  **trace arcs** (`isTrace=true`) that act as their rail. Each arctap = 1 combo.

### Easing codes
Two characters: **first = x-axis easing, second = y-axis easing.**
`s`=linear, `b`=bezier, `si`=sine-in, `so`=sine-out(cosine).
Examples: `s` (linear x, linear y), `si`/`so` (eased x, linear y),
`sisi` (sine-in both), `siso`, `sosi`, `soso`. Shorthand: when the y-axis easing
is `s` it may be omitted (`sis` ≡ `si` on x with linear y; bare `s` ≡ linear/linear).

## Scoring (confirm charts satisfy this)
- **Max score = 10,000,000 + total_combo** (all shiny/max PURE).
- Per PURE = `10,000,000 / total_combo`; FAR = half; LOST = 0; each shiny PURE +1.
- The engine normalizes, so **any valid chart satisfies the rule** — there is no
  authored number that must "sum to 10M".
- **total_combo / Notes** counts: tap=1, arctap=1, hold = 1 + tick-combo by
  duration, playable arc (`isTrace=false`) = 1 + tick-combo by length, **trace
  (`isTrace=true`) = 0**. Hold/arc ticks scale with `TimingPointDensityFactor`
  and are computed by the engine — the exact in-game Notes count is only known
  after loading in a simulator (ArcCreate / Arcade).

## Validation checklist
- All `lane` ∈ {1,2,3,4}; `hold`/`arc` have `end > start` (`arc` may have
  `end == start` for a point).
- Every `arctap(t)` satisfies `arc_start ≤ t ≤ arc_end` of its parent.
- No duplicate identical note lines; no two taps at the same `(t, lane)`.
- A **connected** playable-arc chain keeps **one color**; different colors only
  for arcs that overlap in time (two-hand patterns). See SKILL.md principle 4.
- Plenty of real scoring objects (not just traces). See principle 6.
- No unexplained multi-second empty gaps unless the audio is silent there.

## Package layout (what Arcaea needs)
`2.aff` (this difficulty's chart; the integer name maps to `ratingClass`:
`0.aff` Past, `1.aff` Present, `2.aff` Future, `3.aff` Beyond), `songlist.json`
(or a `songlist` entry), `base.jpg` + `base_256.jpg` (512²/256² jacket),
`base.ogg` (Vorbis audio). Zip them together.

## songlist.json entry (minimum)
```json
{"songs":[{"id":"my_song","title_localized":{"en":"My Song"},"artist":"",
  "bpm":"116","bpm_base":115.9,"set":"base","audioPreview":0,"audioPreviewEnd":12000,
  "side":0,"bg":"base","date":1700000000,"version":"",
  "difficulties":[{"ratingClass":0,"rating":-1},{"ratingClass":1,"rating":-1},
    {"ratingClass":2,"chartDesigner":"","jacketDesigner":"","rating":9,"ratingPlus":false}]}]}
```
`rating:-1` hides a difficulty. `side` 0=light/1=conflict/2=colorless;
`audioPreview*` are ms bounds of the menu preview loop.
