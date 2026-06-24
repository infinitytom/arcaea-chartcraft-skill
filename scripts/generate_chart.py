# -*- coding: utf-8 -*-
"""
Arcaea chart package generator.

Produces <difficulty>.aff + songlist.json + base.jpg/base_256.jpg + base.ogg (+ output.zip)
from an audio file, following the principles documented in SKILL.md:
  - empirically grid-searched BPM on a fixed uniform 16th lattice (timing accuracy)
  - HPSS + pyin melody tracking -> pitch-following arcs (expression)
  - color-continuous arc chains (good hand feel)
  - light drum backbone, real scoring notes (valid Arcaea scoring)

Deps: pip install librosa numpy pillow soundfile   (ffmpeg NOT required)

Usage:
  python generate_chart.py --input song.mp3 --outdir ./out \
      --title "Title" --artist "Artist" --rating 9 [--jacket cover.jpg]
      [--difficulty 2] [--density 2.2] [--style auto] [--motion auto] [--clip START END] [--seed 11]
"""
import argparse, json, os, re, zipfile, sys
import numpy as np

def log(*a): print(*a, flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="input audio (mp3/wav/ogg/...)")
    ap.add_argument("--outdir", default="./arcaea_out")
    ap.add_argument("--title", default="Untitled")
    ap.add_argument("--artist", default="")
    ap.add_argument("--song-id", default=None)
    ap.add_argument("--rating", type=int, default=9)
    ap.add_argument("--difficulty", type=int, default=2, help="0 Past 1 Present 2 Future 3 Beyond")
    ap.add_argument("--jacket", default=None, help="cover image; if omitted a gradient is generated")
    ap.add_argument("--density", type=float, default=2.2, help="target ground notes/sec")
    ap.add_argument("--clip", nargs=2, type=float, default=None, metavar=("START", "END"),
                    help="chart only this time window (seconds); avoid unless asked")
    ap.add_argument("--bpm", type=float, default=None, help="override detected BPM")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--style", choices=["auto", "edm", "rock", "funk", "vocal", "ambient", "hyper"],
                    default="auto", help="charting language / arc-height palette")
    ap.add_argument("--motion", choices=["auto", "compact", "normal", "bold", "wild"], default="auto",
                    help="hand-travel intensity and groove accent strength")
    ap.add_argument("--no-melody", action="store_true", help="drum-only fallback (skip HPSS/pyin)")
    args = ap.parse_args()

    import librosa
    import soundfile as sf
    np.random.seed(args.seed)
    os.makedirs(args.outdir, exist_ok=True)
    hop = 512
    sid = args.song_id or re.sub(r"[^a-z0-9]+", "_", args.title.lower()).strip("_") or "custom_song"

    log("=== load ===")
    ys, sr = librosa.load(args.input, sr=None, mono=False)
    y = librosa.to_mono(ys) if ys.ndim > 1 else ys
    DUR = len(y) / sr
    ar = 22050
    ya = librosa.resample(y, orig_sr=sr, target_sr=ar) if sr != ar else y

    # chart window
    T0 = max(0.0, args.clip[0]) if args.clip else 0.0
    T1 = min(DUR, args.clip[1]) if args.clip else DUR
    CHART_END = T1 - 1.0 if not args.clip else T1

    # ---- harmonic / percussive separation ----
    if args.no_melody:
        yh = yp = ya
    else:
        log("=== HPSS ===")
        yh, yp = librosa.effects.hpss(ya)

    def onsets(sig):
        of = librosa.onset.onset_detect(y=sig, sr=ar, hop_length=hop, backtrack=True)
        env = librosa.onset.onset_strength(y=sig, sr=ar, hop_length=hop)
        return librosa.frames_to_time(of, sr=ar, hop_length=hop), env[of]
    perc_t, perc_s = onsets(yp)
    harm_t, harm_s = onsets(yh)
    log(f"perc onsets={len(perc_t)} harm onsets={len(harm_t)}")

    # ---- BPM: empirical grid search (principle 1) ----
    _ot = librosa.frames_to_time(
        librosa.onset.onset_detect(y=ya, sr=ar, hop_length=hop, backtrack=True), sr=ar)
    _ot = _ot[(_ot >= T0) & (_ot <= T1)]
    def gerr(bpm_):
        """Return (normalized_error, abs_error_s, best_phase). Normalizing by the
        16th spacing makes the objective scale-invariant, so a denser (faster)
        grid is NOT trivially favored — avoids the high-BPM aliasing trap."""
        six = 60.0 / bpm_ / 4.0
        best, bph = 1e9, 0.0
        for ph in np.linspace(0, six, 40, endpoint=False):
            r = np.abs(((_ot - ph) + six/2) % six - six/2).mean()
            if r < best: best, bph = r, ph
        return best / six, best, bph
    if args.bpm:
        bpm = args.bpm; ne, snap_err, phase16 = gerr(bpm)
    elif len(_ot) > 4:
        # coarse search over a sensible base-tempo band [85,175] using NORMALIZED error
        scan = [(gerr(b)[0], b) for b in np.arange(85.0, 175.01, 0.25)]
        base_ne = min(scan, key=lambda z: z[0])[0]
        # among near-ties (within 15% of best), prefer the LOWEST bpm (base tempo, not an octave-up)
        cands = sorted(b for ne_, b in scan if ne_ <= base_ne * 1.15)
        center = cands[0]
        c2 = min(((gerr(b)[0], b) for b in np.arange(center-1.5, center+1.51, 0.02)),
                 key=lambda z: z[0])
        bpm = c2[1]; _, snap_err, phase16 = gerr(bpm)
    else:
        tempo, _ = librosa.beat.beat_track(y=ya, sr=ar)
        bpm = float(np.atleast_1d(tempo)[0]); _, snap_err, phase16 = gerr(bpm)

    period = 60.0 / bpm
    eighth = period / 2.0
    sixteenth = period / 4.0
    first = phase16 + sixteenth * np.ceil((T0 - phase16) / sixteenth)
    grid16 = np.arange(first, T1, sixteenth)
    if len(grid16) < 2:
        sys.exit("audio too short / no grid")
    anchor = float(grid16[0])
    AUDIO_OFFSET = int(round(anchor * 1000))
    if args.style != "auto":
        style = args.style
    elif bpm >= 155:
        style = "hyper"
    elif bpm >= 124 and len(perc_t) >= len(harm_t) * 0.75:
        style = "edm"
    elif bpm <= 90 and len(harm_t) > len(perc_t) * 0.9:
        style = "ambient"
    else:
        style = "vocal"
    log(f"DUR={DUR:.1f}s BPM={bpm:.2f} (snap err={snap_err*1000:.1f}ms) "
        f"AudioOffset={AUDIO_OFFSET} style={style}")
    if args.motion != "auto":
        motion = args.motion
    else:
        motion = ["compact", "normal", "bold", "wild"][int(np.clip(args.difficulty, 0, 3))]
    motion_cfg = {
        "compact": dict(x_scale=1.00, oob=0.00, y_amp=0.90, jump=0.45, lane_wide=0.10, accent=0.00),
        "normal": dict(x_scale=1.12, oob=0.06, y_amp=1.05, jump=0.55, lane_wide=0.28, accent=0.25),
        "bold": dict(x_scale=1.32, oob=0.18, y_amp=1.25, jump=0.70, lane_wide=0.52, accent=0.55),
        "wild": dict(x_scale=1.55, oob=0.30, y_amp=1.45, jump=0.85, lane_wide=0.72, accent=0.85),
    }[motion]
    log(f"motion={motion}")

    def gidx(t):
        j = int(np.clip(np.searchsorted(grid16, t), 0, len(grid16) - 1))
        if j > 0 and abs(grid16[j-1]-t) <= abs(grid16[j]-t): j -= 1
        return j
    def snap(t): return float(grid16[gidx(t)])
    def ms(t): return int(round((t - anchor) * 1000))

    # ---- pitch tracking (principle 2) ----
    voiced = None
    if not args.no_melody:
        log("=== pyin pitch ===")
        try:
            f0, _, _ = librosa.pyin(yh, fmin=130, fmax=1318, sr=ar, hop_length=hop)
            f0_t = librosa.frames_to_time(np.arange(len(f0)), sr=ar, hop_length=hop)
            voiced = np.nan_to_num(f0, nan=0.0) > 0
            semi = np.full_like(f0, np.nan); semi[voiced] = 12*np.log2(f0[voiced]/130.0)
            smin, smax_ = np.nanpercentile(semi, 5), np.nanpercentile(semi, 95)
        except Exception as e:
            log("pyin failed, drum-only fallback:", e); voiced = None
    def pitch_x(t):
        if voiced is None: return None
        i = int(np.clip(np.searchsorted(f0_t, t), 0, len(f0)-1))
        if not voiced[i]: return None
        return float(np.clip((semi[i]-smin)/max(1e-6, smax_-smin), 0.0, 1.0))
    def pitch_lane(t):
        x = pitch_x(t); return None if x is None else int(np.clip(1+round(x*3), 1, 4))

    # voiced phrases
    phrases = []
    if voiced is not None and voiced.any():
        vi = np.where(voiced)[0]; start = prev = f0_t[vi[0]]
        for k in vi[1:]:
            if f0_t[k]-prev > 0.28:
                if prev-start > period*0.9: phrases.append((max(start, anchor), prev))
                start = f0_t[k]
            prev = f0_t[k]
        if prev-start > period*0.9: phrases.append((max(start, anchor), prev))
    log(f"voiced phrases={len(phrases)}")

    # ---- note containers ----
    notes = []
    lane_busy = {1: [], 2: [], 3: [], 4: []}
    def lane_free(l, a, b): return all(not (a < e and s < b) for (s, e) in lane_busy[l])
    counts = dict(tap=0, hold=0, play_arc=0, arctap=0, trace=0)

    def styled_x(x, phrase_i, playable):
        scale = motion_cfg["x_scale"]
        if (not playable) and style in ("edm", "hyper") and phrase_i % 4 == 0:
            scale *= 1.14
        if (not playable) and style == "funk" and phrase_i % 5 == 2:
            scale *= 1.06
        oob = 0.0 if playable else motion_cfg["oob"]
        sx = 0.5 + (x - 0.5) * scale
        return float(np.clip(sx, -oob, 1.0 + oob))

    def styled_y(t, x, phrase_i, playable, syl_density):
        beat_pos = (t - anchor) / max(1e-6, period)
        wave = 0.5 + 0.5 * np.sin((beat_pos / 4.0 + phrase_i * 0.17) * 2 * np.pi)
        if style == "edm":
            base = 0.22 if phrase_i % 3 == 0 else 0.72
            y = base + 0.28 * wave
        elif style == "rock":
            y = 0.28 + 0.42 * (0.65 * x + 0.35 * wave)
        elif style == "funk":
            y = 0.26 + 0.55 * (0.55 * x + 0.45 * (1.0 - wave))
        elif style == "ambient":
            y = 0.35 + 0.58 * (0.5 * x + 0.5 * wave)
        elif style == "hyper":
            y = 0.18 + 0.78 * (wave if phrase_i % 2 else 1.0 - wave)
        else:  # vocal
            phrase_mode = phrase_i % 5
            contour = 0.7 * x + 0.3 * wave
            if phrase_mode in (1, 3):
                y = 0.18 + 0.24 * contour  # low response phrase
            elif phrase_mode in (2, 4):
                y = 0.78 + 0.20 * contour  # vocal peak phrase
            else:
                y = 0.38 + 0.58 * contour
        if playable:
            y = max(y, 0.18)
        if syl_density >= 2.5 and not playable:
            y = min(1.0, y + 0.08)
        y = 0.5 + (y - 0.5) * motion_cfg["y_amp"]
        return float(np.clip(y, 0.10, 1.00))

    def emit_contour(pts, color, playable, taps=None, phrase_i=0, syl_density=0.0):
        flag = "false" if playable else "true"
        taps = sorted(taps) if taps else []
        for k in range(len(pts)-1):
            t1, x1 = pts[k]; t2, x2 = pts[k+1]
            sx1, sx2 = styled_x(x1, phrase_i, playable), styled_x(x2, phrase_i, playable)
            y1 = styled_y(t1, x1, phrase_i, playable, syl_density)
            y2 = styled_y(t2, x2, phrase_i, playable, syl_density)
            ez = "si" if sx2 > sx1+0.02 else ("so" if sx2 < sx1-0.02 else "s")
            seg = f"arc({ms(t1)},{ms(t2)},{sx1:.2f},{sx2:.2f},{ez},{y1:.2f},{y2:.2f},{color},none,{flag})"
            if not playable:
                inside = [tt for tt in taps if t1-1e-4 <= tt < t2-1e-4]
                if inside:
                    seg += "[" + ",".join(f"arctap({ms(tt)})" for tt in inside) + "]"
                    counts["arctap"] += len(inside)
            notes.append((ms(t1), seg + ";"))
            counts["play_arc" if playable else "trace"] += 1

    def build_contour(t0, t1):
        j0, j1 = gidx(t0), gidx(t1)
        idxs = list(range(j0, j1+1, 2)) or [j0]
        if idxs[-1] != j1: idxs.append(j1)
        raw = [(grid16[j], pitch_x(grid16[j])) for j in idxs]
        xs = [x for _, x in raw]; last = 0.5
        for i in range(len(xs)):
            if xs[i] is None: xs[i] = last
            last = xs[i]
        sm = xs[:]
        for i in range(1, len(xs)-1): sm[i] = float(np.median(xs[i-1:i+2]))
        for i in range(1, len(sm)):
            d = sm[i]-sm[i-1]
            if abs(d) > motion_cfg["jump"]: sm[i] = sm[i-1]+motion_cfg["jump"]*np.sign(d)
            sm[i] = float(np.clip(sm[i], -motion_cfg["oob"], 1.0 + motion_cfg["oob"]))
        return [(raw[i][0], round(sm[i], 2)) for i in range(len(raw))]

    def thin(times, strs, min_gap):
        order = sorted(range(len(times)), key=lambda i: -strs[i]); kept = []
        for i in order:
            if all(abs(times[i]-k) >= min_gap for k in kept): kept.append(times[i])
        return sorted(kept)

    # ---- melody arcs (principles 2-4) ----
    melody_ranges = []; pc = 0
    for phrase_i, (p0, p1) in enumerate(phrases):
        p1 = min(p1, CHART_END)
        if p1-p0 < period*0.9: continue
        pts = build_contour(p0, p1)
        if len(pts) < 2: continue
        syl_idx = [i for i, t in enumerate(harm_t) if p0-eighth <= t <= p1]
        syl_t = [snap(harm_t[i]) for i in syl_idx]; syl_s = [harm_s[i] for i in syl_idx]
        dens = len(syl_t)/max(1e-6, (p1-p0))
        if dens >= 2.0:
            taps = [t for t in thin(syl_t, syl_s, eighth*0.95) if p0-1e-3 <= t < p1-0.001]
            emit_contour(pts, pc, playable=False, taps=taps, phrase_i=phrase_i, syl_density=dens)
        else:
            emit_contour(pts, pc, playable=True, phrase_i=phrase_i, syl_density=dens)
        melody_ranges.append((p0, p1)); pc ^= 1
    def in_melody(t): return any(a-1e-3 <= t <= b+1e-3 for (a, b) in melody_ranges)

    # ---- drum backbone: taps + holds ----
    slot = {}
    for t, s in zip(perc_t, perc_s):
        if t < anchor-eighth or t > CHART_END: continue
        slot[gidx(t)] = max(slot.get(gidx(t), 0.0), s)
    smax = max(slot.values()) if slot else 1.0
    ranked = sorted(slot.items(), key=lambda kv: kv[1], reverse=True)
    keep_full = set(k for k, _ in ranked[:int(args.density*(CHART_END-anchor))]) | \
                set(k for k in slot if k % 4 == 0)
    prev_lane = 2; order = sorted(slot.items())
    for idx, (gi, raw) in enumerate(order):
        t = grid16[gi]; s = raw/smax; melo = in_melody(t)
        if melo:
            if not (s > 0.6 and gi % 2 == 0): continue
        else:
            if gi not in keep_full: continue
        pl = pitch_lane(t); near = False
        if len(harm_t):
            j = int(np.clip(np.searchsorted(harm_t, t), 0, len(harm_t)-1))
            near = min(abs(harm_t[j]-t), abs(harm_t[max(0, j-1)]-t)) < 0.06
        if pl and near:
            base = pl
        elif np.random.random() < motion_cfg["lane_wide"]:
            base = 1 if prev_lane >= 3 else 4
        else:
            base = int(np.clip(2+np.random.choice([-1, 0, 1, 1]), 1, 4))
        lane = base; tries = 0
        while lane == prev_lane and tries < 3:
            if np.random.random() < motion_cfg["lane_wide"]:
                lane = 1 if lane >= 3 else 4
            else:
                lane = int(np.clip(base+np.random.choice([-1, 1]), 1, 4))
            tries += 1
        t_ms = ms(t)
        nxt = order[idx+1][0] if idx+1 < len(order) else gi+4
        gap = (nxt-gi)*sixteenth
        if (not melo) and gap >= period and (s > 0.35 or gi % 4 == 0):
            dur = max(period*0.5, min(gap-sixteenth, period*2.0))
            a, b = t_ms, t_ms+int(round(dur*1000))
            if lane_free(lane, a, b):
                notes.append((a, f"hold({a},{b},{lane});")); lane_busy[lane].append((a, b))
                prev_lane = lane; counts["hold"] += 1; continue
        a, b = t_ms, t_ms+60
        if lane_free(lane, a, b):
            notes.append((a, f"({t_ms},{lane});")); lane_busy[lane].append((a, b))
            prev_lane = lane; counts["tap"] += 1

    # ---- groove accents: strong sky hits tied to the drum grid ----
    if motion_cfg["accent"] > 0 and slot:
        accent_budget = int((CHART_END - anchor) * motion_cfg["accent"] * 0.18)
        accent_candidates = [(gi, raw) for gi, raw in ranked if gi % 2 == 0 and not in_melody(grid16[gi])]
        min_gap = 4 if motion in ("normal", "bold") else 3
        kept = []
        for gi, raw in accent_candidates:
            if len(kept) >= accent_budget:
                break
            if all(abs(gi - old) >= min_gap for old in kept):
                kept.append(gi)
        for n, gi in enumerate(sorted(kept)):
            t0 = grid16[gi]
            t1 = grid16[min(len(grid16) - 1, gi + (3 if motion == "wild" else 2))]
            if t1 <= t0:
                continue
            color = n % 2
            if color == 0:
                x1, x2 = -motion_cfg["oob"], 1.0 + motion_cfg["oob"]
            else:
                x1, x2 = 1.0 + motion_cfg["oob"], -motion_cfg["oob"]
            y1 = 0.18 if n % 4 < 2 else 0.88
            y2 = 0.88 if n % 4 < 2 else 0.18
            ats = [ms(t0)]
            if motion in ("bold", "wild"):
                ats.append(ms(grid16[min(len(grid16) - 1, gi + 1)]))
            seg = (f"arc({ms(t0)},{ms(t1)},{x1:.2f},{x2:.2f},s,{y1:.2f},{y2:.2f},"
                   f"{color},none,true)[" + ",".join(f"arctap({a})" for a in ats) + "];")
            notes.append((ms(t0), seg))
            counts["trace"] += 1
            counts["arctap"] += len(ats)

    # ---- emit + validate ----
    notes.sort(key=lambda x: x[0])
    lines = [f"AudioOffset:{AUDIO_OFFSET}", "-", f"timing(0,{bpm:.2f},4.00);"] + [t for _, t in notes]
    aff_name = f"{args.difficulty}.aff"
    aff_path = os.path.join(args.outdir, aff_name)
    with open(aff_path, "w", encoding="utf-8") as f: f.write("\n".join(lines)+"\n")
    prob = []
    tap_seen = set()
    audit_events = []
    audit_y = []
    audit_x = []
    tap_sequence = []
    for ln in lines[3:]:
        mt = re.match(r"^\((\d+),([1-4])\);$", ln)
        if mt:
            key = (int(mt.group(1)), int(mt.group(2)))
            if key in tap_seen:
                prob.append("duplicate tap: " + ln)
            tap_seen.add(key)
            audit_events.append(key[0])
            tap_sequence.append(key)
            continue
        mh = re.match(r"^hold\((\d+),(\d+),[1-4]\);$", ln)
        if mh:
            a, b = int(mh.group(1)), int(mh.group(2))
            if b <= a:
                prob.append(ln)
            audit_events.extend([a, b])
            continue
        ma = re.match(
            r"^arc\((\d+),(\d+),([-0-9.]+),([-0-9.]+),[^,]+,"
            r"([-0-9.]+),([-0-9.]+),\d+,none,(?:true|false)\)(.*);$",
            ln,
        )
        if ma:
            a, b = int(ma.group(1)), int(ma.group(2))
            x1, x2 = float(ma.group(3)), float(ma.group(4))
            y1, y2 = float(ma.group(5)), float(ma.group(6))
            if b < a:
                prob.append(ln)
            audit_events.extend([a, b])
            audit_x.extend([x1, x2])
            audit_y.extend([y1, y2])
            for at in map(int, re.findall(r"arctap\((\d+)\)", ma.group(7))):
                if not (a <= at <= b):
                    prob.append("arctap outside parent: " + ln)
                audit_events.append(at)
            continue
        prob.append("unparsed: " + ln)
    scoring = counts["tap"]+counts["hold"]+counts["arctap"]+counts["play_arc"]
    sixteenth_ms = sixteenth * 1000.0
    def grid_err(t_):
        return abs(((t_ + sixteenth_ms / 2.0) % sixteenth_ms) - sixteenth_ms / 2.0)
    max_grid_err = max((grid_err(t_) for t_ in audit_events), default=0.0)
    low_y = sum(y < 0.35 for y in audit_y) / max(1, len(audit_y))
    mid_y = sum(0.35 <= y < 0.75 for y in audit_y) / max(1, len(audit_y))
    high_y = sum(y >= 0.75 for y in audit_y) / max(1, len(audit_y))
    x_oob = sum(x < 0.0 or x > 1.0 for x in audit_x) / max(1, len(audit_x))
    tap_sequence.sort()
    lane_jumps = [abs(b[1] - a[1]) for a, b in zip(tap_sequence, tap_sequence[1:])]
    lane_jump_avg = float(np.mean(lane_jumps)) if lane_jumps else 0.0
    lane_wide = sum(j >= 2 for j in lane_jumps) / max(1, len(lane_jumps))
    log(f"\n=== chart === taps:{counts['tap']} holds:{counts['hold']} "
        f"playArc:{counts['play_arc']} arctaps:{counts['arctap']} traces:{counts['trace']}")
    log(f"discrete scoring:{scoring}  melodyPhrases:{len(melody_ranges)}  validate:{len(prob)} problems")
    log(f"audit: maxGridErr={max_grid_err:.2f}ms yLow/Mid/High={low_y:.2f}/{mid_y:.2f}/{high_y:.2f} "
        f"xOOB={x_oob:.2f} laneJumpAvg={lane_jump_avg:.2f} laneWide={lane_wide:.2f}")
    for p in prob[:8]: log("  ", p)

    # ---- songlist.json ----
    diffs = [{"ratingClass": rc, "chartDesigner": "", "jacketDesigner": "", "rating": -1}
             for rc in range(3)]
    while len(diffs) <= args.difficulty:
        diffs.append({"ratingClass": len(diffs), "chartDesigner": "", "jacketDesigner": "", "rating": -1})
    diffs[args.difficulty] = {"ratingClass": args.difficulty, "chartDesigner": "Codex",
                              "jacketDesigner": "Codex", "rating": args.rating, "ratingPlus": False}
    songlist = {"songs": [{"id": sid, "title_localized": {"en": args.title},
        "artist": args.artist, "bpm": str(int(round(bpm))), "bpm_base": round(bpm, 1),
        "set": "base", "purchase": "", "audioPreview": 0, "audioPreviewEnd": 12000,
        "side": 0, "bg": "base", "date": 1700000000, "version": "", "difficulties": diffs}]}
    with open(os.path.join(args.outdir, "songlist.json"), "w", encoding="utf-8") as f:
        json.dump(songlist, f, indent=2, ensure_ascii=False)

    # ---- jacket ----
    from PIL import Image, ImageDraw, ImageFont
    if args.jacket and os.path.exists(args.jacket):
        raw = Image.open(args.jacket).convert("RGB"); w, h = raw.size; sd = min(w, h)
        cr = raw.crop(((w-sd)//2, (h-sd)//2, (w+sd)//2, (h+sd)//2))
    else:
        arr = np.zeros((512, 512, 3), np.uint8)
        for r in range(512):
            arr[r, :] = [int(20+r/512*40), int(10+r/512*20), int(80+r/512*100)]
        cr = Image.fromarray(arr); d = ImageDraw.Draw(cr)
        try: fnt = ImageFont.truetype("arial.ttf", 40)
        except Exception: fnt = ImageFont.load_default()
        bb = d.textbbox((0, 0), args.title, font=fnt)
        d.text(((512-(bb[2]-bb[0]))//2, 230), args.title, fill="white", font=fnt)
    cr.resize((512, 512), Image.LANCZOS).save(os.path.join(args.outdir, "base.jpg"), quality=92)
    cr.resize((256, 256), Image.LANCZOS).save(os.path.join(args.outdir, "base_256.jpg"), quality=92)

    # ---- base.ogg (clip if requested), chunked stereo write ----
    if args.clip:
        s0, s1 = int(T0*sr), int(T1*sr)
        seg = (ys[:, s0:s1] if ys.ndim > 1 else ys[s0:s1])
        fade = int(0.05*sr); segm = np.atleast_2d(seg)
        if segm.shape[1] > 2*fade:
            segm[:, :fade] *= np.linspace(0, 1, fade); segm[:, -fade:] *= np.linspace(1, 0, fade)
        exp = segm.T
    else:
        exp = (ys.T if ys.ndim > 1 else ys[:, None])
    with sf.SoundFile(os.path.join(args.outdir, "base.ogg"), "w", sr, exp.shape[1],
                      format="OGG", subtype="VORBIS") as f:
        for i in range(0, len(exp), 441000): f.write(exp[i:i+441000])

    # ---- package ----
    files = [aff_name, "songlist.json", "base.jpg", "base_256.jpg", "base.ogg"]
    zpath = os.path.join(args.outdir, "output.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for fn in files: zf.write(os.path.join(args.outdir, fn), fn)
    log("\n=== files ===")
    for fn in files: log(f"  {fn}: {os.path.getsize(os.path.join(args.outdir, fn)):,} bytes")
    log(f"output.zip: {os.path.getsize(zpath):,} bytes\nDone -> {args.outdir}")

if __name__ == "__main__":
    main()
