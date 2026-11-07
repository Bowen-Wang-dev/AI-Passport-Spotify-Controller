# 开发约定 / Development Guide

**Status:** M1 local Companion validation code added; other milestones remain planned / 已加入 M1 本地 Companion 验证代码；其他里程碑仍为规划

M1 安装、CLI、Mock/真实测试和限制见 [companion/README.md](../companion/README.md)。开发规范与产品范围不变。 / See [companion/README.md](../companion/README.md) for M1 installation, CLI, Mock/actual tests and limitations. The development rules and product scope remain unchanged.

**2026-11-07 阶段交付 / Interim submission:** 已完成、未完成、本轮修改和测试证据见 [SUBMISSION_STATUS.md](SUBMISSION_STATUS.md)；M1 进行中，未完整验收。 / See the report for implemented work, gaps, changes and verification; M1 remains in progress, not fully qualified.

## 简体中文

### 1. 仓库结构（M1 已实现，其余为计划）

```text
AI-Passport-Spotify-Controller/
├── README.md
├── docs/
│   ├── PRODUCT_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── PROTOCOL.md
│   ├── ROADMAP.md
│   └── DEVELOPMENT.md
├── companion/                # M1：本地 Windows Python CLI，无网络服务
│   ├── src/
│   └── tests/
├── firmware/                 # 未来：ESP-IDF / LVGL 应用
├── tools/                    # 未来：开发/测试辅助工具
└── .github/workflows/        # 未来：静态检查和构建
```

**M1 已新增 `companion/` 本地实现与测试**；`firmware/`、`tools/` 和 CI 目录仍是规划。其他命令和产物仅在对应里程碑实现后才标为可用。

### 2. 开发环境建议

- Windows 10 1809+ 或 Windows 11，Spotify Desktop，Python 3.11+（以真实依赖兼容测试为准）。
- AI Passport + USB-C 数据线，能运行官方刷机/恢复过程。
- ESP-IDF 与 LVGL 采用官方 BSP 的兼容版本，不直接使用未经测试的最新版。
- 同一可信局域网；Windows Companion 的 IPv4 地址以及设备本地配对令牌。
- 常用 IDE 可用 VS Code + Python + ESP-IDF 扩展，**不依赖 Arduino**。

### 3. 研发原则

1. **先 Windows 后固件**：必须先验证 Spotify 信息、封面、Seek(0)、逐行歌词可用，避免盲目开发 UI。
2. **逐步可测**：M1 本地 CLI/模拟设备测试 → M2 假数据真机渲染 → M3 协议联调 → M4 稳定性发布。
3. **单一职责**：Companion 获取/处理数据、执行业务逻辑；Passport 只显示、网络和按键。
4. **绝无设备音频路径**：禁止在代码中新增音乐流、MP3/AAC 解码、扬声器输出、麦克风采集、Spotify Connect 接收。
5. **安全默认值**：仅在可信 LAN 开放控制端口。密码/配对令牌写入本地忽略文件或安全配置，不提交到 Git；避免令牌出现在日志/URL。
6. **第三方许可**：在使用外部源代码前记录版本、许可证、署名与必要的许可证副本；封面、歌词不提交到仓库。
7. **中英双语**：主要功能与技术设计文档必须保持简体中文和英语版本语义一致。代码标识符和协议字段统一使用英文。
8. **禁止夸大进度**：未在 Windows/设备真实测试通过的功能，文档标记为“提议/未验证”。

### 4. 代码质量与测试约定（实施时）

- Python：类型标注、日志级别、网络/Spotify/LRCLIB 错误边界、可替换的适配器、确定性单元测试。
- C / ESP-IDF：检查返回码、限定分配/缓冲区、按键去抖、网络/GUI 线程安全、不阻塞 LVGL UI。
- 协议：版本校验、显式 JSON Schema 思路、最大长度、错误码、过期状态过滤、事件 ID 去重。
- 测试：用**原创虚构歌词**及自制/可许可的测试封面，禁止把真实受版权保护的歌词样本打包进仓库。
- 记录设备芯片/flash/显示屏、BSP、ESP-IDF、Python、Spotify 版本以及测试结果；不从“编译成功”推断“真机可用”。

### 5. 推荐首个开发任务（M1）

在 `companion/` 构建**仅本地运行**的 Python 验证程序，能够输出歌曲元数据、当前播放位置、播放状态、封面字节是否存在、LRCLIB 的两行同步歌词，并能以三个命令模拟 UP/OK/DOWN；实现 UP 两秒状态机。通过后再引入网络，不要先写固件。

**本地 Companion 安装和测试命令见其 README；仍不提供固件刷机命令，因为本轮没有固件。**

### 6. 变更管理

需求改动先修改 `PRODUCT_SPEC.md`；影响架构时更新 `ARCHITECTURE.md`；影响消息结构时更新 `PROTOCOL.md`；工作完成时同步 `ROADMAP.md`。建议采用小型可审查提交和清晰的测试结果，避免在一个 PR 中同时引入未经验证的 Windows 与固件复杂功能。

---

## English

### 1. Proposed layout

The tree above describes the original intended layout. **M1 now includes local `companion/` code and tests**; `firmware/`, `tools/` and `.github/` remain planned. Do not mistake those proposed directories for implemented code.

### 2. Suggested environment

Windows 10 1809+ or Windows 11 with Spotify Desktop; Python 3.11+ as a starting preference (confirm dependency compatibility). FOLOTOY AI Passport, data-capable USB-C cable, official flash/recovery path, official BSP-compatible ESP-IDF/LVGL. Same trusted private LAN and a pairing secret. VS Code plus Python / ESP-IDF tools is a good fit; **Arduino is not required**.

### 3. Working rules

1. **Windows first**: demonstrate local Spotify metadata, cover art, Seek(0), and timestamped lyrics before investing in the firmware.
2. **Test incrementally**: M1 local CLI/mocks, M2 real board with fake data, M3 actual protocol and playback, M4 hardening.
3. **Separate responsibilities**: Windows owns data and button semantics; Passport owns UI and physical inputs.
4. **Zero audio on device**: never add streaming, music decoding, speaker output, microphone capture or Spotify Connect reception.
5. **Secure configuration**: LAN-only service; exclude pairing tokens from source control and logs; do not place them in URL parameters.
6. **Respect external licenses**: pin dependency versions and preserve required attributions; do not commit actual copyrighted lyrics or album art.
7. **Maintain both languages**: Simplified Chinese and English product/technical documentation should remain meaningfully aligned; code identifiers and protocol keys use English.
8. **Truthful status**: clearly distinguish plans, builds and real-device test results.

### 4. Quality and tests

For Python, use type hints, structured diagnostics, adapters and deterministic tests. For ESP-IDF, validate return codes, set memory and message limits, debounce inputs and update LVGL from the correct task. Validate protocol versions, payload sizes, errors, stale revisions and event-ID deduplication. Use self-authored fictional lyrics and licensed test artwork. Record exact PC/player/toolchain/board versions and results. A successful compile is not a hardware validation.

### 5. First implementation task (M1)

Implement a **local-only** `companion/` Python probe that reads current player metadata/status/position/art availability, matches two LRCLIB lyric lines, and allows simulated UP/OK/DOWN with the exact two-second UP state machine. Add network features only after this passes.

**Local Companion installation and test commands are in its README. There are still no firmware flashing steps because firmware is outside this milestone.**

### 6. Change process

Change the product spec before scope changes; update architecture for technical decisions, protocol for wire changes, and roadmap when gates are met. Prefer small, reviewable commits with evidence of real tests.
