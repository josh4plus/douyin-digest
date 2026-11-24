#!/usr/bin/env bash
# 一键安装 douyin-digest
#   macOS  : OCR 用 Apple Vision（编译 ocr.swift），不需要额外装东西
#   Linux  : OCR 用 tesseract，需要 chi_sim 语言包；没有就只出逐字稿
#   Windows: 用 Git Bash / WSL 跑本脚本，OCR 同上（tesseract）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${DY_VENV:-$HOME/.venvs/dy-digest}"
OS="$(uname -s)"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# 1. 依赖二进制
case "$OS" in
  Darwin)
    command -v brew >/dev/null || { echo "先装 Homebrew：https://brew.sh"; exit 1; }
    # 只查 ffmpeg；yt-dlp 只是加速路径，失败了还有网页端兜底
    command -v ffmpeg >/dev/null || { say "安装 ffmpeg …"; brew install ffmpeg; }
    command -v yt-dlp >/dev/null || { say "安装 yt-dlp …"; brew install yt-dlp || true; }
    ;;
  Linux)
    for t in ffmpeg python3; do
      command -v "$t" >/dev/null || {
        echo "缺 $t。Debian/Ubuntu: sudo apt install ffmpeg python3 python3-venv"
        exit 1; }
    done
    if ! command -v tesseract >/dev/null; then
      say "提示：没装 tesseract，OCR 会跳过。要中文识别："
      echo "  sudo apt install tesseract-ocr tesseract-ocr-chi-sim"
    fi
    ;;
  *)
    echo "未识别的系统：$OS（Windows 请用 Git Bash 或 WSL 运行本脚本）"
    ;;
esac

# 2. Python venv + faster-whisper
if [ ! -x "$VENV/bin/python" ] && [ ! -x "$VENV/Scripts/python.exe" ]; then
  say "创建 venv：$VENV"
  python3 -m venv "$VENV"
fi
PYBIN="$VENV/bin/python"
[ -x "$PYBIN" ] || PYBIN="$VENV/Scripts/python.exe"

say "安装依赖 …"
"$PYBIN" -m pip install --quiet --upgrade pip
"$PYBIN" -m pip install --quiet -r "$HERE/requirements.txt"

# 3. macOS 才编译 Apple Vision OCR
if [ "$OS" = "Darwin" ]; then
  if [ ! -x "$HERE/vision-ocr" ] || [ "$HERE/ocr.swift" -nt "$HERE/vision-ocr" ]; then
    command -v swiftc >/dev/null || {
      echo "缺 swiftc，装一下命令行工具：xcode-select --install"; exit 1; }
    say "编译 vision-ocr …"
    swiftc -O "$HERE/ocr.swift" -o "$HERE/vision-ocr"
  fi
fi

# 4. 快捷方式（Windows 上是 .cmd 包装）
mkdir -p "$HOME/.local/bin"
if [ "$OS" = "Darwin" ] || [ "$OS" = "Linux" ]; then
  ln -sf "$HERE/dy.py" "$HOME/.local/bin/dy-digest"
  say "已链接：~/.local/bin/dy-digest（确保它在 PATH 里）"
fi

# 5. Claude skill（如果这台机器上有 Claude Code）
SKILL_DIR="$HOME/.claude/skills/douyin-digest"
if [ -d "$HOME/.claude" ]; then
  mkdir -p "$SKILL_DIR"
  cp "$HERE/SKILL.md" "$SKILL_DIR/SKILL.md"
  say "已装 Claude skill：$SKILL_DIR"
fi

# 6. 自检
say "自检 …"
"$PYBIN" -c "import faster_whisper, av; print('  faster-whisper', faster_whisper.__version__, '| av', av.__version__)"
echo "  ffmpeg:    $(command -v ffmpeg || echo 缺失)"
echo "  yt-dlp:    $(command -v yt-dlp || echo '缺失（会直接用网页端兜底）')"
echo "  OCR:       $("$PYBIN" "$HERE/ocr.py" >/dev/null 2>&1 && echo 可用 || echo '不可用（只出逐字稿）')"
echo
say "装好了。试一条："
echo '  dy-digest "整段抖音分享文案 https://v.douyin.com/xxxxx/"'
echo
echo "可选环境变量："
echo "  DY_VAULT        笔记输出目录（默认 ~/Documents/视频拆解）"
echo "  DY_WHISPER_MODEL tiny/base/small/medium（默认 small）"
echo "  DY_VENV_PY      指定带 faster-whisper 的 python"
echo "  DY_TESSERACT    tesseract 路径（非 macOS）"
