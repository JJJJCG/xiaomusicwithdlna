"""Home Assistant 接入：把小爱语音指令映射成 HA 服务调用。

移植自 xiaoai-ha-bridge (https://github.com/chenshuhe/xiaoai-ha-bridge, MIT)，
只保留"语音 → HA"这一段：登录、对话轮询、TTS 全部复用 xiaomusic 既有链路。

- client.py  HA REST 客户端（服务调用 / 实体与服务列表 / 定时自动化）
- rules.py   口语正则规则解析（{num} 数字提取、{0} 参数回填、规则校验）
- bridge.py  规则装载与热更新、指令执行、TTS 反馈、延迟与定时
"""

from xiaomusic.ha.bridge import HABridge

__all__ = ["HABridge"]
