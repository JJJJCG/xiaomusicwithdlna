"""小米音箱设备级 Mina 操作的共用实现。

本项目由三家代码拼成：XiaoMusic（`device_player.py`）、MiAir Next
（`cast/`）、xiaoai-ha-bridge（`ha/`）。其中前两家各自实现过同一批
「Mina 级」操作 —— 读播放状态、搜曲库换 audioID —— 但严格程度与失败
语义并不一致，导致同一台音箱在"本地播放"和"投送播放"下拿到不同的
封面/歌词 ID，状态读取失败时也会一方吞掉、一方抛出。

这里把这类操作收敛成一份，调用方只保留各自的错误处理策略：

    device_player.XiaoMusicDevice   失败时吞掉并回退 0/默认值
    cast.SpeakerController          失败时抛出，让 DLNA 轮询跳过本轮
"""

from __future__ import annotations

import json
import re
import time

# 小米曲库兜底 audioID（与 Config.use_music_audio_id 的默认值保持一致）
DEFAULT_AUDIO_ID = "1582971365183456177"

# 曲库搜索取多少条候选
SEARCH_COUNT = 6

# 歌手字段里可能混进歌名的分隔写法（发送端格式各异）
_ARTIST_TITLE_SEPS = ("--", " — ", " · ", "—", "·")
# 多人合作时分隔歌手的符号
_ARTIST_LIST_SEPS = r"[;；,，&、/·・—]"


async def fetch_player_info(mina_service, device_id: str) -> dict:
    """读 `player_get_status` 并解析出 info 字典。

    任何异常（含 code != 0、缺 info 字段、info 不是合法 JSON）都直接抛出，
    由调用方决定是吞掉还是上抛 —— 这一点很关键：DLNA 侧把失败伪装成
    "已停止"会触发错误的暂停/续播逻辑，所以它必须能感知失败。
    """
    playing_info = await mina_service.player_get_status(device_id)
    if not isinstance(playing_info, dict) or playing_info.get("code") != 0:
        raise RuntimeError(f"Mina API Error: {playing_info}")
    info_str = (playing_info.get("data") or {}).get("info")
    if not info_str:
        raise RuntimeError(f"Mina API response missing 'info': {playing_info}")
    info = json.loads(info_str)
    if not isinstance(info, dict):
        raise RuntimeError(f"Mina API 'info' 不是对象: {info_str!r}")
    return info


async def search_audio_id(
    mina_service, title: str, artist: str = "", *, fuzzy_fallback: bool = True
) -> str:
    """搜小米官方曲库，返回匹配到的 audioID；未命中或出错返回 ""。

    fuzzy_fallback：
      True  —— 精确未命中时回退取搜索结果第一条（一次性场景，接口按相关度排序，
               首条通常就是目标歌）；
      False —— 严格模式，供持续监听场景（AirPlay 歌词滚动）使用：滚动歌词行
               若被模糊命中会误判为切歌，导致反复重发播放指令、音箱频繁重连。
    """
    title = (title or "").strip()
    if not title:
        return ""
    artist = (artist or "").strip()
    # 发送端常把歌名拼进歌手字段（"周杰伦--告白气球"、"搁浅 — 周杰伦"），
    # 拼查询词时剔除与歌名重复的部分，避免杂质干扰搜索接口；
    # 歌手校验仍用原始 artist（双向包含）。
    query_artist = _strip_title_from_artist(title, artist)
    query = f"{title}-{query_artist}" if query_artist else title

    try:
        result = await mina_service.mina_request(
            "/music/search",
            {
                "query": query,
                "queryType": 1,
                "offset": 0,
                "count": SEARCH_COUNT,
                "timestamp": int(time.time() * 1000),
            },
        )
    except Exception:
        return ""

    song_list = ((result or {}).get("data") or {}).get("songList") or []
    if not song_list:
        return ""

    first_artist = _first_artist(artist)
    artist_lower = artist.lower()
    for song in song_list:
        name = (song.get("name") or "").lower()
        if name != title.lower():
            continue
        song_artist = (song.get("artist") or {}).get("name") or ""
        # 无歌手信息时仅凭歌名命中；有歌手时双向包含匹配 —— 曲库歌手名通常
        # 被包含在发送端字符串里，反之亦然（Apple Music "陈奕迅 · 准备中" 等）
        if first_artist:
            song_artist_lower = song_artist.lower()
            if (
                first_artist.lower() not in song_artist_lower
                and song_artist_lower not in artist_lower
            ):
                continue
        audio_id = str(song.get("audioID") or "")
        if audio_id:
            return audio_id

    if fuzzy_fallback:
        audio_id = str(song_list[0].get("audioID") or "")
        if audio_id:
            return audio_id
    return ""


def split_song_artist(name: str) -> tuple[str, str]:
    """把 "歌名-歌手" 拆成 (歌名, 歌手)；没有分隔符时歌手为空串。"""
    text = (name or "").strip()
    if "-" in text:
        song, _, artist = text.partition("-")
        return song.strip(), artist.strip()
    return text, ""


def _strip_title_from_artist(title: str, artist: str) -> str:
    """歌手字段里若混进了歌名（"周杰伦--告白气球"），返回真正的歌手名。"""
    for sep in _ARTIST_TITLE_SEPS:
        if sep not in artist:
            continue
        parts = [part.strip() for part in artist.split(sep)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            continue
        if parts[0].lower() == title.lower():
            return parts[1]
        if parts[1].lower() == title.lower():
            return parts[0]
        break
    return artist


def _first_artist(artist: str) -> str:
    """多人合作时只取第一个歌手用于匹配。"""
    if not artist:
        return ""
    return re.split(_ARTIST_LIST_SEPS, artist)[0].strip()


__all__ = [
    "DEFAULT_AUDIO_ID",
    "SEARCH_COUNT",
    "fetch_player_info",
    "search_audio_id",
    "split_song_artist",
]
