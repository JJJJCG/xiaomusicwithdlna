"""命令处理模块

负责语音指令的解析、匹配和路由。
"""

import asyncio
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xiaomusic.xiaomusic import XiaoMusic
from xiaomusic.config import KEY_WORD_ARG_BEFORE_DICT

if TYPE_CHECKING:
    pass

# HA 指令用的伪命令名：xiaomusic 上真正执行它的是 XiaoMusic.ha_control
HA_CONTROL_CMD = "ha_control"


class CommandHandler:
    """命令处理器

    负责解析用户的语音指令，匹配对应的命令，并路由到相应的处理方法。
    """

    def __init__(self, config, log, xiaomusic_instance: "XiaoMusic"):
        """初始化命令处理器

        Args:
            config: 配置对象
            log: 日志对象
            xiaomusic_instance: XiaoMusic 主类实例，用于调用命令执行方法
        """
        self.config = config
        self.log = log
        self.xiaomusic = xiaomusic_instance
        self.last_cmd = ""

    async def do_check_cmd(self, did="", query="", ctrl_panel=True, **kwargs):
        """检查并执行命令
        这是命令处理的入口方法，负责：
        1. 记录命令
        2. 匹配命令
        3. 执行对应的方法
        4. 处理未匹配的情况

        Args:
            did: 设备ID
            query: 用户查询/命令
            ctrl_panel: 是否来自控制面板
            **kwargs: 其他参数
        """
        self.log.info(f"收到消息:{query} 控制面板:{ctrl_panel} did:{did}")

        # 记录最后一条命令
        self.last_cmd = query

        try:
            device = self.xiaomusic.device_manager.devices[did]
            # 匹配命令
            opvalue, oparg = self.match_cmd(device, query, ctrl_panel)
            if not opvalue:
                # 未匹配到命令，等待后检查是否需要重播
                await asyncio.sleep(1)
                await device.check_replay()
                return

            # 执行命令前先停止小爱，避免播放"不支持"提示。
            # HA 指令例外：它是去控制家里的设备，只插播一句反馈，
            # 停播/恢复交给 do_tts（播完会走 check_replay 续播）。
            if opvalue != HA_CONTROL_CMD:
                await device.group_force_stop_xiaoai()

            # 执行命令
            func = getattr(self.xiaomusic, opvalue)
            await func(did=did, arg1=oparg)

        except Exception as e:
            self.log.exception(f"Execption {e}")

    def match_cmd(self, device, query, ctrl_panel):
        """匹配命令

        根据用户输入的查询字符串，匹配对应的命令和参数。

        匹配策略：
        1. 优先完全匹配
        2. 然后按配置的优先级顺序进行模糊匹配
        3. 检查是否在激活命令列表中

        Args:
            device: 设备
            query: 用户查询字符串
            ctrl_panel: 是否来自控制面板

        Returns:
            tuple: (命令值, 命令参数)，未匹配返回 (None, None)
        """
        # 检查是否有待选择的歌曲
        if device._pending_selection:
            patternarg = r"^第?([零一二三四五六七八九十百千万亿]+)[个首条集]$"
            matcharg = re.match(patternarg, query)
            if matcharg:
                self.log.info(f"匹配到选择指令. query:{query}")
                return "select_index", query

        # 优先处理完全匹配
        opvalue = self.check_full_match_cmd(device, query, ctrl_panel)
        if opvalue:
            self.log.info(f"完全匹配指令. query:{query} opvalue:{opvalue}")
            # 自定义口令
            if opvalue.startswith("exec#"):
                code = opvalue.split("#", 1)[1]
                return "exec", code
            return opvalue, ""

        # Home Assistant 规则优先于"模糊关键词"匹配。
        # xiaomusic 的模糊匹配形如 (.*)关闭(.*)，会把"关闭客厅空调"当成停止播放，
        # 所以带"关闭/播放"字样的 HA 指令必须在这里先被拦下；
        # 而上面那段完全匹配（只喊"关闭"两个字）仍然优先，音乐口令不会被抢走。
        if self._match_ha_cmd(query):
            self.log.info(f"匹配到 Home Assistant 指令. query:{query}")
            return HA_CONTROL_CMD, query

        # 按优先级顺序进行模糊匹配
        for opkey in self.config.key_match_order:
            patternarg = rf"(.*){opkey}(.*)"
            # 匹配参数
            matcharg = re.match(patternarg, query)
            if not matcharg:
                continue

            argpre = matcharg.groups()[0]
            argafter = matcharg.groups()[1]
            self.log.debug(
                "matcharg. opkey:%s, argpre:%s, argafter:%s",
                opkey,
                argpre,
                argafter,
            )

            # 根据配置决定参数位置
            oparg = argafter
            if opkey in KEY_WORD_ARG_BEFORE_DICT:
                oparg = argpre

            opvalue = self.config.key_word_dict.get(opkey)

            # 检查是否在激活命令中
            active_cmd_arr = self.config.get_active_cmd_arr()
            if (
                not ctrl_panel
                and not device.is_playing
                and active_cmd_arr
                and opvalue not in active_cmd_arr
                and opkey not in active_cmd_arr
            ):
                self.log.info(f"不在激活命令中 {opvalue}")
                continue

            self.log.info(f"匹配到指令. opkey:{opkey} opvalue:{opvalue} oparg:{oparg}")

            # 自定义口令
            if opvalue.startswith("exec#"):
                code = opvalue.split("#", 1)[1]
                return "exec", code
            return opvalue, oparg

        self.log.info(f"未匹配到指令 {query} {ctrl_panel}")
        return None, None

    def _match_ha_cmd(self, query):
        """这句话是否命中 Home Assistant 规则。

        HA 未启用 / 未配置 / 规则文件异常时恒为 False，绝不影响音乐指令。
        """
        bridge = getattr(self.xiaomusic, "ha_bridge", None)
        if bridge is None:
            return False
        try:
            return bridge.can_handle(query)
        except Exception as e:
            self.log.warning(f"HA 规则匹配异常: {e}")
            return False

    def check_full_match_cmd(self, device, query, ctrl_panel):
        """检查是否完全匹配命令

        检查查询字符串是否与配置的命令关键词完全一致。

        Args:
            device: 设备
            query: 用户查询字符串
            ctrl_panel: 是否来自控制面板

        Returns:
            str: 匹配的命令值，未匹配返回 None
        """
        if query not in self.config.key_match_order:
            return None

        active_cmd_arr = self.config.get_active_cmd_arr()
        opvalue = self.config.key_word_dict.get(query)
        # 控制面板/正在播放时允许执行/是否在激活命令中
        if (
            ctrl_panel
            or device.is_playing
            or not active_cmd_arr
            or opvalue in active_cmd_arr
        ):
            return opvalue
