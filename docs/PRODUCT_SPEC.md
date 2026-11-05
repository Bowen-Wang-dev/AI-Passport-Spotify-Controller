# 产品需求规格 / Product Requirements Specification

**版本 / Version:** v0.1 (draft) · **日期 / Date:** 2026-11-05 · **状态 / Status:** 已确定 MVP 范围，待实现 / Scope agreed, not implemented

## 简体中文

### 1. 产品定位

AI Passport Spotify Controller 是 **Windows 版 Spotify 的无线状态显示屏与三键遥控器**。音乐始终由 **Windows PC** 播放，设备**不接收音乐数据、不进行音频解码、不发声**。

唯一两项产品能力：
1. **显示**：封面、歌曲名、歌手、当前+下一行同步歌词、进度条及时间。
2. **控制**：从头播放/上一首、播放/暂停、下一首。

设备无扬声器、麦克风及音频播放方面的软件职责。它不是 Spotify Connect 播放终端，不是音乐播放器，也不是音箱。

### 2. 目标环境与约束

- 硬件：FOLOTOY AI Passport；目标 ESP32-C3 / 240 × 320 竖屏 / UP、OK、DOWN 实体按键。具体 BSP、屏幕/按键映射须实机检查。
- 主机：Windows 10 1809+ / Windows 11；已安装并运行 Spotify 桌面客户端。Windows SMTC 支持与 Spotify 元数据表现须实测。
- 网络：两端位于同一可信任的 Wi-Fi/LAN，Windows Companion 运行时设备才能使用。
- 软件：PC Companion 负责 Spotify、LRCLIB、封面转码、时间同步与按键决策；固件负责网络、UI 和按键采样。
- MVP 不要求设备独立访问 Spotify、互联网或任何账户。无歌词时仍须可以控制播放。

### 3. UI 层级与行为

从上至下：细状态栏 → **方形封面** → **标题** → **歌手** → 分隔 → **当前歌词** / **下一句歌词** → **进度条** → 已播/总时长 → 极简按键提示（空间不足可省略）。

- 当前歌词亮色，下一行弱化；没有同步歌词显示「暂无同步歌词 / No synced lyrics」。
- 长标题/歌手：最多约 1–2 行并安全截断/滚动（具体以性能与布局为准）；不得遮挡歌词/进度。
- 字体至少覆盖可见简体中文、拉丁字母、数字和基本标点；不支持的字形有回退方案。
- 封面先在 PC 缩小，再发给设备；解码失败显示占位图，不得导致重启。
- 进度条随歌曲播放推进，暂停时停止，切歌时复位，不可出现负数或超出总时长的绘制。
- 未连接 / 无 Spotify / 暂停 / 播放 / 广告（若可检测）均有明确且简洁的状态表达。
- 不提供触屏、音量、音效、歌曲列表、歌词浏览或其他屏幕页面。

### 4. 按键规格

| 按键 | 行为 | 说明 |
| --- | --- | --- |
| **UP** | 首次：Seek 到当前曲 0:00；**2 秒内再次**：Previous | 规则由 Windows Companion 实现，不直接把首按映射成系统 Previous |
| **OK** | Toggle Play/Pause | 播放中→暂停；暂停中→播放 |
| **DOWN** | Next | 单击立即下一首 |

**UP 状态机**：
1. 第一次有效 UP 发送 Seek(0)，记录成功的动作及单调时钟时间，进入 2 秒窗口；若 Seek 不可用，应返回失败并提示，不默默跳上一首。
2. 同一首歌曲在窗口内第二次有效 UP 发送 Previous，然后关闭窗口。
3. 超时、切歌、连接重置时清除窗口；再次 UP 当作首次操作。
4. 暂停状态下 Seek(0) 不应强制恢复播放。
5. 需按键去抖（建议初值 30–50 ms，实机调整），保证一次物理按压只触发一次。

其他失败条件：Spotify 未运行、不可控制的广告、媒体能力不可用、网络断开，均不得悄悄执行不同命令。可给短暂的错误状态但不添加新功能。

### 5. 歌词匹配与同步

- Companion 首选 LRCLIB **同步 LRC 歌词**；查询条件根据标题/歌手/专辑/时长做匹配并检查合理性。
- 将 LRC 解析为时间戳 + 文本，按当前播放进度选择**当前行**与**下一行**；换歌立即重置。
- 允许纯文本歌词仅作为“暂无同步歌词”的回退说明，不显示错误的“同步”假象。
- Seek(0)、暂停/继续、跳歌以及 PC 用户手动拖进度都应重新计算歌词行。
- 歌词服务不可用、找不到歌、匹配不确定时，明确回退并继续显示其他信息。
- 不在仓库加入未经许可的真实歌词或封面；仅在运行时处理相关内容，并遵守上游服务规则。

### 6. 验收标准（可测试）

