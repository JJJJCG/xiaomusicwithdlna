"""Home Assistant 接入自检（不需要真实的 HA 服务器）。

用法（仓库根目录）：
    python test/test_ha_bridge.py

做法：只把 xiaomusic.ha.client 里的 aiohttp.ClientSession 换成一个假会话，
其余全部走真实源码。覆盖：

    规则校验 / 解析回填 / 调 HA 服务 / 失败话术 / X 分钟后执行 /
    每天 X 点建定时 / 定时误删保护 / 与音乐口令的优先级

规则文件写在临时目录，不会动你自己的 conf/。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xiaomusic.ha.client as ha_client  # noqa: E402
from xiaomusic.command_handler import HA_CONTROL_CMD, CommandHandler  # noqa: E402
from xiaomusic.ha import HABridge  # noqa: E402
from xiaomusic.ha.client import build_time_automation  # noqa: E402
from xiaomusic.ha.rules import (  # noqa: E402
    RuleError,
    compile_rule,
    compile_rules,
    parse_query,
)


# --------------------------------------------------------------------------
# 假的 aiohttp：按 (方法, 路径) 返回可编排的响应，并记录每个请求
# --------------------------------------------------------------------------
class ClientTimeout:
    def __init__(self, total=None, sock_read=None):
        self.total, self.sock_read = total, sock_read


class FakeResponse:
    def __init__(self, status, payload, text=None):
        self.status = status
        self._payload = payload
        self._text = (
            text if text is not None else json.dumps(payload, ensure_ascii=False)
        )

    async def json(self):
        return self._payload

    async def text(self):
        return self._text


class _Ctx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class FakeClientSession:
    routes: dict = {}
    log: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _emit(self, method, url, kwargs):
        path = urlparse(url).path
        entry = {
            "method": method,
            "path": path,
            "json": kwargs.get("json"),
            "headers": kwargs.get("headers"),
        }
        FakeClientSession.log.append(entry)
        status, payload = FakeClientSession.routes.get(
            (method, path), (404, {"message": "no route"})
        )
        return _Ctx(FakeResponse(status, payload))

    def get(self, url, **kwargs):
        return self._emit("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._emit("POST", url, kwargs)

    def delete(self, url, **kwargs):
        return self._emit("DELETE", url, kwargs)


class _FakeAiohttp:
    ClientTimeout = ClientTimeout
    ClientSession = FakeClientSession


# 只替换 client 模块里的那个引用，不污染真正的 aiohttp
ha_client.aiohttp = _FakeAiohttp

log = logging.getLogger("test_ha")
log.setLevel(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="xiaomusic_ha_test_")
AUTO_ID = "xiaomusic_ha_0700_light_living_room_turn_on"

# 顺序即优先级：具体规则（带定时）必须放在通用规则前面
RULES = [
    {
        "pattern": "每天{num}点开客厅灯",
        "action": {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.living_room",
            "type": "schedule",
            "schedule_time": "{0}:00",
            "schedule_days": "每天",
            "reply": "好的",
        },
    },
    {
        "pattern": "(打开|开)(客厅灯)",
        "action": {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.living_room",
            "reply": "好的，客厅灯已打开",
        },
    },
    {
        "pattern": "(关闭|关)(客厅空调)",
        "action": {
            "domain": "climate",
            "service": "turn_off",
            "entity_id": "climate.living_room_ac",
            "reply": "好的，客厅空调已关闭",
        },
    },
    {
        "pattern": "把客厅灯调到{num}[%％]",
        "action": {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.living_room",
            "brightness_pct": "{0}",
            "reply": "好的，亮度已调到 {0}",
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

_failures: list[str] = []


def check(cond, msg):
    print(("  OK   " if cond else " FAIL  ") + msg)
    if not cond:
        _failures.append(msg)


def make_bridge(enable=True, tts_reply=True):
    """造一个 HABridge，xiaomusic 用最小替身（只用到 config / log / do_tts）。"""
    cfg = SimpleNamespace(
        enable_ha=enable,
        ha_url="http://ha.local:8123",
        ha_token="tok",
        ha_tts_reply=tts_reply,
        conf_path=TMP,
    )
    xm = SimpleNamespace(config=cfg, log=log)
    xm.tts_calls = []

    async def do_tts(did, text):
        xm.tts_calls.append((did, text))

    xm.do_tts = do_tts
    return HABridge(xm), xm


def calls(path=None, prefix=None):
    return [
        e
        for e in FakeClientSession.log
        if (path is None or e["path"] == path)
        and (prefix is None or e["path"].startswith(prefix))
    ]


def default_routes():
    return {
        ("POST", "/api/services/light/turn_on"): (
            200,
            [{"entity_id": "light.living_room"}],
        ),
        ("POST", "/api/services/automation/reload"): (200, {}),
        ("POST", f"/api/config/automation/config/{AUTO_ID}"): (200, {}),
        ("DELETE", f"/api/config/automation/config/{AUTO_ID}"): (200, {}),
        ("GET", "/api/config"): (200, {"version": "2024.6.0", "location_name": "家"}),
        ("GET", "/api/states"): (
            200,
            [
                {
                    "entity_id": "light.living_room",
                    "state": "on",
                    "attributes": {"friendly_name": "客厅灯"},
                },
                {
                    "entity_id": f"automation.{AUTO_ID}",
                    "state": "on",
                    "attributes": {"friendly_name": "定时"},
                },
                {"entity_id": "switch.fan", "state": "off", "attributes": {}},
            ],
        ),
        ("GET", "/api/services"): (
            200,
            [
                {"domain": "light", "services": {"turn_on": {}, "turn_off": {}}},
                {"domain": "climate", "services": {"set_temperature": {}}},
            ],
        ),
    }


# --------------------------------------------------------------------------
# 命令链路用的替身
# --------------------------------------------------------------------------
class FakeDevice:
    def __init__(self):
        self.is_playing = True
        self._pending_selection = None
        self.force_stop_calls = 0
        self.replay_calls = 0

    async def group_force_stop_xiaoai(self):
        self.force_stop_calls += 1

    async def check_replay(self):
        self.replay_calls += 1


class FakeCfg:
    key_match_order = ["下一首", "关闭", "播放歌曲"]
    key_word_dict = {"下一首": "play_next", "关闭": "stop", "播放歌曲": "play"}

    def get_active_cmd_arr(self):
        return []

    def is_http_server_config(self, key):
        return False


async def main():
    print("=== [1] 规则校验 ===")
    bad_cases = [
        (
            {
                "pattern": "",
                "action": {
                    "domain": "light",
                    "service": "turn_on",
                    "entity_id": "light.x",
                },
            },
            "空 pattern",
        ),
        (
            {
                "pattern": "开灯",
                "action": {"service": "turn_on", "entity_id": "light.x"},
            },
            "缺 domain",
        ),
        (
            {"pattern": "开灯", "action": {"domain": "light", "service": "turn_on"}},
            "缺 entity_id",
        ),
        (
            {
                "pattern": "开(灯",
                "action": {
                    "domain": "light",
                    "service": "turn_on",
                    "entity_id": "light.x",
                },
            },
            "正则非法",
        ),
        (
            {
                "pattern": "每天开灯",
                "action": {
                    "domain": "light",
                    "service": "turn_on",
                    "entity_id": "light.x",
                    "type": "schedule",
                },
            },
            "定时缺 schedule_time",
        ),
    ]
    for rule, why in bad_cases:
        try:
            compile_rule(rule)
            check(False, f"{why} 应报错")
        except RuleError:
            check(True, f"{why} 会报错")

    compiled, errors = compile_rules(RULES)
    check(len(compiled) == 5 and not errors, f"5 条规则全部编译通过 errors={errors}")

    print("=== [2] 解析与回填 ===")
    parsed = parse_query(compiled, "把客厅灯调到60%")
    check(parsed is not None, "命中『把客厅灯调到60%』")
    check(parsed and parsed["action"]["brightness_pct"] == 60, "『{num}』转成 int 60")
    check(
        parsed and parsed["action"]["reply"] == "好的，亮度已调到 60", "reply 回填 {0}"
    )
    check(parse_query(compiled, "今天天气怎么样") is None, "无关语句不命中")
    check(
        parse_query(compiled, "打开客厅灯")["action"]["entity_id"]
        == "light.living_room",
        "多分组规则命中",
    )

    print("=== [3] 未启用时不介入 ===")
    bridge_off, _ = make_bridge(enable=False)
    check(bridge_off.can_handle("打开客厅灯") is False, "enable_ha=false 时恒为 False")

    print("=== [4] 调用 HA 服务 + TTS 回话 ===")
    FakeClientSession.routes = default_routes()
    FakeClientSession.log.clear()
    bridge, xm = make_bridge()
    ok, err = bridge.save_rules(RULES)
    check(ok is True, f"save_rules 落盘 err={err!r}")
    check(bridge.can_handle("打开客厅灯") is True, "can_handle 命中")
    check(bridge.can_handle("下一首") is False, "音乐口令不归 HA 管")

    FakeClientSession.log.clear()
    handled = await bridge.handle("d1", "打开客厅灯")
    turn_on = calls("/api/services/light/turn_on")
    check(handled is True, "handle 返回已处理")
    check(
        len(turn_on) == 1 and turn_on[0]["json"] == {"entity_id": "light.living_room"},
        f"服务实参正确: {turn_on[0]['json'] if turn_on else None}",
    )
    check(
        bool(turn_on) and turn_on[0]["headers"]["Authorization"] == "Bearer tok",
        "带 Bearer 令牌",
    )
    check(xm.tts_calls == [("d1", "好的，客厅灯已打开")], f"TTS 播报: {xm.tts_calls}")

    print("=== [5] 调用失败时的回话 ===")
    FakeClientSession.routes[("POST", "/api/services/light/turn_on")] = (
        400,
        {"message": "bad"},
    )
    xm.tts_calls.clear()
    await bridge.handle("d1", "打开客厅灯")
    check(
        bool(xm.tts_calls) and "失败" in xm.tts_calls[0][1], f"失败话术: {xm.tts_calls}"
    )
    check("400" in bridge.last_error, f"last_error 记录原因: {bridge.last_error}")

    print("=== [6] N 分钟后执行 ===")
    FakeClientSession.log.clear()
    xm.tts_calls.clear()
    await bridge.handle("d1", "客厅空调30分钟后关闭")
    check(
        xm.tts_calls == [("d1", "好的，30 分钟后关闭客厅空调")],
        f"先回话: {xm.tts_calls}",
    )
    check(bridge.status()["pending_delays"] == 1, "挂了一个待执行任务")
    check(not calls(prefix="/api/services/climate"), "尚未调用 climate（要等到点）")
    await bridge._delayed_call(
        "climate", "turn_off", {"entity_id": "climate.living_room_ac"}, 0
    )
    check(
        bool(calls("/api/services/climate/turn_off")),
        "到点后真的调用了 climate.turn_off",
    )
    await bridge.cancel_delays()
    check(bridge.status()["pending_delays"] == 0, "cancel_delays 清空待执行任务")

    print("=== [7] 每天 X 点 → 在 HA 建定时 ===")
    FakeClientSession.log.clear()
    xm.tts_calls.clear()
    await bridge.handle("d1", "每天7点开客厅灯")
    created = calls(prefix="/api/config/automation/config/")
    check(len(created) == 1, f"创建了 1 个自动化（实际 {len(created)}）")
    check(
        bool(created) and created[0]["path"].endswith(AUTO_ID),
        f"自动化 id: {created[0]['path'] if created else None}",
    )
    conf = created[0]["json"] if created else {}
    check(
        conf.get("trigger") == [{"platform": "time", "at": "07:00:00"}],
        f"触发器: {conf.get('trigger')}",
    )
    check(
        conf.get("action")
        == [{"service": "light.turn_on", "target": {"entity_id": "light.living_room"}}],
        f"动作: {conf.get('action')}",
    )
    check(bool(calls("/api/services/automation/reload")), "调用了 automation.reload")
    check(
        bool(xm.tts_calls)
        and "已创建定时任务" in xm.tts_calls[0][1]
        and "7:00" in xm.tts_calls[0][1],
        f"回话含时间: {xm.tts_calls}",
    )

    print("=== [8] 定时 id 唯一性 / 分支 ===")
    id_on, _ = build_time_automation(
        "light", "turn_on", {"entity_id": "light.living_room"}, "7:00", "每天"
    )
    id_off, _ = build_time_automation(
        "light", "turn_off", {"entity_id": "light.living_room"}, "7:00", "每天"
    )
    id_pad, _ = build_time_automation(
        "light", "turn_on", {"entity_id": "light.living_room"}, "07:00", "每天"
    )
    check(id_on != id_off, f"同刻同实体、不同操作不冲突: {id_on} vs {id_off}")
    check(id_on == id_pad, f"7:00 与 07:00 归一化到同一 id: {id_on}")
    _, workday = build_time_automation(
        "light", "turn_on", {"entity_id": "light.x"}, "7:30", "工作日"
    )
    check(
        workday["condition"]
        == [{"condition": "time", "weekday": ["mon", "tue", "wed", "thu", "fri"]}],
        "工作日条件",
    )
    _, weekend = build_time_automation(
        "climate",
        "set_temperature",
        {"entity_id": "climate.a", "temperature": 26},
        "22:00",
        "周六,周日",
    )
    check(
        weekend["condition"] == [{"condition": "time", "weekday": ["sat", "sun"]}]
        and weekend["action"][0]["data"] == {"temperature": 26},
        "周末 + 附加参数",
    )
    check(
        build_time_automation("light", "turn_on", {"entity_id": "light.x"}, "25点", "")
        == (None, None),
        "非法时间返回 None",
    )

    print("=== [9] 整体校验 / 热更新 / 状态 ===")
    ok2, err2 = bridge.save_rules(
        [{"pattern": "开灯", "action": {"domain": "light", "service": "turn_on"}}]
    )
    check(ok2 is False and "entity_id" in err2, f"非法规则整表拒绝: {err2}")

    rules_path = os.path.join(TMP, "ha_rules.json")
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "rules": [RULES[0]]}, f, ensure_ascii=False)
    os.utime(rules_path, (0, 0))
    bridge._last_check = 0.0
    bridge.refresh_if_changed()
    check(bridge.status()["rules_count"] == 1, "手工改文件后热更新生效")
    check(
        bridge.get_rules()[0]["pattern"] == RULES[0]["pattern"],
        "get_rules 返回原始规则",
    )
    status = bridge.status()
    check(status["enabled"] and status["configured"], "status 显示已启用且已配置")
    check(status["command_count"] >= 4, f"命中计数: {status['command_count']}")

    print("=== [10] HA 侧查询 / 定时误删保护 ===")
    okc, msg = await bridge.test_connection()
    check(okc and "2024.6.0" in msg, f"测试连接: {msg}")
    entities, _ = await bridge.list_entities()
    check(len(entities) == 3, f"实体列表 {len(entities)} 条")
    services, _ = await bridge.list_services()
    check(services.get("light") == ["turn_off", "turn_on"], f"服务列表: {services}")
    automations, _ = await bridge.list_automations()
    check(len(automations) == 1, "只列出自己创建的定时")
    check(
        (await bridge.delete_automation(f"automation.{AUTO_ID}"))[0] is True,
        "传 entity_id 能删",
    )
    check((await bridge.delete_automation(AUTO_ID))[0] is True, "传裸 id 也能删")
    rejected = await bridge.delete_automation("automation.my_own_one")
    check(
        rejected[0] is False and "只允许" in rejected[1],
        f"拒绝删别人的自动化: {rejected}",
    )

    print("=== [11] 与音乐口令的优先级 ===")
    FakeClientSession.routes = default_routes()
    FakeClientSession.log.clear()
    bridge2, _ = make_bridge()
    bridge2.save_rules(RULES)
    fake_xm = SimpleNamespace(config=FakeCfg(), log=log, ha_bridge=bridge2)
    fake_xm.device_manager = SimpleNamespace(devices={})
    handler = CommandHandler(FakeCfg(), log, fake_xm)
    dev = FakeDevice()

    op, arg = handler.match_cmd(dev, "关闭客厅空调", True)
    check(
        (op, arg) == (HA_CONTROL_CMD, "关闭客厅空调"),
        f"HA 规则抢在模糊关键词『关闭』之前: {(op, arg)}",
    )
    op, arg = handler.match_cmd(dev, "关闭", True)
    check((op, arg) == ("stop", ""), f"只喊『关闭』仍是停止播放: {(op, arg)}")
    op, arg = handler.match_cmd(dev, "下一首", True)
    check(op == "play_next", f"普通音乐口令不受影响: {(op, arg)}")
    op, arg = handler.match_cmd(dev, "打开客厅灯", True)
    check(op == HA_CONTROL_CMD, f"HA 开灯命中: {(op, arg)}")

    bridge3, _ = make_bridge(enable=False)
    fake_xm3 = SimpleNamespace(config=FakeCfg(), log=log, ha_bridge=bridge3)
    fake_xm3.device_manager = SimpleNamespace(devices={})
    handler3 = CommandHandler(FakeCfg(), log, fake_xm3)
    op, arg = handler3.match_cmd(FakeDevice(), "关闭客厅空调", True)
    check(
        (op, arg) == ("stop", "客厅空调"),
        f"关闭 HA 后回到原行为（降级安全）: {(op, arg)}",
    )

    print("=== [12] do_check_cmd：HA 指令不停音乐 ===")
    executed = []

    async def ha_control(did="", arg1="", **kwargs):
        executed.append(("ha_control", did, arg1))

    async def stop(did="", arg1="", **kwargs):
        executed.append(("stop", did, arg1))

    fake_xm.ha_control = ha_control
    fake_xm.stop = stop
    dev4 = FakeDevice()
    fake_xm.device_manager = SimpleNamespace(devices={"d1": dev4})
    await handler.do_check_cmd("d1", "关闭客厅空调", True)
    check(
        dev4.force_stop_calls == 0 and executed and executed[-1][0] == "ha_control",
        f"HA 指令未停播且已执行 force_stop={dev4.force_stop_calls}",
    )
    await handler.do_check_cmd("d1", "关闭", True)
    check(
        dev4.force_stop_calls == 1 and executed[-1][0] == "stop",
        f"音乐口令仍先停播 force_stop={dev4.force_stop_calls}",
    )

    print()
    if _failures:
        print(f"RESULT: {len(_failures)} FAILED")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
