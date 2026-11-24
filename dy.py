#!/usr/bin/env python3
"""抖音分享链接 -> 拆解素材包（元数据 + 逐字稿 + 画面文字 + Obsidian 笔记）

用法:
    dy.py "<任意含抖音链接的文本，整段分享文案直接粘>"
    dy.py --local <视频文件> --url <原链> --title <标题> --author <作者> --id <id>

转写为分段模式：按静音点切块，逐块落盘，中断后重跑会跳过已完成的分块。

产出:
    <DY_VAULT>/<日期> <标题>.md       默认 ./视频拆解
    ~/.cache/dy-digest/<id>/           （视频、音频、帧、info.json 留档）

退出码 0 = 成功，非 0 = 失败（stderr 有原因）。
最后一行打印一段 JSON，给上层（Claude）读结构化结果。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_silent(cmd):
    """只关心退出码的调用。"""
    try:
        return subprocess.run(cmd, capture_output=True, text=True).returncode
    except OSError:
        return -1


def _tool(env_key, names, extra=()):
    """先看环境变量，再找 PATH，最后试几个常见安装位置。找不到就原样返回名字，
    留给调用时报错（错误信息里能看到到底缺什么）。"""
    v = os.environ.get(env_key)
    if v:
        return v
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for p in extra:
        if Path(p).exists():
            return p
    return names[0]


YTDlp = _tool("DY_YTDLP", ["yt-dlp"], [
    "/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp", str(HERE / "bin/yt-dlp")])
FFMPEG = _tool("DY_FFMPEG", ["ffmpeg"], [
    "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "C:/ffmpeg/bin/ffmpeg.exe"])
# OCR 走 ocr.py：macOS 用编译好的 vision-ocr，其他平台退回 tesseract
OCR_SCRIPT = HERE / "ocr.py"


def _python_with_faster_whisper():
    """挑一个能 import faster_whisper 的解释器：环境变量 > 当前解释器 > 常见 venv。"""
    candidates = [os.environ.get("DY_VENV_PY"), sys.executable]
    home = Path.home()
    for rel in (".venvs/dy-digest/bin/python", ".venvs/dy/bin/python",
                ".venvs/dy-digest/Scripts/python.exe", ".venvs/dy/Scripts/python.exe"):
        candidates.append(str(home / rel))
    for c in candidates:
        if not c or not Path(c).exists():
            continue
        p = run_silent([c, "-c", "import faster_whisper"])
        if p == 0:
            return c
    return sys.executable


PY = _python_with_faster_whisper()


def _default_vault():
    # Windows 上没有 ~/Documents 这个习惯用法，落到 Videos 下
    return Path.home() / ("Videos/视频拆解" if os.name == "nt" else "Documents/视频拆解")


VAULT = Path(os.environ.get("DY_VAULT") or _default_vault())
CACHE = Path(os.environ.get("DY_CACHE") or (Path.home() / ".cache/dy-digest"))
WHISPER_MODEL = os.environ.get("DY_WHISPER_MODEL", "small")
FRAME_INTERVAL = 2.0      # 每 2 秒抽一帧做 OCR
MAX_FRAMES = 90           # 最多 90 帧（3 分钟）

URL_RE = re.compile(r"https?://[^\s\"'<>，。、）)]+")

sys.path.insert(0, str(HERE))
import douyin_web  # noqa: E402  仅标准库，做 yt-dlp 的兜底



def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def pick_url(text):
    for m in URL_RE.findall(text or ""):
        m = m.rstrip("，。、）)")
        if "douyin.com" in m or "iesdouyin.com" in m:
            return m
    return None


def download(url, work):
    """返回 (video_path, info_dict)。yt-dlp 失败时走网页端兜底。"""
    info_json = work / "info.json"
    cmd = [
        YTDlp, "--no-playlist", "--no-warnings",
        "-f", "bv*+ba/b",
        "--write-info-json", "-o", str(work / "video.%(ext)s"),
        url,
    ]
    p = run(cmd)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        print("  yt-dlp 失败（%s），改走网页端直链" % " / ".join(tail), file=sys.stderr)
        return download_web(url, work)
    cand = list(work.glob("video.*"))
    vids = [f for f in cand if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".flv")]
    if not vids:
        die("下载完成但没找到视频文件：" + str(cand))
    info = {}
    if info_json.exists():
        info = json.loads(info_json.read_text(encoding="utf-8"))
    return vids[0], info


def download_web(url, work):
    """不依赖登录态：申请 ttwid 后读 iesdouyin 分享页拿无水印直链。"""
    dest = work / "video.mp4"
    try:
        info = douyin_web.download(url, dest)
    except douyin_web.DouyinError as e:
        die("下载失败：yt-dlp 要 cookie，网页端兜底也不行（%s）" % e)
    (work / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest, info



def extract_audio(video, work):
    wav = work / "audio.wav"
    p = run([FFMPEG, "-v", "error", "-y", "-i", str(video),
             "-vn", "-ar", "16000", "-ac", "1", str(wav)])
    if p.returncode != 0 or not wav.exists():
        die("抽音轨失败：" + (p.stderr or "")[:200])
    return wav


def transcribe(wav, work):
    """分段转写（静音点切块、逐块落盘、可续跑），返回 [{start,end,text}]"""
    out = work / "transcript.json"
    chunker = HERE / "transcribe_chunked.py"
    env = dict(os.environ)
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # HuggingFace 在国内直连不通
    p = subprocess.run(
        [PY, str(chunker), str(wav), str(work), WHISPER_MODEL, "zh", "300", "3"],
        stdout=subprocess.PIPE, text=True, env=env,
    )
    if p.returncode != 0:
        die("转写失败（错误见上方进度输出）")
    return json.loads(out.read_text(encoding="utf-8"))


def ocr_frames(video, work, duration):
    frames_dir = work / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    # 长视频自动放宽抽帧间隔，保证整段都覆盖到
    step = FRAME_INTERVAL
    if duration and duration / FRAME_INTERVAL > MAX_FRAMES:
        step = duration / MAX_FRAMES
    n = min(MAX_FRAMES, max(1, int(duration / step) if duration else 1))
    run([FFMPEG, "-v", "error", "-y", "-i", str(video),
         "-vf", "fps=1/%g" % step, str(frames_dir / "f_%03d.jpg")])
    files = sorted(frames_dir.glob("f_*.jpg"))[:n]
    if not files:
        return []
    p = run([PY, str(OCR_SCRIPT)] + [str(f) for f in files])
    if p.returncode != 0:
        if (p.stderr or "").strip():
            print("  OCR 跳过：" + (p.stderr or "").strip().splitlines()[-1], file=sys.stderr)
        return []
    out = []
    prev = None
    for line in p.stdout.splitlines():
        name, _, text = line.partition("\t")
        text = text.strip()
        if not text or text == prev:
            continue
        prev = text
        idx = int(re.sub(r"\D", "", name) or 0)
        out.append({"t": round((idx - 1) * step, 1), "text": text})
    return out


def hhmmss(sec):
    sec = int(sec or 0)
    return "%d:%02d" % (sec // 60, sec % 60)


def safe_name(s, limit=60):
    s = re.sub(r"[/\\:*?\"<>|\n\r#\[\]]", " ", s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s[:limit] or "未命名"


def _section(md, heading):
    """取出 markdown 里某个二级标题底下的正文（到下一个 ## 为止）。"""
    m = re.search(r"^" + re.escape(heading) + r"\s*$(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1) if m else ""


def write_note(info, url, segs, frames, work, video):
    VAULT.mkdir(parents=True, exist_ok=True)
    title = info.get("title") or (segs[0]["text"][:30] if segs else "抖音视频")
    dur = info.get("duration") or (segs[-1]["end"] if segs else 0)
    day = time.strftime("%Y-%m-%d")
    path = VAULT / ("%s %s.md" % (day, safe_name(title)))

    lines = [
        "---",
        "title: %s" % title,
        "author: %s" % (info.get("uploader") or info.get("uploader_id") or ""),
        "duration: %s" % hhmmss(dur),
        "url: %s" % url,
        "video_id: %s" % (info.get("id") or ""),
        "collected: %s" % time.strftime("%Y-%m-%d %H:%M"),
        "---",
        "",
        "# %s" % title,
        "",
        "作者：%s ｜ 时长：%s ｜ 原链：%s" % (
            info.get("uploader") or "?", hhmmss(dur), url),
    ]
    for k, label in (("view_count", "播放"), ("like_count", "点赞"),
                     ("comment_count", "评论"), ("repost_count", "转发")):
        if info.get(k) is not None:
            lines.append("%s：%s" % (label, info[k]))
    briefing = "> 待填：这段视频讲了什么、结构、可用的点"
    if path.exists():
        # 重跑时保留上次已经填好的简报，别把人工/AI 写的内容冲掉
        old = _section(path.read_text(encoding="utf-8"), "## 简报")
        if old and "待填" not in old:
            briefing = old.strip()
    lines += ["", "## 简报", "", briefing, ""]
    lines += ["## 逐字稿", ""]
    if segs:
        for s in segs:
            lines.append("**[%s]** %s" % (hhmmss(s["start"]), s["text"]))
            lines.append("")
    else:
        lines += ["（没识别到语音）", ""]
    lines += ["## 画面文字（OCR）", ""]
    if frames:
        for f in frames:
            lines.append("- **[%s]** %s" % (hhmmss(f["t"]), f["text"]))
    else:
        lines += ["（没识别到画面文字）"]
    lines += ["", "## 原始素材", "",
              "- 视频：`%s`" % video, "- 缓存目录：`%s`" % work, ""]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path, title, dur


def main():
    ap = argparse.ArgumentParser(description="抖音链接 -> 拆解素材包")
    ap.add_argument("text", nargs="*", help="含抖音链接的整段分享文案")
    ap.add_argument("--local", help="跳过下载，直接用一个本地视频文件")
    ap.add_argument("--url", default="", help="配合 --local 记录原链接")
    ap.add_argument("--title", default="", help="配合 --local 指定标题")
    ap.add_argument("--author", default="", help="配合 --local 指定作者")
    ap.add_argument("--id", dest="vid", default="", help="配合 --local 指定缓存目录名")
    a = ap.parse_args()

    if a.local:
        video = Path(a.local)
        if not video.exists():
            die("本地视频不存在：" + a.local)
        vid = a.vid or video.stem
        work = CACHE / vid
        work.mkdir(parents=True, exist_ok=True)
        url = a.url
        info = {"title": a.title or video.stem, "uploader": a.author, "id": vid}
        print("[1/4] 使用本地视频 " + str(video), file=sys.stderr)
    else:
        raw = " ".join(a.text)
        if not raw:
            die("用法：dy.py \"<含抖音链接的文本>\"，或用 --local <视频文件>")
        url = pick_url(raw)
        if not url:
            die("这段文字里没找到抖音链接：" + raw[:80])

        m = re.search(r"(?:video|note)/(\d+)", raw)
        if not m:
            # 短链里没有作品 id，展开一次拿到，缓存目录名才稳定、可续跑
            try:
                m = re.match(r"(\d+)", douyin_web.item_id(url))
            except douyin_web.DouyinError:
                m = None
        vid = m.group(1) if m else "u%s" % int(time.time())
        work = CACHE / vid
        work.mkdir(parents=True, exist_ok=True)

        print("[1/4] 下载 " + url, file=sys.stderr)
        video, info = download(url, work)

    print("[2/4] 抽音轨 + 转写（%s，CPU 上大概 1-3 倍速）" % WHISPER_MODEL, file=sys.stderr)
    wav = extract_audio(video, work)
    segs = transcribe(wav, work)

    print("[3/4] 抽帧 + OCR（每 %g 秒一帧）" % FRAME_INTERVAL, file=sys.stderr)
    dur = info.get("duration") or (segs[-1]["end"] if segs else 0)
    frames = ocr_frames(video, work, dur)

    print("[4/4] 写笔记", file=sys.stderr)
    note, title, dur = write_note(info, url, segs, frames, work, video)

    print(json.dumps({
        "ok": True,
        "note": str(note),
        "title": title,
        "duration": hhmmss(dur),
        "author": info.get("uploader") or "",
        "transcript_segments": len(segs),
        "transcript_chars": sum(len(s["text"]) for s in segs),
        "ocr_lines": len(frames),
        "cache": str(work),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