- **F-01** Windows 播放歌曲时，设备显示非空歌曲名/歌手，封面可用则显示，且**声音只从 Windows PC 的既有输出设备发出**。
- **F-02** 设备展示当前+下一行同步歌词，当前行随播放进度变化；无匹配歌词可正常退化。
- **F-03** Windows 端暂停、恢复、切歌、拖动进度后，设备最终同步到正确状态，不需要重启。
- **F-04** UP 首按从头播放；在同曲 2 秒内再次按 UP 切上一首；超过 2 秒再次按仅从头播放。
- **F-05** OK 切换播放/暂停；DOWN 切下一首。
- **F-06** 封面、歌词、长中文标题、无封面、网络断线、Spotify 关闭均不能引发设备崩溃。
- **F-07** 断线重连后重新同步完整快照；旧封面和旧歌词不得长期错误残留。
- **F-08** 无任何设备端播放音乐、下载 MP3、音频缓存、麦克风采集或扬声器调用。
- **F-09** 在同一局域网内通过非公开配置的认证密钥连接；无效控制命令被拒绝。
- **F-10** Windows Companion 能清晰报告依赖安装与 Spotify 接口失败情况。

### 7. 非目标

不含蓝牙音频、Spotify Connect 接收、音量、EQ、歌词翻页、搜索、播放列表、语音、触摸、云同步、互联网远程控制、跨平台主机、自动发现（可后续考虑）。不额外增设硬件。

---

## English

### 1. Purpose

AI Passport Spotify Controller is a **wireless Now Playing display and three-button remote for Spotify Desktop on Windows**. The **Windows PC is the only audio playback device**. The Passport **never receives music streams, decodes audio or produces sound**.

Exactly two product capabilities:
1. **Display:** album art, track title, artist, two synced lyric lines (current/next), progress and time.
2. **Control:** restart/previous, play/pause, next.

It is **not** a Spotify Connect endpoint, player, speaker or audio-processing device.

### 2. Target platform

- FOLOTOY AI Passport; targeted ESP32-C3, 240 × 320 portrait display and three physical buttons; confirm actual pin mappings and BSP on hardware.
- Windows 10 1809+ or Windows 11, Spotify Desktop running; verify SMTC behavior on the target PC.
- Shared trusted local network; an active Windows Companion is required.
- Companion owns player integration, lyric lookup, image transformation, timing and button semantics. Firmware owns UI, buttons and local connectivity.
- The device never logs into Spotify; missing lyrics must not disable controls.

### 3. Screen content and states

Top-to-bottom: slim status indicator → square cover art → title → artist → divider → **current lyric** and **next lyric** → progress → elapsed/total time → optional three-button hints.

Highlight the current lyric and dim the next. Show **No synced lyrics** when missing. Safely clip/wrap long titles and Chinese/Unicode text. Resize covers on Windows and provide an on-device placeholder. Never allow image failure to crash firmware. Interpolate progress during playback, freeze it while paused, and clamp to duration. Make disconnected, no-player, playing, paused, and detectable ad states visually clear. No extra menus or screens.

### 4. Input behavior

| Button | Required action |
| --- | --- |
| **UP** | First press: seek current track to **0:00**; second press **within 2 seconds** on the same track: **Previous** |
| **OK** | Toggle Play/Pause |
| **DOWN** | Next |

The **Companion** owns the UP timing state machine. Only a successful first Seek(0) arms the 2-second window; seek failure must not silently change tracks. A valid second press triggers Previous and clears the window. Clear on timeout, track change or connection reset. Seeking while paused does not force playback. Debounce buttons; begin with 30–50 ms and refine on hardware.

If Spotify is closed, ads are non-skippable, capabilities are unavailable or connection is lost, report failure without silently substituting another control.

### 5. Synced lyrics

Use LRCLIB as a candidate source for timestamped LRC, matching title, artist, album and approximate duration. Parse timestamp/text pairs, pick the current and next line using playback position, and reset immediately on track changes. Recalculate on seek, pause/resume, skip, and host-side timeline changes. No lyrics or uncertain matches yield a clear fallback; plain unsynchronised text is **not** presented as synced. Handle lyrics/art at runtime and respect licensing, service policies and copyright.

### 6. Acceptance criteria

- **F-01:** Display current title and artist and available artwork while all music stays on existing **Windows audio output**.
- **F-02:** Show current and next synced lyric lines, changing at correct timestamps; gracefully handle no match.
- **F-03:** Eventually reflect host-side pause, resume, skip and seek without reboot.
- **F-04:** UP: seek to start, second press on same track within 2 seconds: previous; after timeout: seek to start again.
- **F-05:** OK toggles play/pause; DOWN skips next.
- **F-06:** Artwork failure, no lyrics, long Unicode strings, disconnect and Spotify shutdown do not crash the device.
- **F-07:** Full fresh state after reconnect; no persistent stale art or lyrics.
- **F-08:** No device-side MP3 downloads, streaming, decoding, sound output or microphone activity.
- **F-09:** Local pairing secret authenticates connections and commands.
- **F-10:** Companion exposes useful diagnostic errors for dependencies and player integration.

### 7. Out of scope

Bluetooth audio, Spotify Connect receiver, volume, EQ, lyric browsing, music search, playlists, voice, touchscreen, cloud sync, remote Internet access, non-Windows hosts, network auto-discovery and extra hardware.
