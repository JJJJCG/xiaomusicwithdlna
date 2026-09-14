"""口语规则解析：把"打开客厅灯"这类说法映射成 Home Assistant 服务调用。

移植自 xiaoai-ha-bridge 的 IntentParser，并补上规则校验与定时字段。
规则是纯 JSON（不引入 dataclass），方便 API/前端直接读写：

    {
      "pattern": "(打开|开)(客厅灯|客厅的灯)",
      "action": {
        "domain": "light",              # 必填
        "service": "turn_on",           # 必填
        "entity_id": "light.living_room",  # 必填
        "brightness_pct": "{0}",        # 其它键原样发给 HA；支持 {0}/{1} 与 {num}
        "reply": "好的，客厅灯已打开",     # 本地消费：TTS 播报
        "delay_minutes": "{0}"          # 本地消费：N 分钟后才真正调用
      }
    }
"""

from __future__ import annotations

import re

# 口语数字占位符：pattern 里写 {num} 会替换成 (\d+)
NUM_TOKEN = "{num}"
_NUM_RE = re.compile(r"\{num\}", re.IGNORECASE)
# 动作值里的捕获组占位符，如 {0} / {1}
_GROUP_RE = re.compile(r"\{\d+\}")
# action 里由本地消费、不发给 HA 的键
LOCAL_ACTION_KEYS = (
    "reply",
    "delay_minutes",
    "type",
    "schedule_time",
    "schedule_days",
)
# 本程序在 HA 里创建的定时自动化 id 前缀（便于识别与安全删除）
AUTOMATION_PREFIX = "xiaomusic_ha_"


class RuleError(ValueError):
    """规则非法（供 API 直接回给前端）。"""


def compile_rule(rule: dict) -> dict:
    """校验并编译单条规则。

    Returns:
        {"pattern": str, "action": dict, "regex": re.Pattern}

    Raises:
        RuleError: pattern/action/正则非法
    """
    if not isinstance(rule, dict):
        raise RuleError("规则必须是对象")
    pattern = str(rule.get("pattern") or "").strip()
    if not pattern:
        raise RuleError("pattern 不能为空")

    action = rule.get("action")
    if not isinstance(action, dict):
        raise RuleError("action 必须是对象")
    if not str(action.get("domain") or "").strip():
        raise RuleError("action.domain 不能为空")
    if not str(action.get("service") or "").strip():
        raise RuleError("action.service 不能为空")
    if not _has_entity(action.get("entity_id")):
        raise RuleError("action.entity_id 不能为空")

    if _is_schedule(action) and not _looks_like_time(action.get("schedule_time")):
        raise RuleError("定时规则的 schedule_time 需要是 HH:MM")

    try:
        # 注意：替换内容必须用函数形式给，写成字符串会被当成替换模板、
        # 其中 \d 是非法转义（re.sub 先编译模板，哪怕 pattern 里没有 {num} 也会炸）
        regex = re.compile(_NUM_RE.sub(lambda _m: r"(\d+)", pattern), re.IGNORECASE)
    except re.error as e:
        raise RuleError(f"pattern 不是合法正则：{e}") from e

    return {"pattern": pattern, "action": action, "regex": regex}


def compile_rules(rules) -> tuple[list[dict], list[str]]:
    """批量编译，跳过非法规则并收集原因（不因为一条错规则让整份配置失效）。"""
    compiled: list[dict] = []
    errors: list[str] = []
    for idx, rule in enumerate(rules or []):
        try:
            compiled.append(compile_rule(rule))
        except RuleError as e:
            errors.append(f"第 {idx + 1} 条规则已跳过：{e}")
    return compiled, errors


def parse_query(compiled_rules, text: str) -> dict | None:
    """按顺序匹配口语文本。

    Returns:
        {"pattern": 命中的模式, "action": 解析后的动作}，未命中返回 None
    """
    text = (text or "").strip()
    if not text:
        return None
    for item in compiled_rules:
        match = item["regex"].search(text)
        if not match:
            continue
        return {
            "pattern": item["pattern"],
            "action": _render(item["action"], match.groups()),
        }
    return None


def split_action(action: dict) -> tuple[str, str, dict, dict]:
    """拆分动作：返回 (domain, service, 本地字段, 发给 HA 的参数字典)。"""
    local = {k: action[k] for k in LOCAL_ACTION_KEYS if k in action}
    data = {
        k: v
        for k, v in action.items()
        if k not in ("domain", "service") and k not in LOCAL_ACTION_KEYS
    }
    return (
        str(action.get("domain") or "").strip(),
        str(action.get("service") or "").strip(),
        local,
        data,
    )


def parse_delay_minutes(value) -> int:
    """把 delay_minutes 解析成整数分钟（非法或 <=0 返回 0）。"""
    try:
        minutes = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
    return minutes if minutes > 0 else 0


def _render(action: dict, groups: tuple) -> dict:
    """把 action 里的 {0}/{1}... 用正则捕获组回填，并做值类型转换。"""
    rendered = {}
    for key, val in action.items():
        if isinstance(val, str):
            for i, group in enumerate(groups):
                val = val.replace(f"{{{i}}}", group or "")
            rendered[key] = _convert(val)
        else:
            rendered[key] = val
    return rendered


def _convert(val: str):
    """数字字符串转成 int/float，其它原样返回（HA 需要数值型参数）。"""
    stripped = val.strip()
    if not stripped:
        return val
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        return val


def _has_entity(entity_id) -> bool:
    if isinstance(entity_id, (list, tuple)):
        return any(str(e).strip() for e in entity_id)
    return bool(str(entity_id or "").strip())


def _is_schedule(action: dict) -> bool:
    return str(action.get("type") or "").strip().lower() == "schedule"


def _looks_like_time(value) -> bool:
    text = str(value or "").strip()
    # 允许 "7:30" 与 "{0}:00" 两种写法：后者由捕获组在运行期回填，
    # 真正的时间校验交给 build_time_automation 再做一次
    if _GROUP_RE.search(text):
        return True
    return bool(re.match(r"^\d{1,2}:\d{1,2}$", text))


__all__ = [
    "AUTOMATION_PREFIX",
    "LOCAL_ACTION_KEYS",
    "NUM_TOKEN",
    "RuleError",
    "compile_rule",
    "compile_rules",
    "parse_delay_minutes",
    "parse_query",
    "split_action",
]
