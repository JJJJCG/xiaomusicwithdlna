"""Home Assistant 接入路由

给 /static/ha.html 编辑页和外部脚本用：
    GET    /api/ha/status                 运行状态
    GET    /api/ha/rules                  读取规则
    PUT    /api/ha/rules                  整表保存规则
    POST   /api/ha/rules/test             只解析一句话（不执行）
    POST   /api/ha/test                   测试 HA 连接
    POST   /api/ha/setting                保存 HA 配置（地址/令牌/开关）
    GET    /api/ha/entities               拉取 HA 实体列表（下拉用）
    GET    /api/ha/services               拉取 HA 服务列表（下拉用）
    GET    /api/ha/automations            列出本程序创建的定时任务
    DELETE /api/ha/automations/{id}       删除定时任务
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request

from xiaomusic.api.dependencies import (
    log,
    verification,
    xiaomusic,
)
from xiaomusic.utils.system_utils import restore_sensitive_placeholders

router = APIRouter(dependencies=[Depends(verification)])

# 允许通过本路由修改的配置项（其余字段一律忽略，避免误改）
_SETTING_KEYS = ("enable_ha", "ha_url", "ha_token", "ha_tts_reply")


async def _read_json(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")
    return data


@router.get("/api/ha/status")
async def ha_status():
    """HA 桥接运行状态"""
    return xiaomusic.ha_bridge.status()


@router.get("/api/ha/rules")
async def ha_get_rules():
    """读取全部规则"""
    bridge = xiaomusic.ha_bridge
    return {"rules": bridge.get_rules(), "path": bridge.rules_path}


@router.put("/api/ha/rules")
async def ha_save_rules(request: Request):
    """整表保存规则（全部校验通过才落盘）"""
    data = await _read_json(request)
    rules = data.get("rules")
    ok, err = xiaomusic.ha_bridge.save_rules(rules)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    log.info(f"[HA] 规则已保存，共 {len(rules)} 条")
    return {"success": True, "count": len(rules)}


@router.post("/api/ha/rules/test")
async def ha_test_rule(request: Request):
    """试解析一句话：返回命中的规则与将要发给 HA 的参数"""
    data = await _read_json(request)
    text = str(data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    parsed = xiaomusic.ha_bridge.test_rule(text)
    return {"matched": parsed is not None, "result": parsed}


@router.post("/api/ha/test")
async def ha_test_connection():
    """测试 HA 连接"""
    ok, message = await xiaomusic.ha_bridge.test_connection()
    return {"success": ok, "message": message}


@router.post("/api/ha/setting")
async def ha_save_setting(request: Request):
    """保存 HA 配置（只接受 HA 相关字段）"""
    data = await _read_json(request)
    config_obj = xiaomusic.getconfig()

    payload = {key: data[key] for key in _SETTING_KEYS if key in data}
    # 令牌用 ****** 占位表示"不修改"：与 /savesetting 共用同一份还原逻辑，
    # 空串仍按"清空令牌"处理（keep_on_empty=False）
    restore_sensitive_placeholders(
        payload, config_obj, fields=("ha_token",), keep_on_empty=False
    )

    if not payload:
        return {"success": True, "message": "没有需要更新的字段", "updated": []}

    if (
        "ha_url" in payload
        and payload["ha_url"]
        and not str(payload["ha_url"]).startswith(("http://", "https://"))
    ):
        payload["ha_url"] = f"http://{payload['ha_url']}"
    if "ha_token" in payload:
        payload["ha_token"] = str(payload["ha_token"] or "").strip()

    try:
        xiaomusic.update_config_from_setting(payload)
        xiaomusic.save_cur_config()
    except Exception as err:
        log.exception(f"[HA] 保存配置失败: {err}")
        raise HTTPException(status_code=500, detail=str(err)) from err

    log.info(f"[HA] 配置已更新: {list(payload.keys())}")
    return {
        "success": True,
        "updated": list(payload.keys()),
        "enabled": bool(getattr(config_obj, "enable_ha", False)),
    }


@router.get("/api/ha/entities")
async def ha_entities():
    """拉取 HA 实体列表"""
    items, err = await xiaomusic.ha_bridge.list_entities()
    if err:
        raise HTTPException(status_code=502, detail=err)
    return {"entities": items, "count": len(items)}


@router.get("/api/ha/services")
async def ha_services():
    """拉取 HA 服务列表（前端按 domain 过滤）"""
    services, err = await xiaomusic.ha_bridge.list_services()
    if err:
        raise HTTPException(status_code=502, detail=err)
    return {"services": services, "count": len(services)}


@router.get("/api/ha/automations")
async def ha_automations():
    """列出由本程序创建的定时任务"""
    items, err = await xiaomusic.ha_bridge.list_automations()
    if err:
        raise HTTPException(status_code=502, detail=err)
    return {"automations": items, "count": len(items)}


@router.delete("/api/ha/automations/{automation_id}")
async def ha_delete_automation(automation_id: str):
    """删除定时任务（仅限本程序创建的）"""
    ok, err = await xiaomusic.ha_bridge.delete_automation(automation_id)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"success": True}
