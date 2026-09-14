# SPDX-License-Identifier: GPL-3.0-or-later
# 移植自 MiAir Next (https://github.com/deerwan/miair-next)，
# 派生出处与许可变更说明见仓库根目录 NOTICE。
"""播完自动断开：统一登记并关闭给音箱推流的长连接。

音箱播放音乐时是它主动来拉流的，xiaomusic 有两条推流路径、投送有两条：

    /proxy/{type}         本地/网络音乐（api/routers/file.py）
    /media/{token}        DLNA 投送的媒体代理（cast/dlna/device_server.py）
    /airplay/stream.wav   AirPlay 投送（cast/airplay/audio_stream.py）

这些都是长连接，音乐播完后不会自己断开，会一直占着 aiohttp 连接、
上游 CDN 连接和内存缓冲。这里提供一个全局登记表，让播放结束时能一次性
把正在推流的通道全部关掉。

关闭是"软关闭"：置中断标志 / 取消流式任务，让对应的响应正常收尾，
而不是粗暴地掐断 socket。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger("xiaomusic.stream_guard")


class StreamHandle:
    """一条正在给音箱推流的通道。

    用 `StreamGuard.open()` 创建，连接正常结束时必须 `release()` 注销；
    `with` 语句可以直接当上下文管理器用。
    """

    __slots__ = ("_guard", "_sid", "source", "_closer", "_closed", "created_at")

    def __init__(
        self, guard: StreamGuard, sid: int, source: str, closer: Callable[[], None]
    ):
        self._guard = guard
        self._sid = sid
        self.source = source
        self._closer = closer
        self._closed = False
        self.created_at = time.time()

    @property
    def sid(self) -> int:
        return self._sid

    @property
    def closed(self) -> bool:
        """conn 是否已被 disconnect_all() 关闭。"""
        return self._closed

    def close(self) -> bool:
        """关闭这条通道（幂等）。

        返回 True 仅表示本次真的关成功了；已关闭过、或 closer 抛异常时
        返回 False —— disconnect_all() 的计数据此统计，不能虚报。
        无论成功与否都会置位 _closed，避免失败后反复重试。
        """
        if self._closed:
            return False
        self._closed = True
        try:
            self._closer()
        except Exception as e:
            log.warning(f"关闭推流通道失败 {self.source}: {e}")
            return False
        return True

    def release(self):
        """从登记表注销（连接正常结束时调用）。"""
        self._guard._remove(self._sid)

    def __enter__(self) -> StreamHandle:
        return self

    def __exit__(self, *exc):
        self.release()
        return False


class StreamGuard:
    """推流通道登记表。"""

    def __init__(self):
        self._streams: dict[int, StreamHandle] = {}
        self._next_sid = 1
        # 关闭回调可能来自 AirPlay 的 RTSP/RTP 线程，用线程锁而非 asyncio.Lock
        self._lock = threading.Lock()

    def open(self, source: str, closer: Callable[[], None]) -> StreamHandle:
        """登记一条推流通道。closer 必须同步、幂等、不阻塞。"""
        with self._lock:
            sid = self._next_sid
            self._next_sid += 1
            handle = StreamHandle(self, sid, source, closer)
            self._streams[sid] = handle
        log.debug(f"推流通道登记: {source} (sid={sid})")
        return handle

    def _remove(self, sid: int):
        with self._lock:
            self._streams.pop(sid, None)

    def disconnect_all(self, reason: str = "") -> int:
        """关闭所有已登记的通道，返回实际关闭的数量。"""
        with self._lock:
            handles = list(self._streams.values())
            self._streams.clear()
        if not handles:
            return 0
        closed = 0
        for handle in handles:
            if handle.close():
                closed += 1
        suffix = f"（{reason}）" if reason else ""
        log.info(f"已断开 {closed}/{len(handles)} 条音箱推流连接{suffix}")
        return closed

    def active_count(self) -> int:
        with self._lock:
            return len(self._streams)

    def active_sources(self) -> list[str]:
        with self._lock:
            return [h.source for h in self._streams.values()]


# 全局单例：三条推流路径分布在不同的 web 应用（xiaomusic 主应用 / DLNA
# 独立 aiohttp 应用 / AirPlay 独立 aiohttp 应用）里，通过它汇合。
stream_guard = StreamGuard()

__all__ = ["StreamGuard", "StreamHandle", "stream_guard"]
