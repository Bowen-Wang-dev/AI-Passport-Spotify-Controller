# 阶段提交说明 / Interim Submission Report

**提交整理日期：2026-11-07**

**项目：AI Passport Spotify Controller**

**提交定位：未完成项目的阶段成果，不是完整 MVP 或正式产品发布。**

## 1. 当前做到什么程度

目标是让 FOLOTOY AI Passport 显示 Windows Spotify 的正在播放信息，并提供 UP / OK / DOWN 三键控制。音乐始终由 Windows Spotify Desktop 播放，设备不接收或播放音频。

目前交付的是 **Windows 端本地 Companion 原型、命令行验证工具、自动化测试和设计文档**。尚未实现设备固件、设备界面和局域网服务，因此不能在 AI Passport 真机上完成端到端使用。

| 阶段 | 实际状态 | 是否完成验收 |
| --- | --- | --- |
| M0：需求、架构、协议、开发文档 | 已有中英双语文档；协议是设计草案 | 文档初始化已完成，不等于功能完成 |
| M1：Windows 本地 Companion | 已实现本地原型；本次离线测试通过；已有历史实机记录 | **进行中，未完整验收** |
| M2：设备固件、静态 UI、按键 | 未实现 | 未验收 |
| M3：Wi-Fi 服务、协议和设备联调 | 未实现 | 未验收 |
| M4：长期稳定性、打包和发布 | 未完成；只有本地测试与安装步骤 | 未验收 |

不使用“完成 50%”之类未经量化的比例，也不把离线测试通过等同于产品完成。

## 2. 已完成的实现

| 项目 | 已交付内容 | 代码依据与边界 |
| --- | --- | --- |
| 数据模型 | 歌曲、播放快照、能力、控制结果与可替换适配器接口 | [models.py](../companion/src/passport_companion/models.py) |
| Windows Spotify 适配器 | 读取曲目信息、播放状态、位置、时长和封面；提供播放、暂停、切歌及 Seek | [spotify.py](../companion/src/passport_companion/spotify.py)；依赖本机 Spotify/SMTC，不能保证所有环境可用 |
| 三键业务逻辑 | OK 切换播放/暂停；DOWN 下一首；首次 UP 回到 0:00，成功后两秒内再次 UP 请求上一首；去抖及状态失效处理 | [buttons.py](../companion/src/passport_companion/buttons.py)；当前是 PC 命令模拟，不是实体按键驱动 |
| 同步歌词处理 | LRCLIB 严格元数据匹配、LRC 解析、当前/下一句选择、缓存、限速及无歌词回退 | [lyrics.py](../companion/src/passport_companion/lyrics.py)；**尚无真实同步歌词成功匹配的演示证据** |
| 封面处理 | 在 PC 上转换为小尺寸 JPEG，处理缺失、损坏及大小超限 | [artwork.py](../companion/src/passport_companion/artwork.py)；不包含设备解码/渲染 |
| 本地编排与 CLI | status、doctor、watch、press、JSON 输出及离线 Mock；歌词查询不占用按键控制路径 | [service.py](../companion/src/passport_companion/service.py)、[cli.py](../companion/src/passport_companion/cli.py)、[mock.py](../companion/src/passport_companion/mock.py) |
| 测试与说明 | 七个测试文件、固定直接依赖、安装与复现步骤、已知限制 | [tests](../companion/tests/)、[pyproject.toml](../companion/pyproject.toml)、[Companion README](../companion/README.md) |

## 3. 未完成与尚未验证

### 尚未实现

- ESP-IDF / LVGL 固件、BSP/引脚确认、屏幕渲染、中文字体、实体按键及刷机/恢复流程。
- WebSocket / HTTP 服务、设备通信、令牌校验、封面传输、断线重连和全量状态恢复。
- Windows 安装包、固件构建产物、CI 和可复现的完整产品发布流程。
- AI Passport 真机上的显示、控制、歌词与封面端到端验收。

### 已有代码但证据不足

- 真实 LRCLIB 同步歌词匹配：历史请求返回 `none`；离线 LRC 测试不证明真实歌曲匹配成功。
- 真实广告、Spotify 完全退出/重启、Windows 睡眠唤醒及长时间运行未完整验收。
- 最低 Windows/Python 版本、ARM64 和其他运行时没有完整验证矩阵。
- 上游缺少稳定曲目 ID，相邻曲目元数据完全相同时可能无法确认切歌；超时明确报告失败，不伪造成功。
- 网络超时不能保证 DNS 或持续缓慢响应的严格总时限；已运行的歌词请求可能延迟进程退出。
- 仓库许可证尚未选定；第三方依赖及歌词/封面的再分发许可仍需单独核对。公开仓库不等于已授予开源许可。

### 原本就不在范围内

设备端音频播放、音乐下载、蓝牙音箱、麦克风/语音助手、音量控制、触屏、播放列表操作及设备端 Spotify 登录不是“漏做”的功能，而是产品规格明确排除的内容。

## 4. 哪些改了

### 相对原 GitHub 文档基线

