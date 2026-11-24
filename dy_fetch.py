#!/usr/bin/env python3
"""抖音链接 -> 下载合流 -> 调用 dy.py 出素材包。

用法:
    dy_fetch.py "<含抖音链接的分享文案>"

前置：ego-browser 已登录抖音（本机 ego lite）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import shutil

HERE = Path(__file__).resolve().parent
EGO = os.environ.get("DY_EGO") or shutil.which("ego-browser") or str(Path.home() / ".local/bin/ego-browser")
FFMPEG = os.environ.get("DY_FFMPEG") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
DY = str(HERE / "dy.py")
CACHE = Path(os.environ.get("DY_CACHE") or (Path.home() / ".cache/dy-digest"))
PY = sys.executable
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
URL_RE = re.compile(r"https?://[^\s\"'<>，。、）)]+")


def die(msg: str) -> None:
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def pick_url(text: str) -> str:
    for m in URL_RE.findall(text or ""):
        m = m.rstrip("，。、）)")
        if "douyin.com" in m:
            return m
    die("没找到抖音链接")


def ego_script(url: str) -> str:
    return """
(async () => {
const task = await taskSpace("dy-fetch");
const page = task.page("p1");
await page.goto(%s, { waitUntil: "domcontentloaded", timeout: 45000 });
await page.waitForTimeout(5000);

async function grab() {
  return await page.evaluate(() => {
    const us = performance.getEntriesByType('resource').map(e => e.name);
    const v = us.filter(x => x.includes('media-video')).slice(-1)[0] || null;
    const a = us.filter(x => x.includes('media-audio')).slice(-1)[0] || null;
    const el = document.querySelector('video');
    return {
      url: location.href,
      title: document.title.replace(/\\s*-\\s*抖音\\s*$/, ''),
      duration: el ? el.duration : null,
      video: v, audio: a,
      author: (document.querySelector('[data-e2e="video-author"]') || {}).innerText || ''
    };
  });
}

let info = await grab();
if (!info.video || !info.audio) {
  await page.evaluate(async () => {
    if (navigator.serviceWorker) {
      for (const r of await navigator.serviceWorker.getRegistrations()) {
        try { await r.unregister(); } catch (e) {}
      }
    }
  });
  await page.reload({ waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForTimeout(4000);
}
if (!info.video || !info.audio) {
  await page.evaluate(() => {
    const el = document.querySelector('video');
    if (el) { el.muted = true; el.currentTime = Math.min(20, (el.duration || 30) * 0.2); el.play().catch(() => {}); }
  });
  for (let i = 0; i < 10; i++) {
    await page.waitForTimeout(2000);
    info = await grab();
    if (info.video && info.audio) break;
  }
}
console.log("RESULT:" + JSON.stringify(info));
})();
""" % json.dumps(url, ensure_ascii=False)


def fetch_urls(url: str) -> dict:
    p = subprocess.run([EGO, "nodejs"], input=ego_script(url), capture_output=True, text=True, timeout=180)
    combined = (p.stdout or "") + "\n" + (p.stderr or "")  # ego 把脚本输出写到 stderr
    if p.returncode != 0:
        die("浏览器抓流失败：" + combined[-300:])
    for line in combined.splitlines():
        if line.startswith("RESULT:"):
            return json.loads(line[len("RESULT:"):])
    die("浏览器没有返回媒体地址：" + combined[-300:])


def download(url: str, dst: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.douyin.com/"})
    total = 0
    with urllib.request.urlopen(req, timeout=180) as r, dst.open("wb") as f:
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    return total


def main() -> None:
    if len(sys.argv) < 2:
        die('用法：dy_fetch.py "<含抖音链接的分享文案>"')
    url = pick_url(" ".join(sys.argv[1:]))
    print("[1/4] 浏览器解析 " + url, file=sys.stderr)
    info = fetch_urls(url)
    if not info.get("video") or not info.get("audio"):
        die("没抓到音视频地址（可能被风控或链接失效）")

    vid = re.search(r"(?:video|note)/(\d+)", info.get("url") or url)
    vid = vid.group(1) if vid else "u%s" % int(__import__("time").time())
    work = CACHE / vid
    work.mkdir(parents=True, exist_ok=True)

    print("[2/4] 下载音视频", file=sys.stderr)
    v_size = download(info["video"], work / "video.mp4")
    a_size = download(info["audio"], work / "audio.m4a")
    print("      video %.1fMB / audio %.1fMB" % (v_size / 1048576, a_size / 1048576), file=sys.stderr)

    print("[3/4] 合流", file=sys.stderr)
    merged = work / "merged.mp4"
    p = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(work / "video.mp4"),
                        "-i", str(work / "audio.m4a"), "-c", "copy", "-movflags", "+faststart", str(merged)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        die("合流失败：" + (p.stderr or "")[:200])

    print("[4/4] 转写 + OCR + 写笔记", file=sys.stderr)
    title = re.split(r"\s*#", info.get("title") or "")[0][:40] or "抖音视频"
    p = subprocess.run([PY, DY, "--local", str(merged), "--url", info.get("url") or url,
                        "--title", title, "--author", info.get("author") or "", "--id", vid])
    sys.exit(p.returncode)


if __name__ == "__main__":
    main()
