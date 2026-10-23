# Stable ARC charting strategy

Snapshot date: 2026-09-02
Canonical source: the maintainer's ARC charting strategy; this portable snapshot
does not require a particular workspace path or access to the reference corpus.

This reference contains only rules considered stable enough to guide normal work. The workspace knowledge file may contain newer evidence that has not yet passed the maintenance gate.

## Music selection

- Choose a primary musical layer per section: melody, defining rhythm, distinctive timbre, vocal phrase, or structural accent. Do not chart every detected onset.
- Repeated kick drums are lower priority than phrase-defining accents, fills, melody turns, vocals, and distinctive instruments unless the kick pattern is itself the section identity.
- Keep recognizable anchor timings across difficulty levels, then selectively add secondary layers, subdivisions, coordination, or spatial motion. Difficulty is not a uniform density multiplier.
- Repeated phrases should retain a recognizable timing or spatial motif while changing with orchestration, energy, and section function.
- Onset alignment has no universal pass percentage. Interpret it with the chosen source layer, confidence, sustained sounds, syncopation, and stem quality.

## Sections and difficulty

- Give each section its own density, object vocabulary, hand-pressure, and recovery budget.
- Treat automatic section roles as ranked hypotheses. Low-confidence sections should be referenced by index and timestamp.
- At a candidate boundary, deliberately choose `attack`, `transform`, or `release`; do not make every boundary an attack.
- PST prioritizes clear beats and small motion; PRS introduces readable sky interaction; FTR develops full hand flow and spatial motifs; ETR/BYD may use stronger coordination and effects but must remain learnable and reproducible.

## Arc, gesture, and hand flow

- Merge same-color input Arc segments only within one timinggroup, with start/end timing differing by at most 1 ms and exactly equal x/y endpoints. This is the same-color subset of ArcCreate's connection rule. Do not merge near-misaligned endpoints with a coordinate tolerance; do not turn exact 1 ms seams into release windows. ArcCreate may connect different-color branches visually, but that alone does not prove one continuous hand gesture.
- Classify cross-color junctions over the complete ArcCreate candidate neighborhood: pool every successor sharing one predecessor and every predecessor sharing one successor across the allowed -1/0/+1 ms range. Exact timing/gap buckets can split a staggered same-color and cross-color branch and falsely label the latter a simple switch. Any same-color competitor or multiple predecessor/successor keeps the relation as a branch/merge; do not infer or generate a one-hand color switch from it. The current 109-chart official scan contains no uncontested forward cross-color candidate.
- Report both object density and gesture density. Prefer gesture density for difficulty, hand pressure, and music alignment.
- Arc color and floor lane give only a natural-hand candidate. Cross-hand, reverse-hand, hand swaps, and multi-finger solutions are valid; automated conflicts require review rather than automatic rejection.
- When an Arc/Hold crosses a section boundary, check occupied candidate hands, new gestures before release, rapid re-entry after release, and whether the other hand has a readable coverage zone.
- Compute Arctap position from its parent Trace using the ArcCreate curve formula. Geometry can be reproduced; mapping x-position to a required hand remains heuristic.

## ArcCreate curve mapping

- `s`: linear on both axes. `b`: cubic Bézier equivalent to `t²(3-2t)` on both axes.
- `I(t)=sin(πt/2)` and `O(t)=1-cos(πt/2)`.
- x axis: `si/sisi/siso → I`; `so/sosi/soso → O`.
- y axis: `si/so → linear`; `sisi/sosi → I`; `siso/soso → O`.
- Curve regression tests must sample a non-symmetric point such as `t=0.25`; midpoint-only tests can hide swapped I/O formulas.

## Arctap spacing and contact ambiguity

- Keep simultaneous Arctap contact points clearly separated. In the current six-chart official FTR/BYD calibration set, 106 simultaneous Arctap pairs had zero ArcCreate-default world-hitbox overlaps.
- Active-Arc proximity and rapid sequential Arctap overlap are review prompts, not automatic failures; official high-difficulty charts use both.
- ArcCreate-default AFF-coordinate diagnostics are `|dx|≤0.2235, |dy|≤0.5556` for an Arctap center near an active input Arc, and `|dx|≤0.3553, |dy|≤0.5556` for standard-width Arctap-pair overlap.
- Those values describe ArcCreate default world-space hitboxes, not a published lowiro/Arcaea judgement specification. Camera, screen geometry, width, judgement modifiers, device, and actual official-game behavior can differ.
- Being reachable by the free hand does not prove freedom from mis-touch. Review timing, dx/dy, occupied hands, Arc head/body proximity, and recovery together.

## Effects and validation

- Special effects need a musical trigger and an exit. Ordinary sections do not receive timinggroups, camera, scenecontrol, overbound traces, or lane changes by default.
- Separate playable input from decorative Trace/noinput events when computing density.
- Classify temporally adjacent Trace events by endpoint geometry before calling them visually glued. Endpoint error `≤0.001` AFF is an intentional-continuation candidate and endpoint distance `>0.08` is a spatially separate re-entry; neither is an automatic issue. Only the near-but-misaligned middle band is an AFF-level review prompt. These are local diagnostic thresholds, not published ArcCreate/lowiro visual rules, and screen-space overlap still requires editor review.
- Validate AFF syntax and time ranges before editor launch. Finite overbound Arc coordinates are design-review warnings, not syntax errors; non-finite coordinates remain invalid. Audit cramped gaps, simultaneous inputs, Arc tension, trace visual glue, hand occupancy, Arctap proximity, density spikes, and special effects in proportion to difficulty.
- Treat AFF validity and project completeness as separate gates. Before opening or delivering, parse the ArcCreate `.arcproj` and verify every chart/audio path plus each non-empty jacket/background/video path exists. The official-style folder must contain at least one difficulty AFF, `base.ogg`, and a `songlist.json` with a non-empty `songs` array.
- A valid AFF and passing tests do not prove official-level chart quality. First-read clarity, musical correspondence, physical flow, and target difficulty require human playtesting.
