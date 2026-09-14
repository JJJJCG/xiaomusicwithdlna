"""Home Assistant REST API 客户端。

移植自 xiaoai-ha-bridge 的 HAClient，去掉 OpenAI 相关部分，
并补上"每天/工作日/周末 X 点"的定时自动化构建。

只用到 HA 的这几个接口：
    GET    /api/config                                  → 测试连接
    POST   /api/services/{domain}/{service}             → 调用服务
    GET    /api/states                                  → 实体列表（编辑页下拉用）
    GET    /api/services                                → 服务列表（编辑页操作下拉用）
    POST   /api/config/automation/config/{id}           → 创建/覆盖定时自动化
    DELETE /api/config/automation/config/{id}           → 删除定时自动化
    POST   /api/services/automation/reload              → 重载定时自动化
"""

from __future__ import annotations

import logging
import re

import aiohttp

from xiaomusic.ha.rules import AUTOMATION_PREFIX

log = logging.getLogger("xiaomusic.ha")

DEFAULT_TIMEOUT = 10

# 星期写法 → HA 的 weekday 取值
WEEKDAY_MAP = {
    "mon": "mon",
    "tue": "tue",
    "wed": "wed",
    "thu": "thu",
    "fri": "fri",
    "sat": "sat",
    "sun": "sun",
    "周一": "mon",
    "周二": "tue",
    "周三": "wed",
    "周四": "thu",
    "周五": "fri",
    "周六": "sat",
    "周日": "sun",
    "周天": "sun",
    "星期一": "mon",
    "星期二": "tue",
    "星期三": "wed",
    "星期四": "thu",
    "星期五": "fri",
    "星期六": "sat",
    "星期日": "sun",
    "星期天": "sun",
}
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")
_WEEKEND = ("sat", "sun")


def build_time_automation(
    domain: str, service: str, data: dict, schedule_time: str, schedule_days: str = ""
) -> tuple[str, dict] | tuple[None, None]:
    """构建"每天/工作日/周末 HH:MM 执行某服务"的 HA 自动化配置。

    Returns:
        (automation_id, config)，schedule_time 非法时返回 (None, None)
    """
    if not re.match(r"^\d{1,2}:\d{1,2}$", str(schedule_time or "").strip()):
        return None, None

    parts = str(schedule_time).strip().split(":")
    at_time = f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
    entity_id = data.get("entity_id", "")

    action_item: dict = {
        "service": f"{domain}.{service}",
        "target": {"entity_id": entity_id},
    }
    extra = {k: v for k, v in data.items() if k != "entity_id"}
    if extra:
        action_item["data"] = extra

    config: dict = {
        "alias": f"xiaomusic 定时-{at_time[:5]} {entity_id}",
        "description": "由 xiaomusic 语音指令自动创建",
        "trigger": [{"platform": "time", "at": at_time}],
        "action": [action_item],
        "mode": "single",
    }

    weekdays = _parse_weekdays(schedule_days)
    if weekdays:
        config["condition"] = [{"condition": "time", "weekday": weekdays}]

    # id 里带上时刻 + 实体 + 操作：同一时刻同一实体的不同操作
    # （比如"每天7点开灯"和"每天7点关灯"）不会互相覆盖，
    # 而完全相同的规则重复下发时按 id 覆盖，天然幂等。
    hhmm = at_time[:5].replace(":", "")
    automation_id = f"{AUTOMATION_PREFIX}{hhmm}_{_slug(entity_id)}_{service}"
    return automation_id, config


def strip_automation_prefix(automation_id: str) -> str:
    """把 entity_id（automation.xxx）或裸 id 统一成裸 id。"""
    text = str(automation_id or "").strip()
    if text.startswith("automation."):
        text = text[len("automation.") :]
    return text


def _parse_weekdays(schedule_days: str) -> list[str]:
    """解析星期写法；返回空列表表示不限制（每天）。"""
    days = str(schedule_days or "").strip().lower()
    if days in ("", "daily", "everyday", "每天", "每天一次"):
        return []
    if days in ("weekdays", "工作日"):
        return list(_WEEKDAYS)
    if days in ("weekends", "周末"):
        return list(_WEEKEND)
    found: list[str] = []
    for token in re.split(r"[,，、\s]+", days):
        key = WEEKDAY_MAP.get(token.strip())
        if key and key not in found:
            found.append(key)
    return found


def _slug(text: str) -> str:
    """把 entity_id 转成可用于 automation id 的短标识。"""
    return re.sub(r"[^0-9a-zA-Z]+", "_", str(text or "")).strip("_").lower()


