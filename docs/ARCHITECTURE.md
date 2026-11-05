# 技术架构 / Technical Architecture

**设计状态 / Design status:** 拟采用方案，须通过 M1/M2 实测 / Proposed, pending M1/M2 validation.

## 简体中文

### 1. 边界和数据流

```text
[Windows Spotify Desktop] ───────────────→ [Windows PC speakers/headphones]
       │ SMTC metadata + transport
       ▼
[Windows Companion / Python]
   ├── Spotify adapter: libspotifyctl candidate
   ├── Lyrics adapter: LRCLIB -> parse LRC -> select 2 lines
   ├── Artwork adapter: resize, compress, memory-bound cache
   ├── Playback clock/state: smooth interpolation and resets
   ├── UP-button state machine; validate command result
   └── Local WebSocket + HTTP server (token authentication)
              ⇅ 2.4 GHz Wi-Fi / same LAN
[AI Passport / ESP-IDF + LVGL]
   ├── Network client & reconnection
   ├── Render: artwork, song/artist, 2 lyrics, progress/time
   └── Debounced UP/OK/DOWN input events
```

**唯一的音乐音频通路**是 Spotify Desktop → Windows 现有输出设备；AI Passport 和 Companion 之间只传元数据、经过缩放的图片、同步文字、状态快照与控制事件。设备端**没有音频数据结构或媒体解码任务**。

### 2. Windows Companion

初选 Python 3.11+（具体最低版本以库实际兼容范围为准），独立模块：

