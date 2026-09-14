"""Home Assistant 语音桥接：规则装载、指令执行、TTS 反馈、延迟与定时。

移植自 xiaoai-ha-bridge 的 bridge_loop 里"匹配 → 调 HA → TTS 回话"那一段，
但登录、对话轮询、TTS 全部复用 xiaomusic 既有链路，因此这里只剩：

    can_handle(query)   轻量判断这句话是否归 HA 管（给 command_handler 用）
    handle(did, query)  真正执行：调 HA 服务 / 建定时 / 延迟调用，并 TTS 回话

规则存在 {conf_path}/ha_rules.json，编辑页（/static/ha.html）或 API 维护。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from xiaomusic.ha.client import HAClient, build_time_automation
from xiaomusic.ha.rules import (
    compile_rules,
    parse_delay_minutes,
    parse_query,
    split_action,
)

# 与 xiaomusic.ha.client 同一个 logger 名前缀，便于统一过滤 [HA] 日志
log = logging.getLogger("xiaomusic.ha")

# 规则文件变更的探测间隔（秒）：语音指令很频繁，不能每次都 stat
_RELOAD_CHECK_INTERVAL = 5.0

# 首次使用时写入的示例规则（记得把 entity_id 换成你自己的）
DEFAULT_RULES = [
    {
        "pattern": "(打开|开)(客厅灯|客厅的灯)",
        "action": {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.living_room",
            "reply": "好的，客厅灯已打开",
        },
    },
    {
        "pattern": "(关闭|关)(客厅灯|客厅的灯)",
        "action": {
            "domain": "light",
            "service": "turn_off",
            "entity_id": "light.living_room",
            "reply": "好的，客厅灯已关闭",
        },
    },
    {
        "pattern": "把客厅灯调到{num}[%％]",
        "action": {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.living_room",
            "brightness_pct": "{0}",
            "reply": "好的，亮度已调整",
        },
    },
    {
        "pattern": "客厅空调{num}分钟后关闭",
        "action": {
            "domain": "climate",
            "service": "turn_off",
            "entity_id": "climate.living_room_ac",
            "delay_minutes": "{0}",
            "reply": "好的，{0} 分钟后关闭客厅空调",
        },
    },
]


class HABridge:
    """语音 → Home Assistant 的桥接器（每个 XiaoMusic 实例一个）。"""

    def __init__(self, xiaomusic):
        self.xiaomusic = xiaomusic
        self.config = xiaomusic.config
        # 取主程序的 logger；若构造时机早于 setup_logger()（日志句柄还没建），
        # 退回本模块的 logger —— 不要因为一个日志句柄把整个启动流程打断
        self.log = getattr(xiaomusic, "log", None) or log

        self._compiled: list[dict] = []
        self._raw_rules: list[dict] = []
        self._loaded = False
        self._last_check = 0.0
        self._file_mtime = 0.0
        self._delay_tasks: set[asyncio.Task] = set()

        # 运行状态（给 Web 面板看）
        self.last_command = ""
        self.last_command_time = ""
        self.last_reply = ""
        self.last_error = ""
        self.command_count = 0

    # ---- 配置 ----

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config, "enable_ha", False))

    @property
    def rules_path(self) -> str:
        conf_dir = getattr(self.config, "conf_path", "") or "conf"
        return os.path.join(conf_dir, "ha_rules.json")

    @property
    def tts_reply(self) -> bool:
        return bool(getattr(self.config, "ha_tts_reply", True))

    @property
    def client(self) -> HAClient:
        return HAClient(
            getattr(self.config, "ha_url", ""),
            getattr(self.config, "ha_token", ""),
        )

    # ---- 规则装载 ----

    def ensure_loaded(self):
        """首次使用时装载规则；文件不存在就写入示例规则。"""
        if self._loaded:
            return
        self._loaded = True
        if not os.path.exists(self.rules_path):
            try:
                self._write_rules(DEFAULT_RULES)
                self.log.info(
                    f"[HA] 已生成示例规则: {self.rules_path}（请改成自己的实体）"
                )
            except OSError as e:
                self.last_error = f"写入规则文件失败：{e}"
                self.log.warning(f"[HA] 写入规则文件失败: {e}")
        self._load_from_file()

    def refresh_if_changed(self):
        """规则文件被手工改动后热更新（最多每 5 秒查一次 mtime）。"""
        now = time.monotonic()
        if now - self._last_check < _RELOAD_CHECK_INTERVAL:
            return
        self._last_check = now
        try:
            mtime = os.path.getmtime(self.rules_path)
        except OSError:
            return
        if mtime != self._file_mtime:
            self.log.info("[HA] 检测到规则文件变化，重新装载")
            self._load_from_file()

    def _load_from_file(self):
        try:
            with open(self.rules_path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            self._compiled, self._raw_rules, self._file_mtime = [], [], 0.0
            return
        except (OSError, json.JSONDecodeError) as e:
            self.last_error = f"规则文件读取失败：{e}"
            self.log.warning(f"[HA] 规则文件读取失败: {e}")
            return

        rules = data.get("rules") if isinstance(data, dict) else data
        if not isinstance(rules, list):
            self.last_error = '规则文件格式不对（应为 {"rules": [...]} 或数组）'
            self.log.warning(f"[HA] {self.last_error}")
            return

        self._raw_rules = rules
        self._compiled, errors = compile_rules(rules)
        for err in errors:
            self.log.warning(f"[HA] {err}")
        try:
            self._file_mtime = os.path.getmtime(self.rules_path)
        except OSError:
            self._file_mtime = 0.0
        self.log.info(f"[HA] 已装载 {len(self._compiled)} 条规则 ({self.rules_path})")

    def _write_rules(self, rules: list[dict]):
        conf_dir = os.path.dirname(self.rules_path)
        if conf_dir:
            os.makedirs(conf_dir, exist_ok=True)
        with open(self.rules_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "rules": rules}, f, ensure_ascii=False, indent=2)

    def get_rules(self) -> list[dict]:
        """返回原始规则（给编辑页）。"""
        self.ensure_loaded()
        return self._raw_rules

    def save_rules(self, rules) -> tuple[bool, str]:
        """整表保存规则：全部校验通过才落盘。"""
        if not isinstance(rules, list):
            return False, "rules 必须是数组"
        _, errors = compile_rules(rules)
        if errors:
            return False, "；".join(errors)
        try:
            self._write_rules(rules)
        except OSError as e:
            return False, f"写入失败：{e}"
        self._loaded = True
        self._load_from_file()
        self.last_error = ""
        return True, ""

    # ---- 匹配与执行 ----

    def can_handle(self, query: str) -> bool:
        """这句话是否命中某条 HA 规则（不执行任何动作）。"""
        if not self.enabled:
            return False
        self.ensure_loaded()
        self.refresh_if_changed()
        return parse_query(self._compiled, query) is not None

    def test_rule(self, query: str) -> dict | None:
        """只解析不执行（编辑页"试说一句"用）。"""
        self.ensure_loaded()
        return parse_query(self._compiled, query)

    async def handle(self, did: str, query: str) -> bool:
        """执行命中的规则，返回是否已处理。"""
        self.ensure_loaded()
        parsed = parse_query(self._compiled, query)
        if not parsed:
            return False

        action = parsed["action"]
        domain, service, local, data = split_action(action)
        reply = str(local.get("reply") or "好的")
        self.last_command = query
        self.last_command_time = time.strftime("%H:%M:%S")
        self.command_count += 1
        self.log.info(
            f"[HA] 命中规则 pattern={parsed['pattern']!r} → {domain}.{service} data={data}"
        )

        try:
            if str(local.get("type") or "").lower() == "schedule":
                reply = await self._handle_schedule(domain, service, data, local, reply)
            elif parse_delay_minutes(local.get("delay_minutes")):
                reply = self._handle_delay(domain, service, data, local, reply)
            else:
                ok, err = await self.client.call_service(domain, service, data)
                if not ok:
                    self.last_error = err
                    self.log.warning(f"[HA] 调用 {domain}.{service} 失败: {err}")
                reply = reply if ok else "抱歉，操作失败了"
        except Exception as e:
            self.last_error = str(e)
            self.log.exception(f"[HA] 执行失败: {e}")
            reply = "抱歉，操作失败了"

        self.last_reply = reply
        await self._reply(did, reply)
        return True

    async def _handle_schedule(self, domain, service, data, local, reply) -> str:
        """在 HA 里创建定时自动化。"""
        schedule_time = local.get("schedule_time")
        schedule_days = str(local.get("schedule_days") or "")
        automation_id, config = build_time_automation(
            domain, service, data, schedule_time, schedule_days
        )
        if not automation_id:
            self.last_error = f"schedule_time 非法：{schedule_time}"
            self.log.warning(f"[HA] {self.last_error}")
            return "抱歉，时间格式不对，请说几点几分"

        ok, err = await self.client.save_automation(automation_id, config)
        if not ok:
            self.last_error = err
            self.log.warning(f"[HA] 创建定时自动化失败: {err}")
            return "抱歉，创建定时任务失败了"

        self.log.info(
            f"[HA] 已创建定时自动化 {automation_id}（{schedule_time} {schedule_days}）"
        )
        days_text = f"{schedule_days} " if schedule_days else "每天 "
        return f"好的，已创建定时任务：{days_text}{schedule_time}，{reply}"

    def _handle_delay(self, domain, service, data, local, reply) -> str:
        """X 分钟后执行：先回话，再挂后台倒计时（进程重启会丢）。"""
        minutes = parse_delay_minutes(local.get("delay_minutes"))
        task = asyncio.create_task(
            self._delayed_call(domain, service, data, minutes * 60)
        )
        self._delay_tasks.add(task)
        task.add_done_callback(self._delay_tasks.discard)
        self.log.info(f"[HA] 定时任务：{minutes} 分钟后执行 {domain}.{service} {data}")
        return reply

    async def _delayed_call(
        self, domain: str, service: str, data: dict, delay_sec: int
    ):
        try:
            await asyncio.sleep(delay_sec)
            ok, err = await self.client.call_service(domain, service, data)
            if ok:
                self.log.info(f"[HA] 定时任务完成: {domain}.{service}")
            else:
                self.last_error = err
                self.log.warning(f"[HA] 定时任务失败: {domain}.{service} {err}")
        except asyncio.CancelledError:
            self.log.info(f"[HA] 定时任务被取消: {domain}.{service}")
        except Exception as e:
            self.log.warning(f"[HA] 定时任务异常: {e}")

    async def cancel_delays(self):
        """进程退出时取消未执行的延迟任务。"""
        tasks = list(self._delay_tasks)
        self._delay_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reply(self, did: str, text: str):
        """TTS 播报结果（失败不影响主流程）。"""
        if not text:
            return
        if not self.tts_reply:
            self.log.info(f"[HA] 已关闭 TTS 回复，跳过播报: {text}")
            return
        try:
            await self.xiaomusic.do_tts(did, text)
        except Exception as e:
            self.log.warning(f"[HA] TTS 播报失败: {e}")

    # ---- 面板用的查询 ----

    async def test_connection(self) -> tuple[bool, str]:
        return await self.client.test_connection()

    async def list_entities(self) -> tuple[list[dict], str]:
        return await self.client.get_states()

    async def list_services(self) -> tuple[dict, str]:
        return await self.client.get_services()

    async def list_automations(self) -> tuple[list[dict], str]:
        return await self.client.list_automations()

    async def delete_automation(self, automation_id: str) -> tuple[bool, str]:
        from xiaomusic.ha.client import strip_automation_prefix
        from xiaomusic.ha.rules import AUTOMATION_PREFIX

        # 只允许删除本程序创建的定时，避免误删用户自己的自动化
        # （参数可以是 entity_id 也可以是裸 id）
        bare_id = strip_automation_prefix(automation_id)
        if not bare_id.startswith(AUTOMATION_PREFIX):
            return False, f"只允许删除 {AUTOMATION_PREFIX} 开头的定时任务"
        return await self.client.delete_automation(bare_id)

    def status(self) -> dict:
        self.ensure_loaded()
        return {
            "enabled": self.enabled,
            "configured": self.client.configured,
            "ha_url": self.client.base_url,
            "token_configured": bool(self.client.token),
            "tts_reply": self.tts_reply,
            "rules_count": len(self._compiled),
            "invalid_rules": max(0, len(self._raw_rules) - len(self._compiled)),
            "rules_path": self.rules_path,
            "command_count": self.command_count,
            "last_command": self.last_command,
            "last_command_time": self.last_command_time,
            "last_reply": self.last_reply,
            "last_error": self.last_error,
            "pending_delays": len(self._delay_tasks),
        }


__all__ = ["DEFAULT_RULES", "HABridge"]
