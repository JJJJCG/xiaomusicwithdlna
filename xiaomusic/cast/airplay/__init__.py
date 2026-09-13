# SPDX-License-Identifier: GPL-3.0-or-later
# 移植自 MiAir Next (https://github.com/deerwan/miair-next)，
# 派生出处与许可变更说明见仓库根目录 NOTICE。
"""AirPlay 接收服务 - 将 iPhone/iPad/Mac 的 AirPlay 音频转发到小米音箱"""

from xiaomusic.cast.airplay.server import AirPlayServer

__all__ = ["AirPlayServer"]
