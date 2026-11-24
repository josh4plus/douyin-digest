#!/usr/bin/env python3
"""分段转写：按静音点切块，逐块落盘，支持中断续跑。

用法:
    transcribe_chunked.py <audio.wav> <work_dir> [model] [lang] [chunk_sec] [beam]

产出:
    <work_dir>/parts/part_000.json ...   每块结果
    <work_dir>/transcript.json           合并后的完整结果
    <work_dir>/chunks.json               切点信息

进度输出到 stderr，最后一行 stdout 打印 JSON 摘要。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import List, Tuple

import os
import shutil

FFMPEG = os.environ.get("DY_FFMPEG") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def die(msg: str) -> None:
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def detect_silences(path: Path, noise: str = "-35dB", min_len: float = 0.6) -> List[Tuple[float, float]]:
    """返回静音区间 [(start, end), ...]，失败时返回空列表。"""
    cmd = [FFMPEG, "-hide_banner", "-i", str(path),
           "-af", "silencedetect=noise=%s:d=%s" % (noise, min_len),
           "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    text = p.stderr or ""
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", text)]
    out: List[Tuple[float, float]] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else s
        if e > s:
            out.append((s, e))
    return out


def pick_cuts(duration: float, chunk: float, silences: List[Tuple[float, float]]) -> List[float]:
    """在目标切点附近挑静音中点，避免从句子中间切。"""
    cuts: List[float] = []
    target = chunk
    while target < duration - 30:
        best = None
        for s, e in silences:
            mid = (s + e) / 2
            if abs(mid - target) <= 90:
                if best is None or abs(mid - target) < abs(best - target):
                    best = mid
        cut = best if best is not None else target
        if not cuts or cut > cuts[-1] + 60:
            cuts.append(cut)
        target += chunk
    return cuts


def slice_wav(src: Path, dst: Path, start: float, end: float) -> None:
    cmd = [FFMPEG, "-v", "error", "-y", "-ss", "%.2f" % start, "-to", "%.2f" % end,
           "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        die("切块失败 %s-%s: %s" % (start, end, (p.stderr or "")[:160]))


def main() -> None:
    if len(sys.argv) < 3:
        die("用法：transcribe_chunked.py <audio.wav> <work_dir> [model] [lang] [chunk_sec] [beam]")
    wav = Path(sys.argv[1])
    work = Path(sys.argv[2])
    model_name = sys.argv[3] if len(sys.argv) > 3 else "small"
    lang = sys.argv[4] if len(sys.argv) > 4 else "zh"
    chunk_sec = float(sys.argv[5]) if len(sys.argv) > 5 else 300.0
    beam = int(sys.argv[6]) if len(sys.argv) > 6 else 3

    parts_dir = work / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    duration = wav_duration(wav)
    cuts = pick_cuts(duration, chunk_sec, detect_silences(wav))
    bounds = [0.0] + cuts + [duration]
    (work / "chunks.json").write_text(json.dumps(bounds, ensure_ascii=False), encoding="utf-8")

    total = len(bounds) - 1
    print("分段：%d 段，总长 %d:%02d" % (total, int(duration // 60), int(duration % 60)), file=sys.stderr)

    from faster_whisper import WhisperModel  # 延迟导入，便于无模型时快速失败

    model = None
    result: List[dict] = []
    for i in range(total):
        start, end = bounds[i], bounds[i + 1]
        part_json = parts_dir / ("part_%03d.json" % i)
        if part_json.exists():
            segs = json.loads(part_json.read_text(encoding="utf-8"))
            print("  [%d/%d] 已完成，跳过（%d 条）" % (i + 1, total, len(segs)), file=sys.stderr)
        else:
            if model is None:
                model = WhisperModel(model_name, device="cpu", compute_type="int8")
            part_wav = parts_dir / ("part_%03d.wav" % i)
            if not part_wav.exists():
                slice_wav(wav, part_wav, start, end)
            t0 = time.time()
            segs_iter, _ = model.transcribe(str(part_wav), language=lang, vad_filter=True,
                                            beam_size=beam, condition_on_previous_text=False)
            segs = []
            for s in segs_iter:
                text = s.text.strip()
                if not text:
                    continue
                segs.append({"start": round(start + s.start, 2),
                             "end": round(start + s.end, 2),
                             "text": text})
            part_json.write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
            print("  [%d/%d] %.1f–%.1f 分钟，%d 条，用时 %.0f 秒" % (
                i + 1, total, start / 60, end / 60, len(segs), time.time() - t0), file=sys.stderr)
        result.extend(segs)

    result.sort(key=lambda x: x["start"])
    (work / "transcript.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "chunks": total, "segments": len(result)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
