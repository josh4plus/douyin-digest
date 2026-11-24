"""抖音网页端兜底下载：yt-dlp 报 "Fresh cookies needed" 时走这条路。

不需要登录态，只要先申请一个 ttwid cookie 再打开 iesdouyin 分享页，
页面里的 `window._ROUTER_DATA` 就带完整的 item 信息（含无水印播放直链）。

只依赖标准库，macOS / Linux / Windows 通用。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
TTWID_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
SHARE_URL = "https://www.iesdouyin.com/share/video/%s/"

_ROUTER_RE = re.compile(r"window\._ROUTER_DATA\s*=\s*(\{.*?\});?\s*</script>", re.S)
_ITEM_RE = re.compile(r"(?:video|note)/(\d+)")


class DouyinError(RuntimeError):
    pass


def _open(req: urllib.request.Request, timeout: int = 30):
    return urllib.request.urlopen(req, timeout=timeout)


def resolve_url(url: str) -> str:
    """把 v.douyin.com 短链展开成长链（不跟随正文，只看 Location）。"""
    req = urllib.request.Request(url, headers={"User-Agent": MOBILE_UA})
    try:
        with _open(req) as r:
            return r.geturl() or url
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        return loc or url


def item_id(url: str) -> str:
    m = _ITEM_RE.search(resolve_url(url))
    if not m:
        raise DouyinError("链接里找不到作品 id：" + url)
    return m.group(1)


def fetch_ttwid() -> str:
    body = json.dumps({
        "region": "cn", "aid": 1768, "needFid": False,
        "service": "www.ixigua.com",
        "migrate_info": {"ticket": "", "source": "node"},
        "cbUrlProtocol": "https", "union": True,
    }).encode()
    req = urllib.request.Request(
        TTWID_URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": MOBILE_UA})
    with _open(req) as r:
        for cookie in r.headers.get_all("Set-Cookie") or []:
            if cookie.startswith("ttwid="):
                return cookie.split(";")[0]
    raise DouyinError("拿不到 ttwid cookie")


def fetch_item(item: str) -> Dict[str, Any]:
    """返回抖音 item 原始 JSON。"""
    req = urllib.request.Request(
        SHARE_URL % item,
        headers={"User-Agent": MOBILE_UA, "Cookie": fetch_ttwid()})
    with _open(req) as r:
        html = r.read().decode("utf-8", "ignore")
    m = _ROUTER_RE.search(html)
    if not m:
        raise DouyinError("分享页里没有 _ROUTER_DATA，可能被风控")
    data = json.loads(m.group(1))
    page = (data.get("loaderData") or {}).get("video_(id)/page") or {}
    items = ((page.get("videoInfoRes") or {}).get("item_list")) or []
    if not items:
        reason = (page.get("videoInfoRes") or {}).get("filter_list")
        raise DouyinError("分享页没返回作品信息" + ("：" + str(reason)[:120] if reason else ""))
    return items[0]


def _best_url(item: Dict[str, Any]) -> str:
    """优先无水印的 play 直链，退回 playwm。"""
    video = item.get("video") or {}
    for br in video.get("bit_rate") or []:
        urls = (br.get("play_addr") or {}).get("url_list") or []
        if urls:
            return urls[0].replace("/playwm/", "/play/")
    urls = (video.get("play_addr") or {}).get("url_list") or []
    if not urls:
        raise DouyinError("作品没有播放地址（可能是图文）")
    return urls[0].replace("/playwm/", "/play/")


def download(url: str, dest, timeout: int = 120) -> Dict[str, Any]:
    """下载到 dest（Path），返回与 yt-dlp info 字段兼容的字典。"""
    item = fetch_item(item_id(url))
    src = _best_url(item)
    req = urllib.request.Request(src, headers={"User-Agent": MOBILE_UA})
    with _open(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    if dest.stat().st_size < 10_000:
        raise DouyinError("下载到的文件过小，可能被风控")
    stats = item.get("statistics") or {}
    return {
        "id": str(item.get("aweme_id") or ""),
        "title": (item.get("desc") or "抖音视频").strip(),
        "uploader": (item.get("author") or {}).get("nickname") or "",
        "duration": ((item.get("video") or {}).get("duration") or 0) / 1000.0,
        "like_count": stats.get("digg_count"),
        "comment_count": stats.get("comment_count"),
        "repost_count": stats.get("share_count"),
        "collect_count": stats.get("collect_count"),
        "webpage_url": url,
    }
