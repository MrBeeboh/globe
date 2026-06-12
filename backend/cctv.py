"""CCTV feed catalog — verifies streams are actually broadcasting (HLS), not just listed."""
import json
import logging
import os
import re
import time

import httpx

log = logging.getLogger("cctv")

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
TIMEOUT = httpx.Timeout(18.0)
TTL = 300  # re-check every 5 min — live status changes often

_cache: dict = {"ts": 0, "feeds": [], "signature": ""}

_PLAYER_RE = re.compile(r"ytInitialPlayerResponse\s*=\s*(\{.+?\});", re.DOTALL)
_VIDEO_ID_RE = re.compile(r"embed/([A-Za-z0-9_-]{11})")
_VID_PAGE_RE = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')


def _embed_url(video_id: str) -> str:
    return (
        f"https://www.youtube.com/embed/{video_id}"
        "?autoplay=1&mute=1&playsinline=1&rel=0&modestbranding=1"
    )


def _video_id(feed: dict) -> str:
    vid = (feed.get("video_id") or "").strip()
    if vid:
        return vid
    url = feed.get("url") or ""
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else ""


def _parse_player(html: str) -> dict | None:
    m = _PLAYER_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _is_broadcasting(player: dict) -> bool:
    if not player:
        return False
    status = (player.get("playabilityStatus") or {}).get("status")
    hls = (player.get("streamingData") or {}).get("hlsManifestUrl")
    return status == "OK" and bool(hls)


def _check_video(client: httpx.Client, video_id: str) -> bool:
    if not video_id:
        return False
    try:
        r = client.get(f"https://www.youtube.com/watch?v={video_id}")
        return _is_broadcasting(_parse_player(r.text))
    except Exception as e:
        log.debug("check %s: %s", video_id, e)
        return False


def _resolve_channel_live(client: httpx.Client, channel_id: str) -> str | None:
    if not channel_id:
        return None
    try:
        r = client.get(f"https://www.youtube.com/channel/{channel_id}/live")
        for vid in dict.fromkeys(_VID_PAGE_RE.findall(r.text)):
            if _check_video(client, vid):
                return vid
    except Exception as e:
        log.debug("channel %s: %s", channel_id, e)
    return None


def get_feeds(root: str) -> dict:
    path = os.path.join(root, "data", "cctv-feeds.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    feeds = raw.get("feeds") or []
    signature = json.dumps(feeds, sort_keys=True)
    now = time.time()

    if _cache["signature"] == signature and _cache["ts"] and (now - _cache["ts"]) < TTL:
        return {
            "feeds": _cache["feeds"],
            "checked_sec_ago": round(now - _cache["ts"]),
            "online": sum(1 for f in _cache["feeds"] if f.get("online")),
            "total": len(_cache["feeds"]),
        }

    checked: list[dict] = []
    with httpx.Client(timeout=TIMEOUT, headers=UA, follow_redirects=True) as client:
        for feed in feeds:
            feed_type = (feed.get("type") or "youtube").lower()
            if feed_type in ("x", "x_broadcast"):
                checked.append({
                    **feed,
                    "online": None,
                    "url": feed.get("embed_url") or feed.get("url"),
                })
                continue

            channel_id = (feed.get("channel_id") or "").strip()
            vid = _video_id(feed)
            if channel_id:
                live_vid = _resolve_channel_live(client, channel_id)
                if live_vid:
                    vid = live_vid
                elif not vid:
                    vid = ""

            online = _check_video(client, vid) if vid else False
            entry = {
                **feed,
                "video_id": vid or None,
                "url": _embed_url(vid) if vid else None,
                "online": online,
            }
            checked.append(entry)

    _cache.update({"ts": now, "feeds": checked, "signature": signature})
    online_n = sum(1 for f in checked if f.get("online"))
    log.info("cctv live: %d/%d feeds broadcasting", online_n, len(checked))
    return {
        "feeds": checked,
        "checked_sec_ago": 0,
        "online": online_n,
        "total": len(checked),
    }