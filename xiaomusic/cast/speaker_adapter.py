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

import logging
import uuid

from xiaomusic.device_player import (
    PLAY_API_CONTINUE_PLAY,
    PLAY_API_MUSIC,
    PLAY_API_URL,
    resolve_play_api,
)
from xiaomusic.utils.device_utils import DEFAULT_AUDIO_ID, fetch_player_info
from xiaomusic.utils.device_utils import search_audio_id as _search_audio_id
from xiaomusic.utils.network_utils import detect_local_ip

log = logging.getLogger("xiaomusic.cast")


class CastConfig:
    """把 xiaomusic 的 Config 适配成移植代码期望的配置对象。

    移植的 renderer / device_server / speaker_airplay 读取的是 MiAir 风格
    的属性名 (hostname / dlna_port / default_volume / ...)，这里做一次映射，
    避免为了改名而改动协议层代码。所有属性在构造时快照，
    配置变更后由 CastManager 重建整个服务生效。
    """

    def __init__(self, config):
        self.hostname = (
            getattr(config, "cast_hostname", "") or ""
        ).strip() or detect_local_ip()
        self.dlna_port = int(getattr(config, "dlna_port", 8200) or 8200)
        self.default_volume = int(getattr(config, "cast_default_volume", 38) or 0)
        self.follow_device_volume = bool(
            getattr(config, "cast_follow_device_volume", True)
        )
        self.touchscreen_lyrics = bool(
            getattr(config, "cast_touchscreen_lyrics", False)
        )
        self.default_cover_url = (
            getattr(config, "cast_default_cover_url", "") or ""
        ).strip()
        self.default_audio_id = (
            getattr(config, "cast_default_audio_id", "") or ""
        ).strip()
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
        return str(fallback or DEFAULT_AUDIO_ID)

    def _play_api(self) -> str:
        """本音箱该走哪个播放 API（continue_play / music_api / url）。

        直接复用 device_player.resolve_play_api：本地播放与投送共用同一套判断，
        不再各自维护一份 —— 历史上投送侧照抄了分支条件却漏了 continue_play
        的 _type=1，导致同一台音箱"本地播放"和"投送播放"实际调用不同接口。
        """
        return resolve_play_api(
            getattr(self.device_player, "config", None), self.speaker.hardware
        )

    # ---- 播放控制 ----

    async def play_url(self, url: str, audio_id: str | None = None) -> bool:
        """让音箱播放指定 URL。

        audio_id: 小米云路线使用的 audioID（触屏歌词匹配命中的真实 ID），
        为空时回退默认 audioID。
        """
        effective_audio_id = audio_id or self._default_audio_id()
        try:
            # 投送开始即抢占音箱：停掉本地播放残留的兜底轮询，
            # 否则它会误判"音箱已停止"并 disconnect 掉投送刚建立的推流
            self.device_player.cancel_stream_watch()
            await self._ensure_login()
            mina = self._auth.mina_service
            play_api = self._play_api()
            if play_api == PLAY_API_CONTINUE_PLAY:
                # 与本地播放一致：continue_play 模式必须带 _type=1
                ret = await mina.play_by_music_url(
                    self.device_id, url, _type=1, audio_id=effective_audio_id
                )
                self.log.info(
                    f"[CAST] play_by_music_url(_type=1) device_id={self.device_id} "
                    f"ret={ret} url={url}"
                )
            elif play_api == PLAY_API_MUSIC:
                ret = await mina.play_by_music_url(
                    self.device_id, url, audio_id=effective_audio_id
                )
                self.log.info(
                    f"[CAST] play_by_music_url device_id={self.device_id} "
                    f"ret={ret} url={url}"
                )
            else:
                ret = await mina.play_by_url(self.device_id, url)
                self.log.info(
                    f"[CAST] play_by_url device_id={self.device_id} ret={ret} url={url}"
                )
            return ret is not None
        except Exception as e:
            self.log.warning(f"[CAST] play_url 失败: {e}")
            return False

    async def pause(self) -> bool:
        """暂停播放。"""
        try:
            await self._ensure_login()
            mina = self._auth.mina_service
            if self._play_api() != PLAY_API_URL:
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
        解析逻辑与 device_player.get_player_status 共用
        utils.device_utils.fetch_player_info，两边只保留各自的失败策略。
        """
        await self._ensure_login()
        info = await fetch_player_info(self._auth.mina_service, self.device_id)
        return {
            "status": info.get("status", 0),
            "volume": int(info.get("volume", 0)),
        }

    # ---- 触屏歌词匹配 ----

    async def search_audio_id(
        self, title: str, artist: str = "", fuzzy_fallback: bool = True
    ) -> str:
        """搜小米官方曲库，返回匹配到的 audioID（供触屏音箱拉取歌词/封面）；未命中返回 ""。

        匹配逻辑与 device_player 本地播放侧共用
        （utils.device_utils.search_audio_id），两边只保留各自的登录/日志策略 ——
        历史上这两处各写了一份且严格程度不同，导致同一首歌"本地播放"和
        "投送播放"拿到不同的封面/歌词 audioID。

        fuzzy_fallback：True 精确未命中时回退首条；False 供持续搜索场景
        （AirPlay 歌词监听器）严格拒绝，避免滚动歌词行被模糊命中误判为切歌。
        """
        try:
            await self._ensure_login()
            audio_id = await _search_audio_id(
                self._auth.mina_service,
                title,
                artist,
                fuzzy_fallback=fuzzy_fallback,
            )
        except Exception as e:
            self.log.warning(f"[CAST] 曲库搜索失败 ({title} / {artist}): {e}")
            return ""
        if audio_id:
            self.log.info(
                f"[CAST] 曲库搜索命中 ({title} / {artist}) audioID={audio_id}"
            )
        else:
            self.log.info(f"[CAST] 曲库搜索无匹配 ({title} / {artist})")
        return audio_id


def build_controllers(
    device_manager, config, log_=None
) -> dict[str, SpeakerController]:
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
