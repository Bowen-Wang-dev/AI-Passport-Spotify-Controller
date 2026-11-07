# 开发路线图与验收关卡 / Roadmap & Acceptance Gates

**Project start / 立项日期:** 2026-11-05 · **MVP:** v0.1

## 简体中文

### 当前进度

| 里程碑 | 工作 | 状态 |
| --- | --- | --- |
| **M0** | 需求冻结、文档和项目初始化 | **已完成文档初始化** |
| **M1** | Windows Companion 本地能力验证 | **进行中：已有本地原型及离线测试；未完整验收** |
| **M2** | AI Passport 固件静态 UI 与按键 | 未开始 |
| **M3** | Wi-Fi 联调和真实 Spotify 数据 | 未开始 |
| **M4** | 稳定性、打包、刷机说明和 v0.1 验收 | 未开始 |

**状态更新：2026-11-07。** M1 代码和离线测试已存在，本次默认测试为 **246 passed / 2 skipped**；两项真实 Windows 集成测试本次未运行。历史实机记录、未完成项和本轮修改见 [阶段提交说明](SUBMISSION_STATUS.md)。M1 仍需真实同步歌词匹配、重启/广告/长期稳定性验证及独立评审；不能把“已实现”当作“完整验收通过”。M2–M4 仍未完成。

### M0：立项与规范（初始化阶段）

产物：中英双语 README、产品需求、架构、协议、开发说明与路线图。功能范围锁定为**显示+三键控制**，不做设备端音频。

完成条件：所有技术文档对关键行为一致，任何新增需求需修改规格再实施。

### M1：Windows Companion 技术验证（优先）

任务：
1. 在目标 Windows 环境安装 Spotify Desktop，核对版本及 Windows SMTC 能力。
2. 实测 `libspotifyctl` Python 接口能读取当前 `title/artist/album/status/position/duration/albumArt`。
3. 实测 Play/Pause、Next、Previous 和 **Seek(0)**，包括暂停时 Seek、广告/能力不可用场景。
4. 查询 LRCLIB，严格匹配并解析 LRC；能根据播放位置输出两行歌词与无歌词回退。
5. 将封面压缩为小 JPEG；展示无封面回退；不涉及设备端音频。
6. 编写 CLI 或本地模拟客户端的可重复测试；记录对第三方库的版本依赖及失败情况。

**验收门槛：** 在 Windows 本地能稳定获得所需字段、执行所需控制，并有两个歌词行/无歌词结果；若 Seek 不可用，应先解决技术方案而非开始编写完整 UI。

### M2：AI Passport 固件独立验证

任务：
1. 从官方 BSP 确认设备硬件、烧录/恢复流程、分区、屏幕及按键映射。
2. 固定一份**虚构测试数据**，渲染封面、歌名、歌手、歌词两行、进度条及状态栏。
3. 加入 UP/OK/DOWN 去抖及事件发送接口（模拟服务即可）。
4. 在真机上验证字体（中/英）、换行、封面格式、RAM 峰值、播放进度绘制、稳定性。
5. 保留一键恢复或官方重新刷机办法，**不触碰音频播放路径**。

**验收门槛：** 连续刷新界面且按键有效，不因超长标题/损坏图片/空歌词崩溃。

### M3：局域网集成

任务：
1. Windows 开启本地 WS/HTTP 服务，设备用手动地址与令牌连接。
2. 建立 `hello/welcome/state/lyrics/input/ack` 及按版本拉取封面。
3. 落实 Companion 端 UP **2 秒首按从头、再按上一首** 状态机，按钮成功/失败应答。
4. 验证真实 Spotify 播放、暂停、切歌、主机侧 Seek 与歌词同步、中文歌名/歌词。
5. 断线自动重连、清理旧封面/旧歌词、恢复全量状态。
6. 检查无音频流从 Windows 传到 AI Passport，也无设备发声/录音。

**验收门槛：** 实机上完成全功能闭环，并通过 [PRODUCT_SPEC.md](PRODUCT_SPEC.md) 的 F-01..F-10。

### M4：发布候选

任务：故障注入（掉线、服务关闭、广告、无歌词、损坏封面）、内存与长期运行测试、部署说明、固件与 Windows Companion 可复现构建、第三方许可检查。最终提供明晰的刷机、配置、卸载/恢复说明。