class HAClient:
    """Home Assistant REST 客户端（每次调用开一个短连接，与仓库既有风格一致）。"""

    def __init__(self, base_url: str, token: str, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=self.timeout)

    # ---- 连接 ----

    async def test_connection(self) -> tuple[bool, str]:
        """返回 (是否连通, 描述文本)。"""
        if not self.configured:
            return False, "HA 地址或长期访问令牌未配置"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/config",
                    headers=self.headers,
                    timeout=self._timeout(),
                ) as resp:
                    if resp.status != 200:
                        return False, f"HA 返回 {resp.status}（检查地址 / 令牌 / 网络）"
                    data = await resp.json()
                    version = data.get("version", "")
                    location = data.get("location_name", "")
                    desc = "已连接 Home Assistant"
                    if version:
                        desc += f" {version}"
                    if location:
                        desc += f"（{location}）"
                    return True, desc
        except Exception as e:
            return False, f"连接失败：{e}"

    # ---- 服务调用 ----

    async def call_service(
        self, domain: str, service: str, data: dict
    ) -> tuple[bool, str]:
        """调用 HA 服务，返回 (是否成功, 错误描述)。"""
        url = f"{self.base_url}/api/services/{domain}/{service}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=data, headers=self.headers, timeout=self._timeout()
                ) as resp:
                    if resp.status in (200, 201):
                        return True, ""
                    detail = (await resp.text())[:200]
                    return False, f"HA 返回 {resp.status} {detail}"
        except Exception as e:
            return False, f"调用异常：{e}"

    # ---- 查询 ----

    async def get_states(self) -> tuple[list[dict], str]:
        """拉取全部实体（供编辑页做下拉）。"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/states",
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=max(self.timeout, 20)),
                ) as resp:
                    if resp.status != 200:
                        return [], f"HA 返回 {resp.status}"
                    states = await resp.json()
                    items = [
                        {
                            "entity_id": s.get("entity_id", ""),
                            "name": (s.get("attributes") or {}).get("friendly_name", "")
                            or s.get("entity_id", ""),
                            "state": s.get("state", ""),
                        }
                        for s in states
                        if s.get("entity_id")
                    ]
                    items.sort(key=lambda x: x["entity_id"])
                    return items, ""
        except Exception as e:
            return [], f"获取实体失败：{e}"

    async def get_services(self) -> tuple[dict, str]:
        """拉取服务列表（供编辑页选择 domain/service）。"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/services",
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=max(self.timeout, 20)),
                ) as resp:
                    if resp.status != 200:
                        return {}, f"HA 返回 {resp.status}"
                    raw = await resp.json()
                    services: dict = {}
                    for item in raw:
                        domain = item.get("domain", "")
                        if not domain:
                            continue
                        services[domain] = sorted((item.get("services") or {}).keys())
                    return services, ""
        except Exception as e:
            return {}, f"获取服务失败：{e}"

    # ---- 定时自动化 ----

    async def save_automation(
        self, automation_id: str, config: dict
    ) -> tuple[bool, str]:
        """创建/覆盖定时自动化并重载。"""
        url = f"{self.base_url}/api/config/automation/config/{automation_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=config, headers=self.headers, timeout=self._timeout()
                ) as resp:
                    if resp.status not in (200, 201):
                        detail = (await resp.text())[:200]
                        return False, f"HA 返回 {resp.status} {detail}"
                async with session.post(
                    f"{self.base_url}/api/services/automation/reload",
                    json={},
                    headers=self.headers,
                    timeout=self._timeout(),
                ) as resp:
                    if resp.status not in (200, 201):
                        # 自动化已写入但未能热重载，重启 HA 后依然生效
                        return True, "已写入，但自动重载失败（重启 HA 后生效）"
            return True, ""
        except Exception as e:
            return False, f"创建定时失败：{e}"

    async def delete_automation(self, automation_id: str) -> tuple[bool, str]:
        automation_id = strip_automation_prefix(automation_id)
        url = f"{self.base_url}/api/config/automation/config/{automation_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    url, headers=self.headers, timeout=self._timeout()
                ) as resp:
                    if resp.status != 200:
                        detail = (await resp.text())[:200]
                        return False, f"HA 返回 {resp.status} {detail}"
                async with session.post(
                    f"{self.base_url}/api/services/automation/reload",
                    json={},
                    headers=self.headers,
                    timeout=self._timeout(),
                ) as resp:
                    if resp.status not in (200, 201):
                        # 删除已生效，只是没能热重载（重启 HA 后一致）
                        return True, "已删除，但自动重载失败（重启 HA 后生效）"
            return True, ""
        except Exception as e:
            return False, f"删除定时失败：{e}"

    async def list_automations(self) -> tuple[list[dict], str]:
        """列出本程序创建的定时自动化。"""
        states, err = await self.get_states()
        if err:
            return [], err
        items = [
            s
            for s in states
            if s["entity_id"].startswith(f"automation.{AUTOMATION_PREFIX}")
        ]
        return items, ""


__all__ = [
    "DEFAULT_TIMEOUT",
    "HAClient",
    "WEEKDAY_MAP",
    "build_time_automation",
    "strip_automation_prefix",
]
