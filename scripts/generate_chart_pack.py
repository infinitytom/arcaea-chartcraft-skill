# -*- coding: utf-8 -*-
"""
Generate a multi-difficulty Arcaea chart package by invoking generate_chart.py
for each requested difficulty, then merging the package metadata and zip.
"""
import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


DEFAULTS = {
    0: {"rating": 4, "density": 1.15},
    1: {"rating": 7, "density": 1.65},
    2: {"rating": 9, "density": 2.35},
    3: {"rating": 10, "density": 2.75},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", default="./arcaea_pack_out")
    ap.add_argument("--title", default="Untitled")
    ap.add_argument("--artist", default="Unknown")
    ap.add_argument("--song-id", default=None)
    ap.add_argument("--jacket", default=None)
    ap.add_argument("--chart-designer", default="Codex")
    ap.add_argument("--jacket-designer", default="Codex")
    ap.add_argument("--style", default="auto",
                    choices=["auto", "edm", "rock", "funk", "vocal", "ambient", "hyper"])
    ap.add_argument("--motion", default="auto",
                    choices=["auto", "compact", "normal", "bold", "wild"])
    ap.add_argument("--clip", nargs=2, type=float, default=None, metavar=("START", "END"),
                    help="chart only this time window in seconds")
    ap.add_argument("--bpm", type=float, default=None)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--difficulties", nargs="+", type=int, default=[0, 1, 2],
                    help="difficulty classes to generate, e.g. 0 1 2 3")
    ap.add_argument("--ratings", nargs="*", type=int,
                    help="optional ratings matching --difficulties")
    ap.add_argument("--densities", nargs="*", type=float,
                    help="optional densities matching --difficulties")
    args = ap.parse_args()

    script = Path(__file__).with_name("generate_chart.py")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    ratings = dict(zip(args.difficulties, args.ratings or []))
    densities = dict(zip(args.difficulties, args.densities or []))
    generated = []
    last_songlist = None

    for diff in args.difficulties:
        if diff not in (0, 1, 2, 3):
            raise SystemExit(f"invalid difficulty: {diff}")
        rating = ratings.get(diff, DEFAULTS[diff]["rating"])
        density = densities.get(diff, DEFAULTS[diff]["density"])
        cmd = [
            sys.executable, str(script),
            "--input", args.input,
            "--outdir", str(outdir),
            "--title", args.title,
            "--artist", args.artist,
            "--rating", str(rating),
            "--difficulty", str(diff),
            "--density", str(density),
            "--style", args.style,
            "--motion", args.motion,
            "--seed", str(args.seed + diff * 13),
        ]
        if args.song_id:
            cmd += ["--song-id", args.song_id]
        if args.jacket:
            cmd += ["--jacket", args.jacket]
        if args.clip:
            cmd += ["--clip", str(args.clip[0]), str(args.clip[1])]
        if args.bpm is not None:
            cmd += ["--bpm", str(args.bpm)]
        print("=== generate difficulty", diff, "rating", rating, "density", density, "===")
        subprocess.run(cmd, check=True)
        generated.append(diff)
        last_songlist = json.loads((outdir / "songlist.json").read_text(encoding="utf-8"))

    song = last_songlist["songs"][0]
    difficulties = []
    for diff in range(4):
        if diff in generated:
            rating = ratings.get(diff, DEFAULTS[diff]["rating"])
            difficulties.append({
                "ratingClass": diff,
                "chartDesigner": args.chart_designer,
                "jacketDesigner": args.jacket_designer,
                "rating": rating,
                "ratingPlus": diff >= 2 and rating >= 9,
            })
        else:
            difficulties.append({
                "ratingClass": diff,
                "chartDesigner": "",
                "jacketDesigner": "",
                "rating": -1,
            })
    song["difficulties"] = difficulties
    (outdir / "songlist.json").write_text(
        json.dumps(last_songlist, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    files = [f"{d}.aff" for d in generated]
    files += ["songlist.json", "base.jpg", "base_256.jpg", "base.ogg"]
    zpath = outdir / "output.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for fn in files:
            path = outdir / fn
            if not path.exists():
                raise SystemExit(f"missing expected file: {path}")
            zf.write(path, fn)

    print("=== multi-difficulty package ===")
    for fn in files:
        print(f"  {fn}: {os.path.getsize(outdir / fn):,} bytes")
    print(f"output.zip: {os.path.getsize(zpath):,} bytes")


if __name__ == "__main__":
    main()
