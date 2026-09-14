# XiaoMusic: 无限听歌，解放小爱音箱

> [!IMPORTANT]
> **📢 项目停止维护通知**
>
> 因个人精力有限，需将重心转移到其他项目，本项目将停止维护，不再接受新功能开发与 bug 修复，已有 issue 与 PR 也不再处理。
>
> 后续推荐使用社区接力项目：**[songloft-org/songloft](https://github.com/songloft-org/songloft)**，欢迎大家迁移、参与共建。
>
> 衷心感谢一路以来所有用户的支持与陪伴 ❤️

[![GitHub License](https://img.shields.io/github/license/JJJJCG/xiaomusicwithdlna)](LICENSE)
[![Docker Image](https://img.shields.io/badge/ghcr.io-xiaomusicwithdlna-blue?logo=docker)](https://github.com/JJJJCG/xiaomusicwithdlna/pkgs/container/xiaomusicwithdlna)
[![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fhanxi%2Fxiaomusic%2Fmain%2Fpyproject.toml)](https://pypi.org/project/xiaomusic/)
[![GitHub Release](https://img.shields.io/github/v/release/hanxi/xiaomusic)](https://github.com/hanxi/xiaomusic/releases)
[![Visitors](https://api.visitorbadge.io/api/daily?path=hanxi%2Fxiaomusic&label=daily%20visitor&countColor=%232ccce4&style=flat)](https://visitorbadge.io/status?path=hanxi%2Fxiaomusic)
[![Visitors](https://api.visitorbadge.io/api/visitors?path=hanxi%2Fxiaomusic&label=total%20visitor&countColor=%232ccce4&style=flat)](https://visitorbadge.io/status?path=hanxi%2Fxiaomusic)

---

<p align="center">
  <strong>🎵 使用小爱音箱播放音乐，音乐使用 yt-dlp 下载</strong>
</p>

<p align="center">
  <a href="https://github.com/hanxi/xiaomusic">🏠 GitHub</a> •
  <a href="https://xdocs.hanxi.cc/">📖 文档</a> •
  <a href="https://github.com/hanxi/xiaomusic/issues/99">💬 FAQ</a> •
  <a href="#-讨论区">💭 讨论区</a>
</p>

---

> [!TIP]
> **新手指南**：初次安装遇到问题请查阅 [💬 FAQ问题集合](https://github.com/hanxi/xiaomusic/issues/99)，一般遇到的问题都已经有解决办法。

## 👋 快速入门指南

已经支持在 web 设置页面配置其他参数，不再需要设置环境变量， docker compose 配置如下（选一个即可）：

```yaml
services:
  xiaomusic:
    image: hanxi/xiaomusic
    container_name: xiaomusic
    restart: always
    ports:
      - 58090:8090
    volumes:
      - /xiaomusic_music:/app/music
      - /xiaomusic_conf:/app/conf
```

🔥 国内：

```yaml
services:
  xiaomusic:
    image: docker.hanxi.cc/hanxi/xiaomusic
    container_name: xiaomusic
    restart: always
    ports:
      - 58090:8090
    volumes:
      - /xiaomusic_music:/app/music
      - /xiaomusic_conf:/app/conf
```

测试版：

```yaml
services:
  xiaomusic:
    image: hanxi/xiaomusic:main
    container_name: xiaomusic
    restart: always
    ports:
      - 58090:8090
    volumes:
      - /xiaomusic_music:/app/music
      - /xiaomusic_conf:/app/conf
```

对应的 docker 启动命令如下:

```bash
docker run -p 58090:8090 -v /xiaomusic_music:/app/music -v /xiaomusic_conf:/app/conf hanxi/xiaomusic
```

🔥 国内：

```bash
docker run -p 58090:8090 -v /xiaomusic_music:/app/music -v /xiaomusic_conf:/app/conf docker.hanxi.cc/hanxi/xiaomusic
```

测试版：

```
docker run -p 58090:8090 -v /xiaomusic_music:/app/music -v /xiaomusic_conf:/app/conf hanxi/xiaomusic:main
```

- 其中 conf 目录为配置文件存放目录，music 目录为音乐存放目录，建议分开配置为不同的目录。
- /xiaomusic_music 和 /xiaomusic_conf 是 docker 所在的主机的目录，可以修改为其他目录。如果报错找不到 /xiaomusic_music 目录，可以先执行 `mkdir -p /xiaomusic_{music,conf}` 命令新建目录。
- /app/music 和 /app/conf 是 docker 容器里的目录，不要去修改。
- 58090 是 NAS 本地端口的。8090 是容器端口，不要去修改。
- 后台访问地址为： http://NAS_IP:58090

> [!NOTE]
> docker 和 docker compose 二选一即可，启动成功后，在 web 页面可以配置其他参数，带有 `*` 号的配置是必须要配置的，其他的用不上时不用修改。初次配置时需要在页面上输入小米账号和密码保存后才能获取到设备列表。

遇到问题可以去 web 设置页面底部点击【下载日志文件】按钮，然后搜索一下日志文件内容确保里面没有账号密码信息后(有就删除这些敏感信息)，然后在提 issues 反馈问题时把下载的日志文件带上。

> [!TIP]
> 作者新写了一个更简洁的个人音乐服务器，支持更强的插件扩展 <https://github.com/mimusic-org/mimusic>

> [!TIP]
> - 适用于 NAS 上安装的开源工具： <https://github.com/hanxi/tiny-nav>
> - 适用于 NAS 上安装的网页打印机： <https://github.com/hanxi/cups-web>
> - PVE 移动端 UI 界面：<https://github.com/hanxi/pve-touch>
> - 喜欢听书的可以配合这个工具使用 <https://github.com/hanxi/epub2mp3>

> [!TIP]
>
> - 🔥【广告:可用于安装 frp 实现内网穿透】
> - 🔥 海外 RackNerd VPS 机器推荐，可支付宝付款。
> - <a href="https://my.racknerd.com/aff.php?aff=11177"><img src="https://racknerd.com/banners/320x50.gif" alt="RackNerd Mobile Leaderboard Banner" width="320" height="50"></a>
> - 不知道选哪个套餐可以直接买这个最便宜的 <https://my.racknerd.com/aff.php?aff=11177&pid=923>
> - 也可以用来部署代理，docker 部署方法见 <https://github.com/hanxi/blog/issues/96>

> [!TIP]
>
> - 🔥【广告: 搭建您的专属大模型主页
告别繁琐配置难题，一键即可畅享稳定流畅的AI体验！】<https://university.aliyun.com/mobile?userCode=szqvatm6>

> [!TIP]
> - 免费主机
> - <a href="https://dartnode.com?aff=SnappyPigeon570"><img src="https://dartnode.com/branding/DN-Open-Source-sm.png" alt="Powered by DartNode - Free VPS for Open Source" width="320"></a>


## 🎤 功能特性

### 🤐 支持语音口令

#### 基础播放控制
- **播放歌曲** - 播放本地的歌曲
- **播放歌曲+歌名** - 例如：播放歌曲周杰伦晴天
- **上一首** / **下一首** - 切换歌曲
- **关机** / **停止播放** - 停止播放

#### 播放模式
- **单曲循环** - 重复播放当前歌曲
- **全部循环** - 循环播放所有歌曲
- **随机播放** - 随机顺序播放

#### 歌单管理
- **播放歌单+目录名** - 例如：播放歌单其他
- **播放歌单第几个+列表名** - 详见 [#158](https://github.com/hanxi/xiaomusic/issues/158)
- **播放歌单收藏** - 播放收藏歌单

#### 收藏功能
- **加入收藏** - 将当前播放的歌曲加入收藏歌单
- **取消收藏** - 将当前播放的歌曲从收藏歌单移除

> [!TIP]
> **隐藏玩法**：对小爱同学说"播放歌曲小猪佩奇的故事"，会先下载小猪佩奇的故事，然后再播放。

### 🏠 接入 Home Assistant

把小爱音箱变成 HA 的语音入口：说一句中文口令 → 调用 HA 服务 → 小爱语音回话。
登录、对话轮询、TTS 都复用本项目既有链路，只多了一遍"口语 → HA 服务调用"的映射。

**配置**（`conf/setting.json`，或用环境变量）：

```json
{
  "enable_ha": true,
  "ha_url": "http://homeassistant.local:8123",
  "ha_token": "在 HA 里 用户资料 → 长期访问令牌 生成",
  "ha_tts_reply": true
}
```

环境变量依次为 `XIAOMUSIC_ENABLE_HA` / `XIAOMUSIC_HA_URL` / `XIAOMUSIC_HA_TOKEN` / `XIAOMUSIC_HA_TTS_REPLY`。

**规则编辑页**：启动后打开 `http://<host>:<port>/static/ha.html`
（可测试连接、拉取实体与服务、增删改规则、试解析、导入导出、管理定时任务）。
规则存在 `conf/ha_rules.json`，改这个文件会在下次语音时自动热更新。

**规则示例**：

```json
[
  {
    "pattern": "每天{num}点开客厅灯",
    "action": {
      "domain": "light", "service": "turn_on",
      "entity_id": "light.living_room",
      "type": "schedule", "schedule_time": "{0}:00", "schedule_days": "每天",
      "reply": "好的"
    }
  },
  {
    "pattern": "(打开|开)(客厅灯)",
    "action": { "domain": "light", "service": "turn_on",
                "entity_id": "light.living_room", "reply": "好的，客厅灯已打开" }
  },
  {
    "pattern": "把客厅灯调到{num}[%％]",
    "action": { "domain": "light", "service": "turn_on",
                "entity_id": "light.living_room", "brightness_pct": "{0}",
                "reply": "好的，亮度已调到 {0}" }
  },
  {
    "pattern": "客厅空调{num}分钟后关闭",
    "action": { "domain": "climate", "service": "turn_off",
                "entity_id": "climate.living_room_ac", "delay_minutes": "{0}",
                "reply": "好的，{0} 分钟后关闭客厅空调" }
  }
]
```

- `pattern` 是正则，`{num}` 代表数字（捕获后可用 `{0}` 回填到任意字段）；`reply` 支持回填。
- `action` 除 `domain`/`service`/`entity_id` 外，其余键（如 `brightness_pct`、`temperature`）
  会原样作为服务的 `data` 发给 HA。
- 特例字段：`reply` 走 TTS、`delay_minutes` 到点后才执行、`type: "schedule"` 会在 HA 里
  创建一条定时自动化（`schedule_time` 必填，`schedule_days` 支持 `每天` / `工作日` / `周一,周三` 等）。
- **顺序即优先级**：规则先匹配先命中，所以"每天 X 点…"这类具体规则要放在通用规则**前面**。

**优先级**：完全匹配的音乐口令（如只喊"关闭"）→ HA 规则 → 音乐口令的关键词模糊匹配。
所以"关闭客厅空调"会走 HA，而"关闭"仍然是停止播放；`enable_ha=false` 时行为与原来完全一致。

**HTTP 接口**：`/api/ha/status`、`/api/ha/rules`(GET/PUT)、`/api/ha/rules/test`、
`/api/ha/test`、`/api/ha/setting`、`/api/ha/entities`、`/api/ha/services`、
`/api/ha/automations`、`DELETE /api/ha/automations/{id}`。

> [!NOTE]
> 定时任务由本程序在 HA 里创建，id 以 `xiaomusic_ha_` 开头；删除接口只允许删这个前缀的任务，
> 不会误删你自己写的自动化。

## 📦 安装方式

### 方式一：Docker Compose（推荐）

详见 [👋 快速入门指南](#-快速入门指南)

### 方式二：Pip 安装

```shell
# 安装
pip install -U xiaomusic

# 查看帮助
xiaomusic --help

# 启动（使用配置文件）
xiaomusic --config config.json

# 启动（使用默认端口 8090）
xiaomusic
```

> [!NOTE]
> `config.json` 文件可以参考 `config-example.json` 文件配置。详见 [#94](https://github.com/hanxi/xiaomusic/issues/94)

## 👨‍💻 开发指南

### 🔩 开发环境运行

1. **下载依赖**
   ```shell
   ./install_dependencies.sh
   ```

2. **安装环境**
   ```shell
   pdm install
   ```

3. **启动服务**
   ```shell
   pdm run xiaomusic.py
   ```
   默认监听端口 8090，使用其他端口请自行修改。

4. **查看 API 文档**
   
   访问 <http://localhost:8090/docs> 查看接口文档。

> [!NOTE]
> 目前的 web 控制台非常简陋，欢迎有兴趣的朋友帮忙实现一个漂亮的前端，需要什么接口可以随时提需求。

### 🚦 代码提交规范

提交前请执行以下命令检查代码和格式化代码：

```shell
pdm lintfmt
```

### 🐳 本地编译 Docker Image

```shell
docker build -t xiaomusic .
```

### 🛠️ 技术栈

- **后端**：Python + FastAPI 框架
- **容器化**：Docker
- **前端**：jQuery

### 🧩 分层与"唯一实现"约定

本项目由三家代码合并而成（XiaoMusic 主体 / MiAir Next 的 `cast/` / xiaoai-ha-bridge 的 `ha/`），
同一件事历史上被实现过两三次（严格程度还不一致），已经踩过坑。改代码前请先看这张表，
**新功能请复用下表的唯一实现，不要再写第二份**：

| 一件事 | 唯一实现 | 谁在复用 |
|---|---|---|
| 走哪个播放 API（continue_play / music_api / url） | `device_player.resolve_play_api()` | 本地播放、`cast/speaker_adapter` |
| 读播放状态并解析 `info` | `utils/device_utils.fetch_player_info()` | `device_player.get_volume/get_player_status`（失败回退 0）、`SpeakerController.get_status`（失败抛出） |
| 搜小米曲库换 audioID | `utils/device_utils.search_audio_id()` | `device_player._get_audio_id`（未命中回退默认值）、`SpeakerController.search_audio_id`（未命中返回空串） |
| `"歌名-歌手"` 拆分 | `utils/device_utils.split_song_artist()` | `device_player` |
| 本机局域网 IP | `utils/network_utils.detect_local_ip()` | DLNA 广告、AirPlay mDNS、AirPlay server（三处必须同一 IP，否则"设备可见但连接失败"） |
| 敏感字段脱敏 / 还原 | `utils/system_utils.SENSITIVE_FIELDS` / `restore_sensitive_placeholders()` | `getsetting`、`savesetting`、`modifiysetting`、`/api/ha/setting` |
| 批量音乐信息 | `api/routers/music._build_music_infos()` | `GET /musicinfos`、`POST /musicinfos` |
| 下载/代理推流核心 | `api/routers/file._proxy_handler()` | `/proxy`、`/proxy/{type}` |

**注意**：`fetch_player_info` 与 `search_audio_id` 只负责"怎么做"，
**失败语义由调用方决定**（本地侧吞异常回退、投送侧必须抛出）——这是有意为之，
不要为了"统一"把两边改成一样，DLNA 侧把失败伪装成"已停止"会触发错误的暂停/续播。

### 🖥️ 前端与接口约定

**新版控制台（`static/app/`）**：默认入口，原生 ES module + 原生 CSS，
不依赖 jQuery / Vue / 构建工具，单页内含「播放 / 音乐库 / 歌单 / 在线 / 设置」五个视图。
旧的 `static/default/` 与 `static/tailwind/` 已重写并只保留跳转桩（旧书签仍可用）。

其余 UI（`pure` / `soundSpace` / `xplayer` / `onlineSearch` / `iwebplayer`）保持原样，
其中前三套是 Vite 构建产物，仓库内没有源码，改动需回到各自项目。

**接口命名**：新路径统一用 `/api/` 前缀；历史裸路径全部保留为别名，
两者由**同一个处理函数**注册（堆叠 decorator，不是转发），行为完全一致。
写新代码请用 `/api/` 前缀，旧路径只做兼容、不再扩展：

| 领域 | 新路径示例 |
|---|---|
| 设备 | `/api/device/list`、`/api/device/volume`、`/api/device/cmd`、`/api/device/play/url`、`/api/device/stop` |
| 音乐 | `/api/music/list`、`/api/music/infos`、`/api/music/playing`、`/api/music/play`、`/api/music/search` |
| 歌单 | `/api/playlist/names`、`/api/playlist/musics`、`/api/playlist/add`、`/api/playlist/music/add` |
| 系统 | `/api/system/setting`(GET/POST)、`/api/system/version`、`/api/system/log` |

音频/封面/代理这类**要嵌进音箱播放地址**的路径（`/music/…`、`/picture/…`、`/proxy/…`）
不加 `/api` 前缀，避免影响设备端拉流。

**已移除**：下载工具（`/downloadplaylist`、`/downloadonemusic`、`/download_progress`
及任务队列的暂停/恢复/停止/删除/重启接口）与其前端页面。
注意"下载"的内部实现仍在：在线播放一首非本地歌曲时，
`device_player.download()` 会用 yt-dlp 先落盘再播放，这条链路没有动。
`/downloadjson` 也与下载无关（它是"拉取远程 JSON 填进设置"），保留。

## 📱 设备支持

### 已测试支持的设备

| 型号 | 设备名称 |
|------|---------|
| **L06A** | [小爱音箱](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l06a) |
| **L07A** | [Redmi小爱音箱 Play](https://home.mi.com/webapp/content/baike/product/index.html?model=xiaomi.wifispeaker.l7a) |
| **S12/S12A/MDZ-25-DA** | [小米AI音箱](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.s12) |
| **LX5A** | [小爱音箱 万能遥控版](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.lx5a) |
| **LX05** | [小爱音箱Play（2019款）](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.lx05) |
| **L15A** | [小米AI音箱（第二代）](https://home.mi.com/webapp/content/baike/product/index.html?model=xiaomi.wifispeaker.l15a#/) |
| **L16A** | [Xiaomi Sound](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l16a) |
| **L17A** | [Xiaomi Sound Pro](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l17a) |
| **LX06** | [小爱音箱Pro](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.lx06) |
| **LX01** | [小爱音箱mini](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.lx01) |
| **L05B** | [小爱音箱Play](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l05b) |
| **L05C** | [小米小爱音箱Play 增强版](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l05c) |
| **L09A** | [小米音箱Art](https://home.mi.com/webapp/content/baike/product/index.html?model=xiaomi.wifispeaker.l09a) |
| **LX04/X10A/X08A** | 触屏版音箱 |
| **X08C/X08E/X8F** | 触屏版音箱 |
| **M01/XMYX01JY** | 小米小爱音箱HD |
| **OH2P** | XIAOMI 智能音箱 Pro |
| **OH2** | XIAOMI 智能音箱 |

> [!NOTE]
> - 型号与产品名称对照可在 [小米IoT平台](https://home.miot-spec.com/s/xiaomi.wifispeaker) 查询
> - 如果你的设备支持播放，请反馈给我添加到支持列表里，谢谢
> - 目前应该所有设备类型都已经支持播放，有问题可随时反馈

### 🎵 支持音乐格式

- **mp3** - 标准音频格式
- **flac** - 无损音频格式
- **wav** - 无损音频格式
- **ape** - 无损音频格式
- **ogg** - 开源音频格式
- **m4a** - AAC 音频格式

> [!NOTE]
> - 本地音乐会搜索目录下上面格式的文件，下载的歌曲是 mp3 格式
> - 已知 L05B、L05C、LX06、L16A 不支持 flac 格式
> - 如果格式不能播放可以打开【转换为MP3】和【型号兼容模式】选项，详见 [#153](https://github.com/hanxi/xiaomusic/issues/153#issuecomment-2328168689)

## 🌏 网络歌单功能

可以配置一个 json 格式的歌单，支持电台和歌曲，也可以直接用别人分享的链接。同时配备了 m3u 文件格式转换工具，可以很方便地把 m3u 电台文件转换成网络歌单格式的 json 文件。

详细用法见 [#78](https://github.com/hanxi/xiaomusic/issues/78)

> [!NOTE]
> 欢迎有想法的朋友们制作更多的歌单转换工具，一起完善项目功能！

## ⚠️ 安全提醒

> [!IMPORTANT]
>
> 1. 如果配置了公网访问 xiaomusic ，请一定要开启密码登陆，并设置复杂的密码。且不要在公共场所的 WiFi 环境下使用，否则可能造成小米账号密码泄露。
> 2. 强烈不建议将小爱音箱的小米账号绑定摄像头，代码难免会有 bug ，一旦小米账号密码泄露，可能监控录像也会泄露。

## 💬 社区与支持

### 📢 讨论区

<p align="center">
  <a href="https://github.com/hanxi/xiaomusic/issues">💬 GitHub Issues</a> •
  <a href="https://pd.qq.com/s/e2jybz0ss">🎮 QQ频道</a> •
  <a href="https://qm.qq.com/q/vQtFRinceA">👥 QQ交流群</a> •
  <a href="https://github.com/hanxi/xiaomusic/issues/86">💬 微信群</a>
</p>

### 🤝 如何贡献

我们欢迎所有形式的贡献，包括但不限于：

- 🐛 **报告 Bug**：在 [Issues](https://github.com/hanxi/xiaomusic/issues) 中提交问题
- 💡 **功能建议**：分享你的想法和建议
- 📝 **改进文档**：帮助完善文档和教程
- 🎨 **前端美化**：优化 Web 控制台界面
- 🔧 **代码贡献**：提交 Pull Request

> [!TIP]
> 提交代码前请确保运行 `pdm lintfmt` 检查代码规范

## 📚 相关资源

### 👉 更多教程

更多功能见 [📝 文档汇总](https://github.com/hanxi/xiaomusic/issues/211)

### 🎨 第三方主题

- [pure 主题 xiaomusicUI](https://github.com/52fisher/xiaomusicUI)
- [移动端的播放器主题](https://github.com/52fisher/XMusicPlayer)
- [Tailwind主题](https://github.com/clarencejh/xiaomusic)
- [SoundScape主题](https://github.com/jhao0413/SoundScape)
- [第三方主题](https://github.com/DarrenWen/xiaomusicui)

### 📱 配套应用

- [微信小程序: 卯卯音乐](https://github.com/F-loat/xiaoplayer)
- [手机APP: 风花雪乐](https://github.com/jokezc/mi_music)
- [JS在线播放插件](https://github.com/boluofan/xiaomusic-online)
- [手机APP: HMusic](https://github.com/hpcll/HMusic)
- [安卓TV: 肉肉音乐TV](https://github.com/GanHuaLin/rouroumusic-tv)

### ❤️ 致谢

**核心依赖**
- [xiaomi](https://www.mi.com/) - 小米智能设备
- [xiaogpt](https://github.com/yihong0618/xiaogpt) - 项目灵感来源
- [MiService](https://github.com/yihong0618/MiService) - 小米服务接口
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 音乐下载工具

**开发工具**
- [PDM](https://pdm.fming.dev/latest/) - Python 包管理
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [Umami](https://github.com/umami-software/umami) - 统计分析
- [Sentry](https://github.com/getsentry/sentry) - 报错监控

**参考资料**
- [实现原理](https://github.com/yihong0618/gitblog/issues/258)
- [awesome-xiaoai](https://github.com/zzz6519003/awesome-xiaoai)

**特别感谢**
- 所有帮忙调试和测试的朋友
- 所有反馈问题和建议的朋友
- 所有贡献代码和文档的开发者

## 🚨 免责声明

本项目仅供学习和研究目的，不得用于任何商业活动。用户在使用本项目时应遵守所在地区的法律法规，对于违法使用所导致的后果，本项目及作者不承担任何责任。
本项目可能存在未知的缺陷和风险（包括但不限于设备损坏和账号封禁等），使用者应自行承担使用本项目所产生的所有风险及责任。
作者不保证本项目的准确性、完整性、及时性、可靠性，也不承担任何因使用本项目而产生的任何损失或损害责任。
使用本项目即表示您已阅读并同意本免责声明的全部内容。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=hanxi/xiaomusic&type=Date)](https://star-history.com/#hanxi/xiaomusic&Date)

## License

[GPL-3.0-or-later](LICENSE) © 2024 涵曦 及 contributors

本项目原有代码来自 [XiaoMusic](https://github.com/hanxi/xiaomusic)（MIT）；
投送功能（DLNA / AirPlay，`xiaomusic/cast/`）移植自
[MiAir Next](https://github.com/deerwan/miair-next)（GPL-3.0-or-later）；
Home Assistant 接入（`xiaomusic/ha/`）参考并部分移植自
[xiaoai-ha-bridge](https://github.com/chenshuhe/xiaoai-ha-bridge)（MIT）。
组合作品整体按 GPL-3.0-or-later 分发，各组件的出处与原始署名见 [NOTICE](NOTICE)。
