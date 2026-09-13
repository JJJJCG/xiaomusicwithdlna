# SPDX-License-Identifier: GPL-3.0-or-later
# 移植自 MiAir Next (https://github.com/deerwan/miair-next)，
# 派生出处与许可变更说明见仓库根目录 NOTICE。
"""投送服务管理器：统一启停 DLNA / AirPlay。

移植自 miair-next 的 app/services/orchestrator.py（Orchestrator），
去掉了其中的小米账号登录/续期/自动重启逻辑 —— 那些由 xiaomusic 的
AuthManager 负责，这里只在登录完成后把协议服务拉起来。
"""

from __future__ import annotations

import asyncio
import logging

from xiaomusic.cast.airplay.speaker_airplay import AirPlayManager
from xiaomusic.cast.dlna.device_server import DeviceServer
from xiaomusic.cast.dlna.renderer import DLNARenderer
from xiaomusic.cast.dlna.ssdp import SSDPServer
from xiaomusic.cast.speaker_adapter import CastConfig, build_controllers

log = logging.getLogger("xiaomusic.cast")

# 影响投送服务的配置项。这些值或设备列表变化时才需要重建服务，
# 避免用户保存无关设置（如歌单、TTS 音色）时打断正在进行的投送。
_CAST_CONFIG_KEYS = (
    "enable_cast",
    "cast_hostname",
    "dlna_port",
    "cast_default_volume",
    "cast_follow_device_volume",
    "cast_touchscreen_lyrics",
    "cast_default_cover_url",
    "cast_default_audio_id",
    "cast_auto_resume_on_interrupt",
    "cast_resume_delay_seconds",
    "cast_auto_play_on_set_uri",
    "ffmpeg_location",
)


