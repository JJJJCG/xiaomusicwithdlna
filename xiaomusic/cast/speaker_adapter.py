# SPDX-License-Identifier: GPL-3.0-or-later
# 移植自 MiAir Next (https://github.com/deerwan/miair-next)，
# 派生出处与许可变更说明见仓库根目录 NOTICE。
"""音箱适配层：把 xiaomusic 的 XiaoMusicDevice 适配成移植代码期望的接口。

移植自 miair-next 的 app/engine/speaker.py（SpeakerController）与
app/engine/config.py（Speaker / Config）。

移植的 DLNA 渲染器与 AirPlay 接收器只依赖这里定义的接口：
    controller.did / device_id / speaker / play_url / pause / stop /
    set_volume / get_volume / get_status / search_audio_id
其中 controller.speaker 是一个轻量配置对象，暴露 did / hardware / udn /
dlna_name / get_dlna_name() / needs_audio_conversion()。

这样协议层代码可以保持与上游一致，改动集中在适配层，
底层仍走 xiaomusic 既有的 miservice 登录与设备控制链路。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import time
import uuid

log = logging.getLogger("xiaomusic.cast")


def detect_local_ip() -> str:
    """自动检测本机局域网 IP。

    优先取默认路由出口 IP (UDP connect 探测)，但仅当其是私网段且不是
    常见虚拟网卡网段 (docker0/tailscale) 时才采用；否则遍历所有网卡候选，
    取第一个符合私网段的 IP。
    解决多网卡 / Docker host 网络 + VPN(旁路由) 场景下自动探测到错误 IP
    (如公网段 172.5.x.x 或 172.17.x docker0) 导致 AirPlay/DLNA 不可连接的问题。
    """

    def _is_lan_ip(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.is_loopback or addr.is_link_local:
            return False
        if not addr.is_private:
            return False
        # 排除常见虚拟网卡网段: docker0 (172.17.0.0/16) / tailscale (100.64.0.0/10)
        for net in ("172.17.0.0/16", "100.64.0.0/10"):
            if addr in ipaddress.ip_network(net):
                return False
        return True

    # 1) 默认路由出口 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        default_ip = s.getsockname()[0]
        s.close()
        if _is_lan_ip(default_ip):
            return default_ip
    except Exception:
        pass

    # 2) 遍历网卡候选: 通过 UDP connect 到各私网段广播地址获取各网卡源 IP
    #    (UDP connect 不实际发包, 仅做路由选择, 各系统均安全)
    candidates: set[str] = set()
    for target in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 80))
            candidates.add(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    for ip in candidates:
        if _is_lan_ip(ip):
            return ip
    return "127.0.0.1"


class CastConfig:
    """把 xiaomusic 的 Config 适配成移植代码期望的配置对象。

    移植的 renderer / device_server / speaker_airplay 读取的是 MiAir 风格
    的属性名 (hostname / dlna_port / default_volume / ...)，这里做一次映射，
    避免为了改名而改动协议层代码。所有属性在构造时快照，
    配置变更后由 CastManager 重建整个服务生效。
    """

    def __init__(self, config):
        self.hostname = (getattr(config, "cast_hostname", "") or "").strip() or detect_local_ip()
        self.dlna_port = int(getattr(config, "dlna_port", 8200) or 8200)
        self.default_volume = int(getattr(config, "cast_default_volume", 38) or 0)
        self.follow_device_volume = bool(
            getattr(config, "cast_follow_device_volume", True)
        )
        self.touchscreen_lyrics = bool(
            getattr(config, "cast_touchscreen_lyrics", False)
        )
        self.default_cover_url = (getattr(config, "cast_default_cover_url", "") or "").strip()
        self.default_audio_id = (getattr(config, "cast_default_audio_id", "") or "").strip()
        self.auto_resume_on_interrupt = bool(
            getattr(config, "cast_auto_resume_on_interrupt", False)
        )
        self.resume_delay_seconds = max(
            1, min(15, int(getattr(config, "cast_resume_delay_seconds", 5) or 5))
        )
        self.auto_play_on_set_uri = bool(
            getattr(config, "cast_auto_play_on_set_uri", False)
        )
        # 复用 xiaomusic 自己的 ffmpeg（默认 ./ffmpeg/bin），
        # 非 Docker 安装下 ffmpeg 未必在 PATH 上
        self.ffmpeg_location = (getattr(config, "ffmpeg_location", "") or "").strip()

    def save(self):
        """兼容上游代码里的 config.save() 调用；配置持久化由 xiaomusic 负责。"""


class SpeakerInfo:
    """SpeakerController.speaker —— 移植代码读取的音箱配置对象。"""

    # 不支持无损格式的音箱型号列表
    _NON_LOSSLESS_HARDWARE = {"L05B", "L05C", "LX06", "L16A"}

    def __init__(self, device, config=None):
        self._device = device
        self._config = config
        self._dlna_name_override: str | None = None

        did = device.did or ""
        self.did = did
        self.device_id = device.device_id or ""
        self.hardware = (device.hardware or "").upper()
        # 每个音箱一个稳定 UDN，供 SSDP / UPnP 设备描述使用
        self.udn = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"xiaomusic-{did}"))

    @property
    def name(self) -> str:
        return self._device.name or ""

    @property
    def dlna_name(self) -> str:
        return self._dlna_name_override or ""

    @dlna_name.setter
    def dlna_name(self, value: str):
        self._dlna_name_override = value

    def get_dlna_name(self) -> str:
        """投送时可读到的设备名，用户改设备名后随之变化。"""
        return self._dlna_name_override or self._device.name or f"XiaoAI-{self.did}"

    def needs_audio_conversion(self, content_type: str = "") -> bool:
        """部分音箱不支持无损格式，需要转换为 WAV (PCM) 播放。"""
        if self.hardware not in self._NON_LOSSLESS_HARDWARE:
            return False
        if content_type:
            ct = content_type.lower()
            if "mp3" in ct or "mpeg" in ct or "wav" in ct or "x-wav" in ct:
                return False
        return True


class SpeakerController:
    """单个小爱音箱的控制接口（移植自 MiAir 的 SpeakerController）。

    底层复用 xiaomusic 的 XiaoMusicDevice / AuthManager.mina_service，
    因此登录态、账号恢复等行为与主程序保持一致。
    """

    def __init__(self, device_player, config, log_=None):
        self.device_player = device_player
        self.config = config
        self.log = log_ or log
        self.speaker = SpeakerInfo(device_player.device, config)
        self._last_volume = 50  # 用于 unmute 恢复

    @property
    def did(self) -> str:
        return self.speaker.did

    @property
    def device_id(self) -> str:
        return self.device_player.device_id

    # ---- 内部工具 ----

    @property
    def _auth(self):
        return self.device_player.auth_manager

    async def _ensure_login(self):
        """确保 mina_service 可用；为空时强制走一次登录恢复。"""
        auth = self._auth
        if auth.mina_service is None:
            self.log.info("[CAST] mina_service 为空，尝试强制恢复登录")
            await auth.init_all_data(force_login=True)
        if auth.mina_service is None:
            raise RuntimeError("mina_service 不可用（未登录或登录失败）")

    def _default_audio_id(self) -> str:
        """小米云路线默认封面 audioID。

        优先使用 cast_default_audio_id (小米曲库某歌曲的 audioID)，
        未配置时回退到 xiaomusic 的 use_music_audio_id。
        """
        cfg = self.config
        if getattr(cfg, "default_audio_id", ""):
            return cfg.default_audio_id
        host_cfg = getattr(self.device_player, "config", None)
        fallback = getattr(host_cfg, "use_music_audio_id", "") if host_cfg else ""
        return str(fallback or "1582971365183456177")

    def _should_use_music_api(self) -> bool:
        """是否走 play_by_music_url（可携带 audioID → 触屏显示封面/歌词）。

        与 xiaomusic device_player.play_one_url 的分支保持一致。
        """
        host_cfg = getattr(self.device_player, "config", None)
        if host_cfg is not None and getattr(host_cfg, "continue_play", False):
            return True
        if host_cfg is not None and getattr(host_cfg, "use_music_api", False):
            return True
        from xiaomusic.const import NEED_USE_PLAY_MUSIC_API

        return self.speaker.hardware in NEED_USE_PLAY_MUSIC_API

    # ---- 播放控制 ----

    async def play_url(self, url: str, audio_id: str | None = None) -> bool:
        """让音箱播放指定 URL。

        audio_id: 小米云路线使用的 audioID（触屏歌词匹配命中的真实 ID），
        为空时回退默认 audioID。
        """
        effective_audio_id = audio_id or self._default_audio_id()
        try:
            await self._ensure_login()
            mina = self._auth.mina_service
            if self._should_use_music_api():
                ret = await mina.play_by_music_url(
                    self.device_id, url, audio_id=effective_audio_id
                )
                self.log.info(
                    f"[CAST] play_by_music_url device_id={self.device_id} ret={ret}"
                )
            else:
                ret = await mina.play_by_url(self.device_id, url)
                self.log.info(f"[CAST] play_by_url device_id={self.device_id} ret={ret}")
            return ret is not None
        except Exception as e:
            self.log.warning(f"[CAST] play_url 失败: {e}")
            return False

    async def pause(self) -> bool:
        """暂停播放。"""
        try:
            await self._ensure_login()
            mina = self._auth.mina_service
            if self._should_use_music_api():
                # 某些使用 play_by_music_url 的设备，调用 pause 后 API 状态不会
                # 正确更新为 paused (status=2)，需改用 stop 来实现暂停语义
                await mina.player_stop(self.device_id)
            else:
                await mina.player_pause(self.device_id)
            return True
        except Exception as e:
            self.log.warning(f"[CAST] pause 失败: {e}")
            return False

    async def stop(self) -> bool:
        """停止播放。

        走 XiaoMusicDevice.force_stop_xiaoai（player_pause + player_stop），
        而不是 XiaoMusicDevice.stop —— 后者会播 TTS 提示音并 sleep 3 秒，
        不适合响应 DLNA Stop 指令。
        """
        try:
            await self._ensure_login()
            await self.device_player.force_stop_xiaoai(self.device_id)
            return True
        except Exception as e:
            self.log.warning(f"[CAST] stop 失败: {e}")
            return False

    async def set_volume(self, volume: int) -> bool:
        """设置音量 (0-100)。"""
        volume = max(0, min(100, int(volume)))
        try:
            await self._ensure_login()
            await self._auth.mina_service.player_set_volume(self.device_id, volume)
            if volume > 0:
                self._last_volume = volume
            return True
        except Exception as e:
            self.log.warning(f"[CAST] set_volume 失败: {e}")
            return False

    async def get_volume(self) -> int:
        """获取当前音量。"""
        try:
            status = await self.get_status()
            volume = int(status.get("volume", 0))
            if volume > 0:
                self._last_volume = volume
            return volume
        except Exception as e:
            self.log.warning(f"[CAST] get_volume 失败: {e}")
            return self._last_volume

    async def get_status(self) -> dict:
        """获取播放状态。

        Returns:
            dict: {status: int, volume: int}
            status: 0=stopped, 1=playing, 2=paused

        失败时抛异常而非返回 status=0：DLNA 侧轮询把异常当作「本轮跳过」，
        若伪装成 0 会被判定为「已停止」，触发错误的暂停/续播逻辑。
        """
        await self._ensure_login()
        playing_info = await self._auth.mina_service.player_get_status(self.device_id)
        if not isinstance(playing_info, dict) or playing_info.get("code") != 0:
            raise RuntimeError(f"Mina API Error: {playing_info}")
        data = playing_info.get("data", {})
        info_str = data.get("info")
        if not info_str:
            raise RuntimeError(f"Mina API response missing 'info': {playing_info}")
        info = json.loads(info_str)
        return {
            "status": info.get("status", 0),
            "volume": int(info.get("volume", 0)),
        }

    # ---- 触屏歌词匹配 ----

    async def search_audio_id(
        self, title: str, artist: str = "", fuzzy_fallback: bool = True
    ) -> str:
        """搜小米官方曲库，返回匹配到的 audioID（供触屏音箱拉取歌词/封面）；未命中返回 ""。

        fuzzy_fallback 参数：优先按「歌名完全相等 + 歌手包含匹配」精确命中；
        精确未命中时回退取搜索结果第一条。
        fuzzy_fallback=False 供持续搜索场景使用（AirPlay 歌词监听器）：
        滚动歌词行若模糊命中会被误判为切歌，导致反复重发播放指令。
        """
        title = (title or "").strip()
        if not title:
            return ""
        artist = (artist or "").strip()
        # 发送端常把歌名拼进歌手字段（"周杰伦--告白气球"、"搁浅 — 周杰伦"、
        # "挚友 · Eric周兴哲"），拼查询词时剔除与歌名重复的部分，
        # 避免杂质干扰搜索接口；歌手验证仍用原始 artist（双向包含）
        query_artist = artist
        for sep in ("--", " — ", " · ", "—", "·"):
            if sep not in artist:
                continue
            parts = [p.strip() for p in artist.split(sep)]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                continue
            if parts[0].lower() == title.lower():
                query_artist = parts[1]
            elif parts[1].lower() == title.lower():
                query_artist = parts[0]
            break
        query = f"{title}-{query_artist}" if query_artist else title
        try:
            await self._ensure_login()
            result = await self._auth.mina_service.mina_request(
                "/music/search",
                {
                    "query": query,
                    "queryType": 1,
                    "offset": 0,
                    "count": 6,
                    "timestamp": int(time.time() * 1000),
                },
            )
        except Exception as e:
            self.log.warning(f"[CAST] 曲库搜索失败 ({query}): {e}")
            return ""

        song_list = (result or {}).get("data", {}).get("songList") or []
        if not song_list:
            self.log.info(f"[CAST] 曲库搜索未命中 ({query})，回退默认 audioID")
            return ""

        # 优先「歌名完全相等 + 歌手包含」精确命中；精确未命中时回退策略：
        # - fuzzy_fallback=True（默认，每首歌只搜一次的一次性场景）：
        #   取搜索结果第一条，接口按相关度排序，首条通常就是目标歌；
        # - fuzzy_fallback=False（AirPlay 歌词监听器等持续搜索场景）：
        #   滚动歌词行若模糊"命中"会被误判为切歌，导致反复重发播放指令、
        #   音箱频繁重连音频流（卡顿），必须严格拒绝。
        # 歌手校验双向包含：发送端格式各异（Apple Music "陈奕迅 · 准备中"、
        # QQ音乐 "周杰伦--青花瓷"、网易云 "梁博/日落大道"），
        # 曲库歌手名通常包含在发送端字符串里，反之亦然。
        first_artist = re.split(r"[;；,，&、/·・—]", artist)[0].strip() if artist else ""
        artist_l = artist.lower()
        for song in song_list:
            name = song.get("name") or ""
            song_artist = (song.get("artist") or {}).get("name") or ""
            if name.lower() != title.lower():
                continue
            if first_artist:  # 无歌手信息时仅凭歌名命中
                if first_artist.lower() not in song_artist.lower() and not (
                    song_artist and song_artist.lower() in artist_l
                ):
                    continue
            audio_id = str(song.get("audioID") or "")
            if audio_id:
                self.log.info(f"[CAST] 曲库搜索精确命中 ({query}) audioID={audio_id}")
                return audio_id
        if fuzzy_fallback:
            audio_id = str(song_list[0].get("audioID") or "")
            if audio_id:
                first_name = song_list[0].get("name") or ""
                self.log.info(
                    f"[CAST] 曲库搜索无精确匹配，回退首条结果 ({query}) "
                    f"{first_name} audioID={audio_id}"
                )
                return audio_id
        self.log.info(f"[CAST] 曲库搜索无匹配 ({query})，回退默认 audioID")
        return ""


def build_controllers(device_manager, config, log_=None) -> dict[str, SpeakerController]:
    """为当前已配置的音箱构建控制器（did -> SpeakerController）。"""
    controllers: dict[str, SpeakerController] = {}
    for did, device_player in device_manager.devices.items():
        device = device_player.device
        if not device.device_id:
            log.info(f"[CAST] 音箱 did={did} 未找到 device_id，跳过")
            continue
        controllers[did] = SpeakerController(device_player, config, log_)
        log.info(
            f"[CAST] 已初始化音箱控制器: {controllers[did].speaker.get_dlna_name()} "
            f"(did={did})"
        )
    return controllers


__all__ = [
    "CastConfig",
    "SpeakerInfo",
    "SpeakerController",
    "build_controllers",
    "detect_local_ip",
]
