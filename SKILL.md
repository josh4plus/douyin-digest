---
name: douyin-digest
description: |
  拆解抖音视频链接：下载视频、转写语音、OCR 画面文字，写成一篇 markdown 笔记，并给出一段简报。
  当用户发来抖音分享链接（v.douyin.com / www.douyin.com/video 开头，通常还带一堆分享文案）时使用。
  触发词：抖音链接、这个视频讲了什么、拆解、调研这条视频、转发视频、转成笔记。
---

# 抖音视频拆解

用户发来一条抖音链接时，**不要自己手搓下载和转写**，直接跑现成脚本。

## 前置检查（第一次用这台机器时做一次）

```bash
dy-digest --help >/dev/null 2>&1 || <仓库目录>/setup.sh
```

`dy-digest` 不在 PATH 里，就直接用仓库里的 `dy.py`：

```bash
python3 <仓库目录>/dy.py "<原文>"
```

## 一条命令

```bash
dy-digest "<用户发来的整段原文>"
```

脚本自己从文本里挑抖音链接，依次做：

1. **下载**：先试 `yt-dlp`；报 *Fresh cookies needed* 时自动走网页端兜底
   （申请 ttwid → 读 iesdouyin 分享页的 `_ROUTER_DATA` → 取无水印直链），不需要登录态。
2. `ffmpeg` 抽音轨 → `faster-whisper`（small / int8 CPU）写带时间轴的逐字稿，按静音切块、可中断续跑。
3. 每 2 秒抽一帧 → OCR（macOS 用 Apple Vision，其他平台用 tesseract），去重后带时间戳。没装 OCR 就跳过这一步，只出逐字稿。
4. 写一篇 markdown 到 `DY_VAULT`（默认 `~/Documents/视频拆解`，Windows 是 `~/Videos/视频拆解`）。

成功时**最后一行**是一段 JSON：

```json
{"ok":true,"note":"...路径...","title":"...","duration":"0:47","author":"...",
 "transcript_segments":12,"transcript_chars":430,"ocr_lines":9,"cache":"..."}
```

跑完必须确认 `ok: true` 且笔记文件真的存在，再往下走。失败就看 stderr 里 `ERROR:` 那行，把原因转成人话说给用户。

## 跑完之后（这一步不能省）

1. 读那篇笔记，按逐字稿 + 画面文字写 200–400 字简报，**覆盖掉笔记里的「> 待填」那一行**（放在 `## 简报` 下面）。
2. 回复里讲清：这段视频讲了什么、结构怎么走、有哪几个可以直接用的点、结尾一句"全文存在 <笔记路径>"。
3. 手机上看的话少用 markdown 列表和符号，像人说话，控制在一屏左右。

## 平台差异

| | macOS | Linux | Windows |
|---|---|---|---|
| 语音转写 | faster-whisper（CPU int8） | 同左 | 同左 |
| 画面 OCR | Apple Vision（需 `swiftc` 编译） | tesseract + `chi_sim` | tesseract + `chi_sim` |
| 命令入口 | `~/.local/bin/dy-digest` | 同左 | `dy-digest.cmd`（Git Bash 跑过 setup 后） |

Windows 上必须在 Git Bash 或 WSL 里跑一次 `setup.sh`（它建 venv、装依赖），之后用 `dy-digest.cmd` 调。

## 时长与超时

CPU 转写大约 1–3 倍速：1 分钟的视频整体 1–3 分钟跑得完，5 分钟的视频可能要 10 分钟以上。
上层机器人如果单轮有上限（比如 1200 秒），超长视频（>8 分钟）先跟用户说一声再跑。

## 已知限制（别硬碰）

- 部分视频即使走网页端兜底也拿不到（图文作品、被限流），`ERROR:` 会写原因，告诉用户抓不到，不要反复重试。
- 图文作品（非视频）没有音轨，只能靠 OCR。
- 直播回放不是这条链路，别混进来。
- whisper 模型首次运行会从 HuggingFace 下载（国内走 `HF_ENDPOINT=https://hf-mirror.com` 镜像），第一次慢几分钟。