class CastManager:
    """DLNA / AirPlay 服务的生命周期管理。

    DLNA (SSDP + HTTP) 与 AirPlay (mDNS + RTSP) 都依赖组播发现，
    需要宿主网络可达；在 Docker 中必须使用 host 网络模式。
    """

    def __init__(self, xiaomusic):
        self.xiaomusic = xiaomusic
        self.config = xiaomusic.config
        self.log = xiaomusic.log

        self.renderers: dict[str, DLNARenderer] = {}  # udn -> renderer
        self._did_to_udn: dict[str, str] = {}  # did -> udn
        self.ssdp_server: SSDPServer | None = None
        self.device_server: DeviceServer | None = None
        self.airplay_manager: AirPlayManager | None = None
        self.running = False
        # 重启串行化：防止配置连续变更触发多个 restart 并发互相踩踏
        self._restart_lock = asyncio.Lock()
        # 上次启动时的配置/设备指纹，用于跳过无关的配置变更
        self._signature: tuple | None = None

    def _current_signature(self) -> tuple:
        """配置 + 设备列表的指纹。"""
        cfg = tuple((k, getattr(self.config, k, None)) for k in _CAST_CONFIG_KEYS)
        try:
            dids = tuple(sorted(self.xiaomusic.device_manager.devices.keys()))
        except Exception:
            dids = ()
        return (cfg, dids)

    # ---- 查询 ----

    def get_renderer_by_did(self, did: str) -> DLNARenderer | None:
        udn = self._did_to_udn.get(did)
        return self.renderers.get(udn) if udn else None

    def status(self) -> dict:
        """给 Web/API 用的运行状态快照。"""
        return {
            "running": self.running,
            "hostname": self._cast_config.hostname if hasattr(self, "_cast_config") else "",
            "dlna_port": self._cast_config.dlna_port if hasattr(self, "_cast_config") else 0,
            "renderers": [
                {
                    "did": did,
                    "udn": udn,
                    "name": self.renderers[udn].friendly_name,
                    "state": self.renderers[udn].transport_state,
                }
                for did, udn in self._did_to_udn.items()
                if udn in self.renderers
            ],
            "airplay": sorted(self.airplay_manager.speaker_airplays) if self.airplay_manager else [],
        }

    # ---- 启停 ----

    async def start(self):
        """启动 DLNA + AirPlay。设备列表为空时静默跳过。"""
        if self.running:
            return
        if not getattr(self.config, "enable_cast", True):
            self.log.info("[CAST] enable_cast 为关闭，跳过 DLNA/AirPlay 启动")
            return

        try:
            await self._start_locked()
        except Exception as e:
            self.log.warning(f"[CAST] 启动 DLNA/AirPlay 失败: {e}")
            self.running = False
            await self._clear_runtime()

    async def _start_locked(self):
        controllers = build_controllers(
            self.xiaomusic.device_manager, self.config, self.log
        )
        if not controllers:
            self.log.info("[CAST] 没有可用的音箱，DLNA/AirPlay 未启动")
            return

        self._cast_config = CastConfig(self.config)
        cast_cfg = self._cast_config
        self.log.info(
            f"[CAST] 启动 DLNA/AirPlay: 主机 {cast_cfg.hostname}, "
            f"DLNA 端口 {cast_cfg.dlna_port}, 共 {len(controllers)} 个音箱"
        )

        self.ssdp_server = SSDPServer(cast_cfg.hostname, cast_cfg.dlna_port)
        self.device_server = DeviceServer(
            cast_cfg.hostname, cast_cfg.dlna_port, cast_cfg
        )

        for did, controller in controllers.items():
            speaker = controller.speaker
            udn = speaker.udn
            friendly_name = speaker.get_dlna_name()

            renderer = DLNARenderer(
                udn, friendly_name, controller, cast_cfg.default_volume, config=cast_cfg
            )
            self.renderers[udn] = renderer
            self._did_to_udn[did] = udn

            self.ssdp_server.register_renderer(udn, friendly_name)
            self.device_server.register_renderer(renderer)
            self.log.info(f"[CAST] 已创建 DLNA 渲染器: {friendly_name} (udn={udn})")

        await self.ssdp_server.start()
        await self.device_server.start()

        # AirPlay：每个音箱一个独立接收器
        self.airplay_manager = AirPlayManager(cast_cfg.hostname, config=cast_cfg)
        await self.airplay_manager.start_for_speakers(controllers)

        self.running = True
        self._signature = self._current_signature()
        self.log.info(
            f"[CAST] DLNA/AirPlay 启动完成，共 {len(self.renderers)} 个音箱；"
            f"手机投送现在应能发现这些设备"
        )

    async def restart(self, reason: str = "配置变更"):
        """重启全部投送服务（配置变更后调用）。"""
        async with self._restart_lock:
            self.log.info(f"[CAST] 正在重启 DLNA/AirPlay（{reason}）...")
            await self.stop()
            await self.start()

    async def restart_if_config_changed(self, reason: str = "配置变更"):
        """仅当投送相关配置或设备列表变化时才重启。

        xiaomusic 保存设置时会走 reinit()，若每次都无条件重启 DLNA/AirPlay，
        用户改一个无关选项就会打断正在进行的手机投送。
        """
        signature = self._current_signature()
        if self.running and signature == self._signature:
            self.log.debug("[CAST] 投送相关配置未变化，保持服务运行")
            return
        await self.restart(reason)

    async def stop(self):
        """停止全部投送服务并释放端口 / mDNS 注册。"""
        await self._stop_dlna()

        if self.airplay_manager:
            try:
                await self.airplay_manager.stop()
            except Exception as e:
                self.log.warning(f"[CAST] 停止 AirPlay 失败: {e}")
            self.airplay_manager = None

        self.running = False
        self.log.info("[CAST] DLNA/AirPlay 已停止")

    async def _stop_dlna(self):
        if self.ssdp_server:
            try:
                await self.ssdp_server.stop()
            except Exception as e:
                self.log.warning(f"[CAST] 停止 SSDP 失败: {e}")
            self.ssdp_server = None
        if self.device_server:
            try:
                await self.device_server.stop()
            except Exception as e:
                self.log.warning(f"[CAST] 停止 DLNA HTTP 服务失败: {e}")
            self.device_server = None
        self.renderers.clear()
        self._did_to_udn.clear()

    async def _clear_runtime(self):
        self.renderers.clear()
        self._did_to_udn.clear()


__all__ = ["CastManager"]
