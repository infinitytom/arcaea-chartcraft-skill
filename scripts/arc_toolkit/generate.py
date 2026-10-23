from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DIFFICULTY_SETTINGS = {
    "PST": {"beat_stride": 2, "trace_every": 0, "input_arc_every": 0, "extra_onsets": False},
    "PRS": {"beat_stride": 1, "trace_every": 16, "input_arc_every": 32, "extra_onsets": False},
    "FTR": {"beat_stride": 1, "trace_every": 8, "input_arc_every": 16, "extra_onsets": True},
    "ETR": {"beat_stride": 1, "trace_every": 8, "input_arc_every": 12, "extra_onsets": True},
    "BYD": {"beat_stride": 1, "trace_every": 8, "input_arc_every": 12, "extra_onsets": True},
}


def create_chart_brief(
    analysis: dict[str, Any],
    references: list[dict[str, Any]],
    reference_profile: dict[str, Any],
    title: str,
    artist: str,
    difficulty: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "song": {"title": title, "artist": artist, "duration_s": analysis["duration_s"]},
        "target_difficulty": difficulty.upper(),
        "music_style": {
            "acoustic_tags": analysis["style_tags"],
            "global_features": analysis["global_features"],
            "warning": "These are acoustic descriptors, not definitive genre labels.",
        },
        "sections": analysis["sections"],
        "reference_profile": reference_profile,
        "nearest_official_references": references,
        "creative_constraints": [
            "derive principles and gestures; never copy a reference event sequence",
            "select a primary and secondary musical layer for every section",
            "develop two to four motifs across sections instead of reacting to every onset",
            "keep hand flow and readability ahead of visual effects",
            "use timinggroup or scenecontrol only when a section has a specific musical reason",
            "reserve at least one contrasting idea not present in the nearest references",
        ],
        "required_llm_output": {
            "design_notes": "section-by-section layer choice, motifs, hand flow and difficulty curve",
            "chart": "valid AFF text",
            "uncertainties": "low-confidence beat, section or timbre decisions requiring human review",
        },
    }


def render_llm_prompt(brief: dict[str, Any]) -> str:
    compact = json.dumps(brief, ensure_ascii=False, indent=2)
    return f"""你是 ARC 谱面设计助手。请先写设计图，再生成可由 ArcCreate 打开的 AFF 初稿。

必须遵守：
1. 相似官谱只用于抽象规律，不复制连续配置或标志性段落。
2. 不同音乐风格必须采用不同的取音层、密度、空间运动和母题发展。
3. 优先可读性、手序、音乐对应和段落对比；特效后置。
4. 对分析中的低置信度判断明确标注，不能伪装成确定事实。
5. 输出 AFF 后等待程序校验；不要用文字解释替代谱面文件。

结构化制谱简报：
{compact}
"""


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def generate_safe_skeleton(analysis: dict[str, Any], difficulty: str = "FTR") -> str:
    difficulty = difficulty.upper()
    settings = DIFFICULTY_SETTINGS[difficulty]
    beats = [float(value) for value in analysis.get("beat_times_s", [])]
    if len(beats) < 8:
        tempo = max(float(analysis.get("tempo_bpm", 120)), 1)
        beat_length = 60 / tempo
        beats = [index * beat_length for index in range(int(analysis["duration_s"] / beat_length))]
    tempo = float(analysis.get("tempo_bpm", 120))
    tags = set(analysis.get("style_tags", []))
    if "percussive" in tags or "dense" in tags:
        lane_pattern = [1, 3, 2, 4, 2, 3, 1, 4]
    elif "harmonic" in tags and "slow" in tags:
        lane_pattern = [1, 2, 3, 4, 3, 2]
    else:
        lane_pattern = [1, 3, 4, 2]

    occupied_times: set[int] = set()
    lines = ["AudioOffset:0", "-", f"timing(0,{tempo:.2f},4.00);"]
    trace_every = settings["trace_every"]
    if trace_every:
        for index in range(trace_every, len(beats) - 4, trace_every):
            start, end = _ms(beats[index]), _ms(beats[index + 4])
            inner = [_ms(beats[index + step]) for step in (1, 2, 3)]
            occupied_times.update(inner)
            if (index // trace_every) % 2:
                x1, x2, y1, y2 = 0.15, 0.85, 0.25, 0.75
            else:
                x1, x2, y1, y2 = 0.85, 0.15, 0.75, 0.25
            arctaps = ",".join(f"arctap({time})" for time in inner)
            lines.append(f"arc({start},{end},{x1:.2f},{x2:.2f},s,{y1:.2f},{y2:.2f},0,none,true)[{arctaps}];")

    input_every = settings["input_arc_every"]
    if input_every:
        for index in range(input_every // 2, len(beats) - 2, input_every):
            start, end = _ms(beats[index]), _ms(beats[index + 2])
            occupied_times.add(start)
            color = (index // input_every) % 2
            if color == 0:
                x1, x2 = 0.1, 0.35
            else:
                x1, x2 = 0.9, 0.65
            lines.append(f"arc({start},{end},{x1:.2f},{x2:.2f},s,0.35,0.65,{color},none,false);")

    beat_stride = settings["beat_stride"]
    for index in range(0, len(beats), beat_stride):
        time = _ms(beats[index])
        if time in occupied_times or time >= _ms(analysis["duration_s"] - 0.1):
            continue
        lane = lane_pattern[index % len(lane_pattern)]
        if difficulty != "PST" and index > 0 and index % 32 == 0 and index + 1 < len(beats):
            lines.append(f"hold({time},{_ms(beats[index + 1])},{lane});")
        else:
            lines.append(f"({time},{lane});")

    if settings["extra_onsets"]:
        beat_ms = [_ms(value) for value in beats]
        additions = 0
        for onset in analysis.get("salient_onsets", []):
            time = _ms(float(onset["time_s"]))
            if time in occupied_times or min((abs(time - beat) for beat in beat_ms), default=9999) < 90:
                continue
            if any(abs(time - existing) < 100 for existing in occupied_times):
                continue
            lane = lane_pattern[(additions * 3 + 1) % len(lane_pattern)]
            lines.append(f"({time},{lane});")
            occupied_times.add(time)
            additions += 1
            if additions >= max(8, int(analysis["duration_s"] / 8)):
                break

    header, separator, timing, *events = lines
    events.sort(key=lambda line: int(line.split("(", 1)[1].split(",", 1)[0]))
    return "\n".join([header, separator, timing, *events]) + "\n"
