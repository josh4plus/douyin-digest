# douyin-digest · 抖音视频转笔记

把一条抖音分享链接，变成一篇可读的 markdown 拆解笔记：

**元数据 + 逐字稿（带时间轴）+ 画面文字（OCR）+ 待填简报**

一条命令，不需要登录抖音，不需要 Cookie。

```
抖音链接
  │
  ├─ 1. 下载视频 + 元数据 ────────────────────────────────
  │     先试 yt-dlp；报 "Fresh cookies needed" 时自动切换网页端兜底
  │     申请 ttwid → 读 iesdouyin 分享页 → 拿无水印直链
  │
  ├─ 2. ffmpeg 抽音轨 → faster-whisper 转写 ───────────────
  │     按静音点自动切块，逐块落盘，中断后重跑会跳过已完成的分块
  │
  ├─ 3. ffmpeg 每 2 秒抽一帧 → OCR ───────────────────────
  │     macOS 用 Apple Vision（中文很准）
  │     Linux / Windows 用 tesseract；都没有就跳过这一步
  │
  └─ 4. 写成 markdown ────────────────────────────────────
        <输出目录>/<日期> <标题>.md
```

---

## 一、安装

### macOS

需要先有 [Homebrew](https://brew.sh) 和 Xcode 命令行工具（`xcode-select --install`，为了编译 OCR）。

```bash
git clone https://github.com/josh4plus/douyin-digest.git
cd douyin-digest
./setup.sh
```

脚本会：

1. 装 `ffmpeg`（`yt-dlp` 可选，没有就走网页端兜底）
2. 建 venv `~/.venvs/dy-digest`，装 faster-whisper
3. 用 `swiftc` 编译 Apple Vision OCR
4. 软链 `~/.local/bin/dy-digest`
5. 如果本机有 `~/.claude/`，顺带把 skill 装进 `~/.claude/skills/douyin-digest/`

### Linux

```bash
sudo apt install ffmpeg python3 python3-venv
# 想要中文画面文字识别，再加：
sudo apt install tesseract-ocr tesseract-ocr-chi-sim

git clone https://github.com/josh4plus/douyin-digest.git
cd douyin-digest
./setup.sh
```

### Windows

在 **Git Bash** 或 **WSL** 里跑安装（`setup.sh` 是 bash 脚本）：

```bash
git clone https://github.com/josh4plus/douyin-digest.git
cd douyin-digest
./setup.sh
```

装完之后日常用 `dy-digest.cmd` 调用（它指向 venv 里的 python）。
中文 OCR 同样需要装 tesseract + `chi_sim` 语言包。

### 首次运行会下载模型

Whisper 模型（默认 `small`，约 500MB）第一次运行才下载。
国内直连 HuggingFace 不通，脚本默认走 `hf-mirror.com` 镜像。

> 要换模型：先 `export DY_WHISPER_MODEL=medium`，再跑。`tiny/base/small/medium` 越大越准越慢。

---

## 二、使用

### 基本用法

把抖音 App「复制链接」得到的**整段文字**直接粘进去，不用手工截链接：

```bash
dy-digest "7.43 复制打开抖音，看看【某某】的作品 https://v.douyin.com/xxxxx/ ..."
```

脚本会自己从这堆文字里挑出抖音链接。

Windows 上：

```bash
./dy-digest.cmd "7.43 复制打开抖音 ... https://v.douyin.com/xxxxx/"
```

### 输出

跑完最后一行是 JSON，给上层程序（比如 Claude）读结果：

```json
{"ok": true,
 "note": "/Users/you/Documents/视频拆解/2026-11-24 标题.md",
 "title": "标题",
 "duration": "0:57",
 "author": "作者昵称",
 "transcript_segments": 24,
 "transcript_chars": 313,
 "ocr_lines": 28,
 "cache": "/Users/you/.cache/dy-digest/7694938814749396265"}
```

笔记长这样：

```markdown
---
title: 你英语差的话，就一定要去看动画片。
author: 杨妈妈颠覆英语-前沿教育
duration: 0:57
url: https://v.douyin.com/xxxxx/
video_id: 7694938814749396265
collected: 2026-11-24 20:18
---

# 你英语差的话，就一定要去看动画片。

作者：杨妈妈颠覆英语-前沿教育 ｜ 时长：0:57 ｜ 原链：...

## 简报

> 待填：这段视频讲了什么、结构、可用的点

## 逐字稿

**[0:00]** 你英语差的话就一定要去看动画片

**[0:02]** 从零基础到雅思 7

...

## 画面文字（OCR）

- **[0:06]** 第一个月：《米奇妙妙屋》

...

## 原始素材

- 视频：`~/.cache/dy-digest/7694938814749396265/video.mp4`
```

「简报」那一段是留给你（或你的 AI）填的。**重跑同一条视频不会冲掉已经写好的简报**。

### 已经下载过视频？

跳过下载，只跑转写和 OCR：

```bash
dy-digest --local ./video.mp4 \
  --url "https://v.douyin.com/xxxxx/" \
  --title "标题" --author "作者" --id 1234567890
```

### 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功，stdout 最后一行有 JSON |
| 1 | 失败，stderr 上有 `ERROR:` 开头的具体原因 |

---

## 三、配置

全部靠环境变量，不改代码。

| 变量 | 作用 | 默认 |
|---|---|---|
| `DY_VAULT` | 笔记输出目录 | macOS/Linux `~/Documents/视频拆解`，Windows `~/Videos/视频拆解` |
| `DY_CACHE` | 中间文件（视频/音频/帧/分块） | `~/.cache/dy-digest` |
| `DY_WHISPER_MODEL` | whisper 模型 | `small` |
| `DY_VENV_PY` | 指定带 faster-whisper 的 python | 自动探测 |
| `DY_FFMPEG` / `DY_YTDLP` | 覆盖二进制路径 | 走 PATH |
| `DY_OCR` | 指定 macOS 的 vision-ocr 二进制 | 仓库内的编译产物 |
| `DY_TESSERACT` | 指定 tesseract 路径 | 走 PATH |
| `HF_ENDPOINT` | HuggingFace 镜像 | `https://hf-mirror.com` |

例：把笔记直接写进 Obsidian 库：

```bash
export DY_VAULT="$HOME/MyVault/视频拆解"
dy-digest "https://v.douyin.com/xxxxx/"
```

---

## 四、配合 Claude Code / 其他 Agent

`SKILL.md` 是一个 [Claude Code](https://claude.com/claude-code) 的 skill 定义。
`setup.sh` 检测到 `~/.claude/` 会自动装进去；手动装也可以：

```bash
mkdir -p ~/.claude/skills/douyin-digest
cp SKILL.md ~/.claude/skills/douyin-digest/
```

装好之后，你把抖音链接发给 agent，它会自己跑这条链路，再把「简报」那段填好。

---

## 五、原理说明

### 抖音为什么要特殊处理

`yt-dlp` 对抖音现在大概率报：

```
ERROR: [Douyin] 7694938814749396265: Fresh cookies (not necessarily logged in) are needed
```

意思是需要一个 `ttwid` cookie，哪怕没登录。

本项目的兜底路径**不需要登录态**：

1. `POST https://ttwid.bytedance.com/ttwid/union/register/` 拿 `ttwid` cookie
2. 带着它请求 `https://www.iesdouyin.com/share/video/<id>/`
3. 页面里的 `window._ROUTER_DATA` 就是完整的作品 JSON（含作者、时长、点赞、无水印播放直链）
4. 把 `playwm` 换成 `play` 得到无水印地址

见 `douyin_web.py`，纯标准库，不依赖第三方包。

### 转写为什么要切块

长视频一口气转写有两个问题：中断就全废；内存占用大。
`transcribe_chunked.py` 先用 ffmpeg 的 `silencedetect` 找静音点，按 5 分钟为目标切，
每一块的结果单独落盘 `parts/part_000.json`。重跑时已存在的分块直接跳过。

### OCR 的效果差异

- **Apple Vision**（macOS）：中文花字、艺术字、双层字幕都能认，接近可用
- **tesseract**（Linux/Windows）：中文花字基本认不出，只适合打印体

差异只影响笔记里「画面文字（OCR）」那一段，**逐字稿不受影响**。
对画面文字要求高的话，可以自己接 PaddleOCR 替换 `ocr.py`。

---

## 六、常见问题

**`Error opening data file .../chi_sim.traineddata`**

tesseract 装了但中文语言包没装好。macOS 用 Homebrew：

```bash
brew install tesseract-lang
```

Debian/Ubuntu：

```bash
sudo apt install tesseract-ocr-chi-sim
```

没装中文包也能跑：脚本会自动降级成纯英文 `-l eng`，画面文字只剩英文部分。

**`Fresh cookies (not necessarily logged in) are needed`**

这不是错误，是 yt-dlp 对抖音的正常反应。脚本会自己切到网页端兜底，看到这行说明兜底已生效。

**转写很慢**

`small` 模型在 M 系列 Mac 上是 6–10 倍速，Intel 上只有 4.6 倍速。改用 `DY_WHISPER_MODEL=base` 快一倍，准确率略降。

**`ocr_lines: 0`**

说明这台机器的 OCR 不可用（没装 tesseract、或 macOS 没编译 vision-ocr）。逐字稿不受影响。
检查方法：`python ocr.py 随便一张图.jpg`，退出码 3 就是没有 OCR。

---

## 七、已知限制

- **不是所有视频都能下**：图文作品没有音轨、部分视频即使兜底也拿不到，会打印 `ERROR:` 原因，别反复重试
- **直播回放不在范围内**，这是给短视频/图文用的
- **纯 CPU 转写**：M 系列 Mac 上 `small` 约 6–10 倍速；Intel i5 约 4.6 倍速。1 分钟的视频整体 1–3 分钟跑完
- **tesseract 的中文识别很差**：花字、艺术字基本认不出，只适合打印体。要高质量中文 OCR 得自己接 PaddleOCR 替换 `ocr.py`
- **抖音会变**：这套兜底依赖 `iesdouyin` 分享页的结构，抖音改了就得跟着改
- **仅供个人学习研究**：请尊重原作者版权，不要拿下载的内容做二次分发

---

## 八、文件说明

| 文件 | 作用 |
|---|---|
| `dy.py` | 主程序：下载 → 转写 → OCR → 写笔记 |
| `douyin_web.py` | 免登录下载兜底（yt-dlp 失败时用） |
| `transcribe_chunked.py` | 按静音点切块转写，支持中断续跑 |
| `ocr.py` | OCR 适配层：Vision / tesseract / 跳过 |
| `ocr.swift` | Apple Vision 的 Swift 实现（仅 macOS 编译） |
| `dy_fetch.py` | 可选路径：用 ego-browser 抓流（需该浏览器已登录抖音），日常用不到 |
| `setup.sh` | 跨平台安装脚本 |
| `dy-digest.cmd` | Windows 启动器 |
| `SKILL.md` | Claude Code skill 定义 |

---

## License

MIT
