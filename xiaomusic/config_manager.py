"""配置管理模块

负责配置的加载、保存、更新和管理。
"""

import json
from dataclasses import asdict


class ConfigManager:
    """配置管理类

    负责管理应用配置，包括：
    - 从文件加载配置
    - 保存配置到文件
    - 更新配置
    - 配置变更通知
    """

    # 一次性迁移：仅当存量配置的值"恰好等于旧默认值"时才升级为新默认值，
    # 用户自定义过的值不受影响。
    _KEYWORD_MIGRATIONS = {
        "keywords_playlocal": (
            "播放本地歌曲,本地播放歌曲",
            "播放本地歌曲,本地播放歌曲,播放本地音乐",
        ),
    }

    def __init__(self, config, log):
        """初始化配置管理器

        Args:
            config: 配置对象
            log: 日志对象
        """
        self.config = config
        self.log = log

    def try_init_setting(self):
        """尝试从设置文件加载配置

        从配置文件中读取设置并更新当前配置。
        如果文件不存在或格式错误，会记录日志但不会抛出异常。
        """
        try:
            filename = self.config.getsettingfile()
            with open(filename, encoding="utf-8") as f:
                data = json.loads(f.read())
                return data
        except FileNotFoundError:
            self.log.info(f"The file {filename} does not exist.")
            return None
        except json.JSONDecodeError:
            self.log.warning(f"The file {filename} contains invalid JSON.")
            return None
        except Exception as e:
            self.log.exception(f"Execption {e}")
            return None

    def do_saveconfig(self, data):
        """配置文件落地

        将配置数据写入文件。

        Args:
            data: 要保存的配置数据（字典格式）
        """
        filename = self.config.getsettingfile()
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.log.info(f"Configuration saved to {filename}")

    def save_cur_config(self, devices):
        """把当前配置落地

        将当前运行时的配置保存到文件。
        会同步设备配置到 config 对象中。

        Args:
            devices: 设备字典 {did: XiaoMusicDevice}
        """
        # 同步设备配置
        for did in self.config.devices.keys():
            deviceobj = devices.get(did)
            if deviceobj is not None:
                self.config.devices[did] = deviceobj.device

        # 转换为字典并保存
        data = asdict(self.config)
        self.do_saveconfig(data)
        self.log.info("save_cur_config ok")

    def update_config(self, data):
        """更新配置

        从字典数据更新配置对象。

        Args:
            data: 配置数据字典
        """
        # 存量配置的口令关键词一次性迁移（仅限恰好等于旧默认值的场景）
        for key, (legacy, upgraded) in self._KEYWORD_MIGRATIONS.items():
            if data.get(key) == legacy:
                data[key] = upgraded
                self.log.info(f"配置迁移: {key} 已升级为 {upgraded!r}")
        # 自动赋值相同字段的配置
        self.config.update_config(data)

    def get_config(self):
        """获取当前配置

        Returns:
            Config: 当前配置对象
        """
        return self.config

    def get_setting_filename(self):
        """获取配置文件路径

        Returns:
            str: 配置文件的完整路径
        """
        return self.config.getsettingfile()