**验收门槛：** 在记录的软硬件版本上完整测试通过后，才可发布标为“可用”的 v0.1；否则明确标为实验性构建。当前尚未指定发布日期。

### 建议测试矩阵

| 场景 | 预期 |
| --- | --- |
| 播放中按 UP 一次 | 进度 0:00，同曲继续播放 |
| 2 秒内第二次 UP | 上一首 |
| 超过 2 秒再次 UP | 新一轮 Seek(0) |
| 暂停中按 UP | Seek(0) 后依然暂停 |
| 按 OK | 播放/暂停切换 |
| 按 DOWN | 下一首 |
| PC 端手动切歌/拖进度 | 封面、文字、歌词和进度随之更新 |
| LRCLIB 查不到歌 | 显示无同步歌词，控制仍可用 |
| Wi-Fi 断开/恢复 | UI 标识断线，恢复后无陈旧数据 |
| Spotify 关闭/广告 | 清晰的不可用状态，不发错误的替代指令 |
| 超长中文/英文歌曲名 | 无越界，无崩溃 |
| 无/损坏封面 | 占位图而非崩溃 |
| 网络抓包/固件审查 | 没有音乐流或设备音频处理 |

---

## English

### Milestones

| Gate | Deliverable | Status |
| --- | --- | --- |
| **M0** | Bilingual scope and project documentation | Documentation initialized |
| **M1** | Validate Windows Spotify, controls, art and synced lyrics locally | **In progress: local prototype and offline tests available; not fully qualified** |
| **M2** | Validate on-device static UI, buttons, font and memory | Not started |
| **M3** | Integrate Wi-Fi protocol, live state and actual controls | Not started |
| **M4** | Regression tests, reproducible builds and release instructions | Not started |

**Status updated 2026-11-07:** the default offline suite produced **246 passed / 2 skipped**; real Windows integration was not rerun. M1 still needs live synced-lyric matching, restart/ad/soak validation and independent review. See the [interim submission report](SUBMISSION_STATUS.md) for the distinction between implementation, historical evidence and acceptance. M2–M4 remain incomplete.

**M0:** Freeze exactly two functions: **display + simple control**. Exclude all device audio behavior. Keep README, specs, architecture and protocol mutually consistent.

**M1: Windows-first feasibility.** Verify Spotify Desktop + SMTC integration using `libspotifyctl` (or documented substitute), including title/artist/album/status/position/duration/art and Play/Pause/Next/Previous/**Seek(0)**. Check paused seeking and unsupported actions. Match LRCLIB synced lyrics, select two lines or fallback, shrink cover art and provide reproducible local diagnostics. **Gate:** all host capabilities needed for MVP work or have a documented viable fallback. Do not mask unsupported Seek.

**M2: Hardware UI validation.** Confirm official BSP, board revisions, flashing/recovery and button mappings. Render fictional song data, Unicode/Chinese, art placeholder, two lyric lines and progress. Verify debouncing, UI task safety, memory peaks and resilience to invalid/long inputs. **Gate:** stable on-device rendering, no audio subsystem involvement.

**M3: Live integration.** Connect device to Companion using manually configured LAN address and token. Implement `hello/welcome/state/lyrics/input/ack` and HTTP artwork, track revision checks, auto-reconnect and full resync. Implement the **first UP seeks to 0:00 / second UP within 2 seconds selects Previous** state machine on Windows. Verify host-side seeks, skips, pause, lyric changes and failure paths. **Gate:** all F-01..F-10 criteria in [PRODUCT_SPEC.md](PRODUCT_SPEC.md) pass on physical hardware.

**M4: Release qualification.** Run tests for network loss, Spotify exit, missing lyrics, ads, invalid covers and extended runtime. Record dependency versions, produce reproducible firmware + Companion builds and flashing/recovery instructions, and review all third-party licensing. Release a “usable” v0.1 only after a real-world pass; otherwise mark artifacts experimental. **No release date promised.**

The Chinese test matrix above is the shared bilingual checklist: each row maps to a button scenario, host-side changes, missing lyric/art content, reconnect, non-ASCII strings, and proof of **no audio stream or playback on Passport**.
