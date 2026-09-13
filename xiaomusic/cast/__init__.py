# SPDX-License-Identifier: GPL-3.0-or-later
# 移植自 MiAir Next (https://github.com/deerwan/miair-next)，
# 派生出处与许可变更说明见仓库根目录 NOTICE。
"""投送支持：把小爱音箱变成 DLNA 渲染器与 AirPlay 接收器。

协议层代码移植自 miair-next (GPL-3.0-or-later)：
    https://github.com/deerwan/miair-next
- dlna/     UPnP AV MediaRenderer (SSDP + SOAP + 事件订阅 + 媒体代理)
- airplay/  AirPlay 1 (RAOP) 音频接收 (RTMP/RTSP + FairPlay + RTP 解码)

与上游的差异：
- 新增 speaker_adapter.py 把 xiaomusic 的 XiaoMusicDevice 适配成协议层期望的接口
- 新增 manager.py 管理生命周期，替代上游的 Orchestrator（登录/续期交给 xiaomusic）
"""

from xiaomusic.cast.manager import CastManager

__all__ = ["CastManager"]