对照远端原提交 `02732f628081bdfeb4d93efb4f2758ee8409b9ed`（`docs: add bilingual development.md plan`）：

- 新增 `companion/` 本地实现、测试、依赖配置和使用说明；这些代码在本次整理前已存在于本地，并非本轮重新开发。
- README 与开发说明由“只有规划文档”更新为“已有 M1 本地原型”，同时保留未完成 MVP 的说明。
- 本轮新增本报告和根目录忽略规则，避免将虚拟环境、缓存、生成元数据、凭据和下载内容作为交付文件。
- 本轮把路线图 M1 的过期“未开始”改为“进行中、未完整验收”，**没有将验收关卡标成通过**。
- 本轮修正 Companion 说明中“本地没有 Git、尚未连接仓库”的过期描述；2026-11-05 的历史记录保留并明确属于历史证据。
- 产品范围、架构和协议草案没有扩展；本轮不新增产品功能，不关闭未完成的里程碑或发布正式版本。

### 已有实现中的修正

原有 2026-11-05 记录记载：初次真实控制测试发现元数据过渡态误判，后改为稳定观察确认，并加入回归测试。当前代码也区分“原生命令已发送”与“观察确认成功”，确认超时返回失败。这些属于已有实现随本次提交交付的内容，**不冒充本轮新修复或重新实测的成果**。

## 5. 本次验证结果（2026-11-07）

测试环境为 Windows x64、Python **3.12.10**；项目直接依赖为 libspotifyctl **0.3.4**、Pillow **12.0.0**、pytest **8.4.2**。

初次测试因当前虚拟环境缺少 pytest 未能启动；按项目已有 `.[test]` 声明安装依赖后重新执行，结果如下。没有修改依赖版本来绕过失败。

| 验证项 | 本次结果 | 能证明什么 |
| --- | --- | --- |
| 默认测试 `python -m pytest -q` | **246 passed, 2 skipped，0.90 秒** | 离线逻辑/回归测试通过；跳过的两项是真实 Windows 集成测试，不计为通过 |
| `python -m pip check` | **No broken requirements found** | 当前环境已安装依赖没有声明冲突 |
| `python -m passport_companion --mock --json status` | 退出码 0，输出虚构歌曲状态 | 本地安装及离线 CLI 路径可运行，不代表真实 Spotify |
| `python -m passport_companion --mock --json press up up` | 退出码 0；依次返回 `seek_zero`、`previous`，均 `ok: true` | Mock 下两次 UP 逻辑可演示，不代表真实控制或实体按键 |

本次未开启 `PASSPORT_RUN_INTEGRATION` / `PASSPORT_RUN_CONTROLS`，未操作真实 Spotify，也未重新请求真实歌曲歌词。没有对设备、真实 Spotify 或歌词服务宣称新的验收通过。

### 历史证据，不是本次复测

[Companion 实测记录](../companion/README.md#实测记录--verification-record) 中保留了 **2026-11-05** 的记录：默认测试 246 passed / 2 skipped，显式真实 Windows 集成 2 passed；记录了元数据、封面、播放/暂停/切歌、非零位置回零及暂停 Seek。这是随项目已有文档提供的历史结果，本次没有重新执行来独立确认。该次真实 LRCLIB 查询为 `none`，不能据此宣称同步歌词实机成功。

## 6. 教授复现与查看入口

从仓库根目录打开 PowerShell，使用 x64 Python 3.12：

```powershell
Set-Location .\companion
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m passport_companion --mock --json status
.\.venv\Scripts\python.exe -m passport_companion --mock --json press up up
.\.venv\Scripts\python.exe -m pip check
```

Mock 运行不需要 Spotify，不访问歌词服务，不控制播放器。真实 Windows 测试有额外条件和副作用，只按 [Companion README](../companion/README.md) 的明确步骤选择执行。

## 7. 交付结论与后续

**本次交付达到“有可运行、可离线复现的 Windows 本地原型”的阶段，尚未达到“可在 AI Passport 上使用的完整产品”。** 已完成、未实现、未验证、本轮修改与历史记录已分开列明。

后续顺序：先补真实同步歌词、重启/广告和稳定性证据并评审 M1，再做设备静态 UI/按键，之后才做局域网联调，最后打包和完整验收。此处仅记录剩余工作，本轮不继续扩展。

## English Summary

This is an **interim submission of an incomplete project**, not a complete MVP or product release. The deliverable includes a local Windows Companion prototype, CLI, offline tests and design documents. Firmware, the physical device UI, LAN services, end-to-end validation and packaging are not implemented/completed.

On **2026-11-07**, the default suite produced **246 passed and 2 skipped**; `pip check` and two offline Mock CLI demonstrations also passed. The skipped tests require explicit real Spotify opt-in. No real player control, live lyric lookup or hardware validation was rerun. The existing **2026-11-05** real-Windows results are retained as historical records only; successful live synced-lyric matching remains unproven.

This submission adds the existing local implementation to the original documentation-only GitHub baseline and documents its limits. Submission-preparation changes are limited to documentation, roadmap accuracy and ignore rules; no new product feature or milestone acceptance is claimed.