- `spotify_adapter`: 首选 [libspotifyctl](https://github.com/ColdMeekly/spotifyctl)；文档称依托 Windows SMTC、窗口信息、Core Audio，提供标题、歌手、专辑、封面、位置/总时长、播放状态与 Play/Pause/Next/Previous/Seek。需测试实际 Python API、Spotify 版本及 SMTC 状态。不要把文档描述等同于已在本机验证。
- `lyrics_adapter`: 根据 `(title, artist, album, duration)` 查询 [LRCLIB](https://github.com/tranxuanthang/lrclib)，解析带时间戳的 LRC。匹配置信度不够则不显示假同步。做好超时/缓存/限速；歌词提供方需可替换。
- `cover_adapter`: 优先从本地 SMTC 缩略图读取，在 PC 端缩小为约 128–160px 方图，输出适于目标解码器的 JPEG；压缩体积与 RAM 峰值以真机实测决定，不在 MCU 端处理原始大图。
- `playback_clock`: 将主机播放位置、更新时间、播放/暂停状态组合成一致的进度。遇切歌、Seek、暂停、广告等立即失效/修正。设备端仅做短期进度插值。
- `control_service`: 执行三个逻辑按键，并维护 UP 的 2 秒窗口；拒绝不支持的命令，返回应答。
- `server`: 局域网 WebSocket 传消息，HTTP 提供经过处理的封面。控制和媒体快照共享同一服务状态。

### 3. 设备固件

- 基于 [官方 FOLOTOY 工程](https://github.com/FoloToy/ai-passport) 提供的目标板支持，先确认 ESP-IDF 版本、LVGL、驱动、分区、引脚、屏幕方向。
- 设备端负责 Wi-Fi 连接、WebSocket 客户端、HTTP 拉取封面、轻量 JSON 解析、LVGL 页面以及按键去抖。
- 网络任务与 UI 线程分离，所有 LVGL 更新在正确的 UI 任务/锁语义下执行；禁止从任意网络回调直接无保护地触碰 LVGL。
- 限制消息、字符串、图片及缓冲区上限；不得把完整高分辨率封面、多首歌曲/歌词或音频写入 RAM。
- 固件中绝不集成 Spotify OAuth、LRCLIB 查询、歌词匹配、音频编解码或媒体播放器。

### 4. 主要技术决策 (ADR)

| 编号 | 决策 | 原因 / 约束 |
| --- | --- | --- |
| A-01 | Windows 本地控制优先于 Spotify Web API | 用户只控制本机桌面端；避免 OAuth/云 API 依赖；但本地 SMTC 兼容性须测试 |
| A-02 | ESP-IDF + 官方 BSP + LVGL | 复用现有硬件驱动；版本和内存要实测 |
| A-03 | Wi-Fi WebSocket + HTTP 封面 | 双向控制与元数据、按需二进制图片；不用于传音频 |
| A-04 | Windows 端处理歌词和图片 | ESP32-C3 资源有限，避免复杂的 JSON/图像/歌词处理 |
| A-05 | UP 行为由 Companion 状态机负责 | 两秒双击跨网络一致性及 Seek 结果判断 |
| A-06 | 手动配置 Companion IPv4 + 配对令牌 | MVP 实现简单；mDNS 和自动发现留到后续 |
| A-07 | 只传当前状态，无历史资料库 | 减少内存和版权风险 |

### 5. 网络、安全与隐私

- 仅在**可信任的局域网**使用，不做公网端口映射。默认限制设备对等连接，Windows 防火墙只允许必要的私有网络端口。
- WebSocket 与封面 HTTP 请求需使用配对令牌；令牌来自设备配置/串口配对，不提交 Git，不在日志中回显。
- v0.1 局域网明文 WS/HTTP 的传输本身**不加密**，令牌不能替代 TLS；只适用可信 LAN，不宣称抵御同网恶意窃听者。
- 控制命令采用明确枚举、长度限制、基本认证和重放去重。无远程任意执行、文件系统浏览或通用键盘注入。
- 日志默认不记录歌词全文、Spotify 凭据、令牌。歌词和封面只在运行时短期缓存；不得打包到发行物。
- 处理第三方依赖许可、歌词使用与专辑图片的再分发限制；不将其默认视为可自由再许可素材。

### 6. 开发风险与备选方案

1. **Windows Spotify 元数据/Seek 行为**：先用 CLI/Python 验证 libspotifyctl；失败时评估直接 Windows SMTC 适配层，**不能假装功能已实现**。
2. **中文/Unicode 字库占用**：按需字形子集或字体资源分区，基于真实歌词测试。
3. **图片解码峰值内存**：限制 JPEG 尺寸/大小；若不稳定改为 RGB565 分块传输或更简化占位图方案。
4. **歌词错配、版本、服务限制**：严格匹配，缺失回退；不让歌词网络错误阻塞遥控器。
5. **连接中断、窗口失效、旧数据**：有心跳/超时，重新连接后请求完整快照和当前版本号。
6. **Spotify 广告/不可 Seek**：尊重适配层返回的可用能力，显示不可操作，不进行未约定的替代动作。

### 7. 外部项目

- https://github.com/FoloToy/ai-passport
- https://github.com/ColdMeekly/spotifyctl
- https://github.com/tranxuanthang/lrclib
- https://github.com/AmazingAndrew/pc-controller

具体复用代码前必须核查对应许可证，保留署名要求和许可证文件。

---

## English

### 1. Boundaries & flow

**Spotify Desktop → the PC's existing audio output is the sole audio path.** The Python Companion exchanges **metadata, compressed cover image, timed lyric snippets, playback status and commands** with the Passport over a trusted LAN. No audio streams, compressed music, DAC output, Bluetooth audio or device-side sound pipeline are present.

The Windows Companion bridges local Spotify state/controls (candidate: libspotifyctl), synced lyrics (candidate: LRCLIB) and cover conversion to an ESP-IDF + LVGL firmware UI.

### 2. Companion components

- **Spotify adapter:** evaluate `libspotifyctl` (SMTC/window state/Core Audio). Confirm exact Python API, cover format, seek support, player selection, and behavior of installed Spotify Desktop.
- **Lyrics adapter:** request timestamped LRC matched on title/artist/album/duration; parse timestamps; choose only current and next lyric lines; time out and fail closed on uncertain matches.
- **Artwork adapter:** rescale locally to roughly 128–160 px JPEG and serve only the current track; final pixel dimensions, compression and decoding memory are hardware-tested decisions.
- **Playback clock:** reconcile status, host timeline events, track changes and seek; use short local interpolation for smooth UI.
- **Control service:** validate three logical actions, execute host player commands and own the UP two-second window.
- **Network server:** WebSocket for commands/snapshots/lyrics, HTTP for resized cover, token authentication and reconnect state.

Python 3.11+ is an initial preference, not a validated dependency requirement.

### 3. Firmware components

Reuse official FOLOTOY board support, with board-specific pinout, ESP-IDF/LVGL version, flash partitions and panel driver verified before coding. Separate network callbacks from LVGL task context; bound all payloads and image allocations. Firmware only draws, connects, reports inputs and optionally interpolates progress. It must not authenticate to Spotify, query lyrics, download music or play audio.

### 4. Design decisions

- **A-01:** Prefer local Windows/SMTC integration over Spotify Web API for control of the PC's own playback.
- **A-02:** Use official BSP, ESP-IDF and LVGL, subject to hardware constraints.
- **A-03:** WebSocket + HTTP on local Wi-Fi: metadata, control and artwork only.
- **A-04:** Offload expensive lyric/image work to Windows.
- **A-05:** Keep UP double-press state on Windows to handle seek-success and time-window behavior consistently.
- **A-06:** Manual host IPv4 and pairing secret in MVP; no discovery requirement.
- **A-07:** Maintain only current-track state; avoid retaining or distributing content.

### 5. Security and privacy

Trusted private LAN only, never expose ports to the Internet. Require a pairing token for WebSocket and cover endpoints; do not commit/log secrets. Plain WS/HTTP is **not encrypted** and is therefore unsuitable for hostile shared networks. Validate command enums and sizes, rate limit and deduplicate event IDs. No shell-execution endpoint, filesystem exposure or general keyboard control. Respect attribution, code licenses, lyrics service terms and album-art rights.

### 6. Risks and fallbacks

Validate SMTC/Spotify/Seek on the PC first; if `libspotifyctl` fails, investigate a direct Windows SMTC adapter. Budget multilingual fonts and JPEG decoder RAM. Use a small cover or placeholder on failures. Never block controls on lyric lookup. Clear stale state on disconnect and fetch a full snapshot on reconnect. Respect unavailable controls during ads and other unsupported player states.

### 7. Upstream references

Official BSP, libspotifyctl, LRCLIB and PC Controller links are in section 7 above. Verify third-party licenses before copying source.
