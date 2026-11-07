# AI Passport Spotify Controller

**简体中文** | [English](#english)

> **项目状态 / Project status:** 阶段提交；M1 本地原型已实现但未完整验收，非完整 MVP / Interim submission; M1 local prototype implemented, not fully qualified or a complete MVP · **MVP target:** v0.1 · **Kickoff:** 2026-11-05

**教授审阅 / Submission review:** [阶段提交说明：已做、未做、修改及验证结果 / Interim submission report](docs/SUBMISSION_STATUS.md) · **As of 2026-11-07**

将 **FOLOTOY AI Passport** 变成一个适用于 Windows 桌面版 Spotify 的 **迷你正在播放显示屏 + 三键无线遥控器**。

**核心原则：Spotify 始终在 Windows 电脑上播放音乐。AI Passport 只显示信息和发送控制指令，绝不接收音乐流、解码音频或播放声音。**

Turn the **FOLOTOY AI Passport** into a compact **Now Playing display and three-button wireless remote** for Spotify Desktop on Windows.

**Core rule: Music plays exclusively on the Windows PC. AI Passport displays metadata and sends control commands only. It never streams, decodes, or outputs audio.**

## 简体中文

### MVP v0.1 功能

**显示**
- 当前歌曲的专辑封面
- 歌曲名称、歌手名称
- 两行同步歌词：当前行高亮、下一行弱化显示
- 播放进度条、当前时间和总时长
- 最小连接/播放状态提示

**控制**
| 按键 | 行为 |
| --- | --- |
| UP / 上 | 第一次按下使当前歌曲回到 **0:00**；若在 **2 秒内**再次按下，切到**上一首** |
| OK / 中 | 播放 / 暂停切换 |
| DOWN / 下 | 下一首 |

进度无论是多少，**第一次 UP 都是从头播放**，而不是直接发“上一首”媒体键。按键去抖、两秒窗口和切歌后重置状态都必须在实现中处理。

**明确不做：** AI Passport 音频播放、蓝牙音箱、MP3 解码、音量控制、触屏、播放列表操作、语音助手、麦克风、设备端 Spotify 登录、设备端歌词搜索等。

### 预期界面

目标显示屏为 **240 × 320 竖屏**（具体尺寸和引脚以实际设备及官方 BSP 为准）。

```text
┌─────────────────────────┐
│ ● Spotify          Wi-Fi│
│                         │
│     ┌─────────────┐     │
│     │  Album art  │     │
│     │   封  面    │     │
│     └─────────────┘     │
│       Song Title        │
│       Artist Name       │
│ ─────────────────────── │
│   当前歌词 / Current    │
│   下一句 / Next line    │
│ ━━━━━━━━━╺───────────── │
│ 1:08                3:12│
│    ◀◀      ▶/Ⅱ     ▶▶   │
└─────────────────────────┘
```

上图是布局示意，非实际渲染。长标题、中文字体、专辑封面缩放、长歌词截断等会在真机验证。

### 组成与通信

```text
Windows Spotify Desktop (plays audio)
               ⇅
Windows Companion (Python)
  ├─ libspotifyctl / Windows SMTC: state & transport controls
  ├─ LRCLIB: time-synced lyrics (when available)
  └─ image resize/cache and local server
               ⇅ Wi-Fi (WebSocket + cover HTTP)
FOLOTOY AI Passport (ESP32-C3 / ESP-IDF / LVGL)
  ├─ 240×320 display: cover, title, artist, two lyric lines, progress
  └─ UP / OK / DOWN: control messages only
```

Windows Companion 负责 Spotify 集成、歌词匹配/时间同步、图片缩放缓存及通信。设备固件只管渲染、按钮和网络连接。优先**局域网手动配置地址**，后续再考虑自动发现。

### 文档导航

| 文件 | 内容 |
| --- | --- |
| [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) | 中英双语产品需求、交互、异常场景和验收标准 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 技术架构、选型、数据生命周期、风险 |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | v0.1 WebSocket/HTTP 消息草案 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 分阶段实施计划、交付物、测试清单 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发约定、建议目录、验证先后顺序 |
| [docs/SUBMISSION_STATUS.md](docs/SUBMISSION_STATUS.md) | 阶段交付：已完成、未完成、本轮修改、验证证据及剩余工作 |
| [companion/README.md](companion/README.md) | M1 本地 CLI 安装、Mock/真实测试、版本与已知限制 |

### 当前状态

**已加入仅本地运行的 M1 Windows Companion、CLI 和自动化测试，详见 [companion/README.md](companion/README.md)。** 该文档区分 Mock 测试与真实 Windows Spotify 结果。尚无固件、Windows 安装包、网络服务或经过设备验收的完整 MVP；ROADMAP 验收关卡不自动勾选。请勿将其他规划功能当作已经实现。

### 参考与鸣谢

- [FOLOTOY AI Passport 官方项目](https://github.com/FoloToy/ai-passport)
- [libspotifyctl](https://github.com/ColdMeekly/spotifyctl): Windows 本地 Spotify 状态/控制（基于 SMTC 等）
- [LRCLIB](https://github.com/tranxuanthang/lrclib): 同步歌词服务
- [AI Passport PC Controller](https://github.com/AmazingAndrew/pc-controller): 可参考的设备端遥控器项目

本项目是独立社区项目，与 Spotify 和 FOLOTOY 官方无隶属关系。第三方库、专辑封面、歌词遵循各自许可证及使用条款。**尚未选定本仓库许可证；在明确授权前不要假设代码采用开源许可证。**

---

<a id="english"></a>
## English

### MVP v0.1 features

**Display**
- Album artwork for the currently playing track
- Song title and artist
- Two time-synchronised lyric lines: current line highlighted, next line dimmed
- Playback progress, elapsed time, total duration
- Minimal playback/connection status

**Controls**
| Button | Behaviour |
| --- | --- |
| UP | First press seeks to **0:00**; another press **within 2 seconds** selects the **previous track** |
| OK | Toggle play / pause |
| DOWN | Next track |

The first UP press always attempts **seek to start**, never an immediate previous-track media-key event. Debouncing, timing, and track-change resets are part of the requirements.

**Explicitly out of scope:** audio streaming or playback on the device, Bluetooth speaker, MP3 decoding, volume adjustment, touch interactions, playlist management, voice features, device microphone, Spotify login on device, or lyrics fetching on device.

### Display concept

The intended screen is **240 × 320 portrait**, subject to confirmation with the physical device and official BSP. See the wireframe in the Chinese section above. Layout, clipping, Chinese glyph support and artwork decoding require on-device validation.

### Architecture

Spotify Desktop plays all audio on Windows. A Python Windows Companion reads local player state, retrieves matched synced lyrics, scales album artwork and serves the device over local Wi-Fi. The ESP32-C3 firmware (ESP-IDF + LVGL) renders the UI and sends only three kinds of button actions. Manual host configuration is preferred for v0.1; discovery can wait.

### Project documents

- [Product specification](docs/PRODUCT_SPEC.md)
- [Architecture & technical decisions](docs/ARCHITECTURE.md)
- [Local protocol draft](docs/PROTOCOL.md)
- [Roadmap & acceptance gates](docs/ROADMAP.md)
- [Development guide](docs/DEVELOPMENT.md)
- [Interim submission: completed work, gaps, changes and verification](docs/SUBMISSION_STATUS.md)
- [M1 Companion installation, CLI, tests and limitations](companion/README.md)

### Status, dependencies and licensing

**M1 local validation code is available.** See [companion/README.md](companion/README.md) for installation, the CLI, separate Mock/actual Windows test evidence and limitations. No firmware, Windows installer, network server or device-qualified complete MVP is included; roadmap gates are not automatically checked. This independent community project is not affiliated with Spotify or FOLOTOY. Respect third-party licenses, lyric availability, artwork rights and service policies. **A license for this repository has not been selected.**
