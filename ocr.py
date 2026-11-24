#!/usr/bin/env python3
"""跨平台 OCR：优先 Apple Vision（macOS，中文最准），退回 tesseract。

用法（与 vision-ocr 一致，方便直接替换）:
    ocr.py <图片路径> [更多图片...]

输出: 每行 "<文件名>\\t<识别到的整段文字>"
没装任何 OCR 时退出码 3，调用方据此跳过 OCR 而不是报错。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 依次尝试：中英混合 > 纯英文。有的机器装了 tesseract 却没装中文包
LANG_CHAIN = ("chi_sim+eng", "eng")


def vision_ocr() -> str | None:
    """macOS 自带的 Vision 二进制，装过就用。"""
    if sys.platform != "darwin":
        return None
    cand = os.environ.get("DY_OCR") or str(HERE / "vision-ocr")
    if Path(cand).exists() and os.access(cand, os.X_OK):
        return cand
    return None


def tesseract() -> str | None:
    env = os.environ.get("DY_TESSERACT")
    if env:
        return env if Path(env).exists() else None
    return shutil.which("tesseract")


def run_vision(binary: str, files: list[str]) -> list[str]:
    p = subprocess.run([binary] + files, capture_output=True, text=True)
    if p.returncode != 0:
        return []
    return p.stdout.splitlines()


def _ocr_one(binary: str, f: str, lang: str) -> tuple[list[str], str]:
    """返回 (识别到的行, 是否语言包缺失)。"""
    try:
        p = subprocess.run(
            [binary, f, "stdout", "-l", lang, "--psm", "6"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace")  # tesseract 会吐出非 UTF-8 字节
    except OSError:
        return [], False
    if "Failed loading language" in (p.stderr or ""):
        return [], True
    if p.returncode != 0:
        return [], False
    return [line.strip() for line in p.stdout.splitlines() if line.strip()], False


def run_tesseract(binary: str, files: list[str]) -> list[str]:
    out: list[str] = []
    lang = LANG_CHAIN[0]
    for f in files:
        lines, missing = _ocr_one(binary, f, lang)
        if missing and lang != LANG_CHAIN[-1]:
            # 中文包没装/装坏了，退回纯英文；总比整段跳过强
            lang = LANG_CHAIN[-1]
            lines, _ = _ocr_one(binary, f, lang)
        if lines:
            out.append(Path(f).name + "\t" + " ".join(lines))
    return out


def main() -> None:
    files = sys.argv[1:]
    if not files:
        sys.exit(0)

    binary = vision_ocr()
    if binary:
        lines = run_vision(binary, files)
        if lines:
            print("\n".join(lines))
            return

    binary = tesseract()
    if binary:
        lines = run_tesseract(binary, files)
        if lines:
            print("\n".join(lines))
            return

    print("ERROR: 没有可用的 OCR（macOS 装 Vision，其他平台装 tesseract）", file=sys.stderr)
    sys.exit(3)


if __name__ == "__main__":
    main()
