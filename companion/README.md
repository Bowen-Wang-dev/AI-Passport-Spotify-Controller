# M1 Windows Companion — 本地验证 / Local validation

## 简体中文

### 范围与状态

只在 Windows PC 上读取 Spotify Desktop 信息、查询两行同步歌词、缩小封面，以及模拟 UP / OK / DOWN。不包含固件、设备端逻辑、WebSocket/HTTP 服务、音乐下载或音频播放代码。**所有音乐仍由 Windows Spotify Desktop 播放。** `--mock` 完全离线，不证明真实 Spotify 可用。

**2026-11-07 阶段提交更新：** 本地源码已初始化 Git，并连接指定 GitHub 仓库、保留原远端提交历史；提交和推送状态以 Git 记录为准。已完成、未完成、本轮修改及验证证据见 [阶段提交说明](../docs/SUBMISSION_STATUS.md)。未发布正式版本或关闭 Issue #1。产品/架构/协议不变；ROADMAP 将 M1 如实标为进行中，不把验收关卡自动标为通过。下方 2026-11-05 记录中的“没有 Git”是当时的历史状态，不代表当前状态。

### 安装与固定依赖

Windows 10 1809+ / Windows 11、64 位 x64 Python 3.11+、Spotify Desktop。实际验证的 Python/Windows/Spotify 版本和结果见末尾记录。ARM64、32 位 Python 及所有其他 Python 版本的真实集成未验证。非 Windows 可安装并执行 Mock 测试，但不提供非 Windows Spotify 支持。

从项目根目录，在 PowerShell 运行（无需激活脚本）：

```powershell
Set-Location .\companion
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m passport_companion --no-lyrics doctor
```

没有 Python 3.12 时可选择已安装的 3.11+，但需自行验证对应运行时。直接依赖固定为 `libspotifyctl==0.3.4`（Windows x64）、`Pillow==12.0.0`、测试依赖 `pytest==8.4.2`；HTTP 使用 Python 标准库，无需 Spotify OAuth 或 LRCLIB API key。发布的 Windows wheel 自带 DLL；DLL/系统运行库载入失败会明确失败，不静默改为全局媒体键。

### CLI

全局选项放在子命令**之前**。安装后也可使用 `.\.venv\Scripts\passport-companion.exe`。

```powershell
# 当前元数据、进度、封面转换状态、当前/下一句歌词
.\.venv\Scripts\python.exe -m passport_companion status
# 不请求歌词；diagnostics 不输出歌曲名或歌词正文
.\.venv\Scripts\python.exe -m passport_companion --no-lyrics --json doctor
# 实时监视；Ctrl+C 结束
.\.venv\Scripts\python.exe -m passport_companion watch
# Windows 真实终端交互：U=UP，O/空格=OK，D=DOWN，Q=退出
.\.venv\Scripts\python.exe -m passport_companion watch --interactive
# 同一进程内两次 UP；默认相隔 0.1 秒
.\.venv\Scripts\python.exe -m passport_companion press up up
# 超时示例：两次 Seek(0)，不是 Previous
.\.venv\Scripts\python.exe -m passport_companion press up up --gap 2.1
# 离线演示，无外部请求和实际 Spotify 控制
.\.venv\Scripts\python.exe -m passport_companion --mock --json status
.\.venv\Scripts\python.exe -m passport_companion --mock press ok down
```

每次控制显示实际动作、成功/失败和错误原因。`status`/`doctor`/`press` 失败退出码 1，非法参数为 2；`watch` 在断开时继续监视并显示不可用。JSON 输出为一行一个对象。`watch --count 8 --interval 0.25` 提供有限次轮询；只有状态变化才打印。

**两个独立 `press up` 进程不共享双击窗口。** 使用 `press up up` 或持续运行的交互 watch。40 ms 同按钮去抖；成功确认 Seek(0) 后才开始计时，第二次有效 UP 在 **0–2.000 秒（含边界）**同曲窗口内调用 Previous；超时重新 Seek。切歌、连接代次变化、Seek 失败均撤销窗口。暂停 Seek 不调用 Play；若上游意外恢复，会尝试重新 Pause 并报告失败。

### 模块与失败语义

- `models.py`：不可变歌曲、快照、能力、控制结果，以及可替换 `SpotifyAdapter` Protocol。
- `spotify.py`：仅使用已核查的 libspotifyctl 0.3.4 API：`SpotifyClient.start/close/latest_state`、`position_smooth_ms`、`play/pause/next/previous/seek_ms` 及生命周期/切歌回调。读取标题/歌手/专辑、毫秒位置/时长、`album_art` 字节和能力。
- `buttons.py`：独立业务状态机，monotonic 时钟可注入；没有网络逻辑和隐藏 Previous 回退。
- `lyrics.py`：LRCLIB `/api/get` 严格匹配标题/歌手/专辑/时长，解析 LRC，按最新位置选择两行；有界内存缓存、请求超时、限速与错误回退。缺失、超时、错配不是同步歌词。歌词网络查询位于独立单线程 worker，不阻塞按键路径；旧歌曲结果会被丢弃。
- `artwork.py`：PC 上处理为 160×160（可设 128×128）JPEG；缺失、损坏和超限返回明确回退。压缩输入 ≤4 MiB、解码 ≤16M 像素、JPEG 输出 ≤64 KiB；处理 EXIF 方向、透明度和 RGB 转换，不在磁盘缓存。
- 歌词边界：响应默认 ≤1 MiB（配置最大 4 MiB），元数据每字段 ≤512 字符；LRC ≤262,144 字符、每行 ≤4,096 字符、≤8,192 行及 ≤10,000 时间事件。LRU 默认 64 条（最大 256）；正结果/无歌词/失败缓存默认 3,600/120/5 秒。429 完整遵守数值或 HTTP-date `Retry-After` 并增加 jitter；不可表示的有效超长值保守禁用本进程请求，不提前重试。
- `service.py` / `cli.py`：本地编排和验证界面。使用最新 SMTC 平滑位置重新选择歌词，暂停停止推进，Seek/主机拖动会重新定位；不使用独立的猜测歌词时钟。
- `mock.py`：确定性内存播放器；测试素材是原创虚构文本及内存生成图片。

**重要上游事实：** 0.3.4 原生 SMTC `Play/Pause/Next/Previous/Seek` 调用发出异步请求后就可能返回 `true`，没有等待最终 Windows 操作结果。因此这里把返回值视为“已发送”，还需在有限时间内观察并稳定确认对应状态/位置/曲目变化；仅回调版本号增加不足以证明 Next/Previous 成功。超时返回 `confirmation_timeout`，不是伪造成功。暂停 Seek 必须仍暂停。Seek(0) 已经在 0:00 时是幂等操作，不能凭这一场景证明实际移动能力；真实测试先移至 5–6 秒再回零。

### 测试

```powershell
# 默认运行：所有离线测试；真实集成自动 skip
.\.venv\Scripts\python.exe -m pytest -q
# 明确只跑 Mock/离线单元测试
.\.venv\Scripts\python.exe -m pytest -m 'not integration' -q
# 真实只读集成：先打开 Spotify 并选择普通歌曲（有封面）
$env:PASSPORT_RUN_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest tests\test_windows_integration.py -m 'integration and not controls' -q
# 有副作用：真实 Play/Pause/Next/Previous/Seek 与 UP；请勿和手动操作并行
$env:PASSPORT_RUN_CONTROLS = '1'
.\.venv\Scripts\python.exe -m pytest tests\test_windows_integration.py -q
Remove-Item Env:PASSPORT_RUN_INTEGRATION, Env:PASSPORT_RUN_CONTROLS
```

真实控制测试会短暂切歌/播放；在 `finally` 中尽力恢复原先播放/暂停状态，并且仅在仍是原始歌曲时恢复原先进度。队列、随机播放、重复模式、相邻同名歌曲或人为并发操作可能使原曲无法恢复；不要把此测试当作无副作用诊断。真实 Spotify 不可用时不会以 Mock 代替通过。

### 已知限制与后续验收

- 无固件、服务端口、设备 UI 或端到端设备验收；本实现不构成 v0.1 产品发布。
- libspotifyctl 不暴露独立的 `can_play/can_pause`，对应候选能力由当前状态推断，必须以实际调用/观察结果为准；广告禁用控制，不偷偷尝试替代命令。
- 上游没有稳定 Spotify 曲目 URI/实例 ID；版本号、连接代次和元数据用于失效处理。相邻完全相同元数据的不同曲目可能无法区分，Next/Previous 可能诚实地报告确认超时。时间线和元数据由不同上游事件更新，已加入短稳定窗口降低过渡态误判，但不能提供平台原子性保证。
- 无曲目或未知时长时不假同步歌词；多歌手标注、remaster/live 版本等严格不匹配会回退。LRCLIB 仅在运行时访问；不承诺每首歌曲都有歌词，不记录/再分发整首歌词或封面。
- 网络设置 socket 超时并在读取间检查预算，但不能保证 DNS 查询/持续缓慢响应的严格总墙钟截止时间。`status` 的歌词等待上限不等于整个进程的退出上限；关闭时已经运行的 worker 仍可能等待网络结束。按键不会因此阻塞，但歌词和退出可能延后。
- 暂未在真实广告、Spotify 完全退出/重启、Windows 睡眠唤醒或长期运行中完整验收；广告/连接重置/不可用等边界有 Mock 测试，睡眠和长期稳定性尚待验证，不能宣称对应实机测试通过。
- 真实 Spotify 行为依赖本机版本、SMTC 会话和队列。目标最低 Windows/Python 版本尚待矩阵验证。后续先独立审查本地结果，再决定是否更新 M1 ROADMAP；不自动推进 M2/M3。

## English

### Scope and installation

M1 is a **local-only Windows validation tool**: Spotify metadata/transport, two synced lyric lines, small JPEG artwork, and simulated UP/OK/DOWN. There is no firmware, network server, device implementation, music download, or audio playback path. **All music continues to play in Windows Spotify Desktop.** Mock mode is offline and does not validate real Spotify.

Use x64 Python 3.11+ on Windows 10 1809+ / Windows 11 and run the PowerShell installation commands above from the project root. Tested versions are recorded below; other Python versions, ARM64 and minimum Windows versions are not certified. Pinned direct dependencies are **libspotifyctl 0.3.4**, **Pillow 12.0.0**, and **pytest 8.4.2**. HTTP uses the standard library. No OAuth or LRCLIB key is needed; load failures are explicit. As of 2026-11-07, the local copy is connected to the designated GitHub repository with its original history preserved; Git records determine commit/push status. See the [interim submission report](../docs/SUBMISSION_STATUS.md). No product release or issue closure is claimed. The 2026-11-05 no-Git note below describes the historical state only.

### Commands and semantics

The shared PowerShell examples above are runnable commands. Global options precede the subcommand. `status` displays metadata, position, art-processing status and the current/next lyric lines. `doctor` reports runtime/dependency versions and availability without track names or lyric bodies. `watch` polls live changes; `watch --interactive` uses a real Windows console with **U=UP, O/space=OK, D=DOWN, Q=quit**. `press up up` shares one state machine; separate CLI processes do not share an UP window. `--json` emits JSON lines and `--mock` performs no network/player I/O. Failure exit codes are 1 (runtime/control) and 2 (arguments); watch keeps running through disconnects.

UP has a 40 ms per-button debounce. Only an observed successful Seek(0) arms a **two-second inclusive window**, measured with a monotonic clock after confirmation. The second valid press on the same track calls Previous and disarms; timeout, track/connection changes and seek failure clear it. No Previous fallback exists. Paused seeking does not call Play; unexpected resume triggers a best-effort Pause restoration and an explicit failure.

The modules listed in the Chinese section isolate data contracts, native integration, buttons, lyrics, artwork, orchestration and the CLI. Native `true` means dispatch, not a proven result: upstream 0.3.4 does not await Windows' asynchronous transport outcome. The adapter therefore waits for an observed, briefly stable state/timeline/metadata change and reports `confirmation_timeout` otherwise. A track callback alone is not skip success. Real seek validation first moves away from zero. Native smooth position, rather than a guessed lyric clock, drives line selection after pause/resume, skips and host seeks.

Lyrics use strict normalized title/artist/album/duration matching against LRCLIB `/api/get`, a bounded in-memory cache, sequential identified requests and explicit no-match/network/rate-limit fallbacks. A single background worker keeps network I/O off the control path and discards obsolete-track results. Artwork is processed only on the PC to 160×160 or 128×128 JPEG: compressed input is limited to 4 MiB, decoded images to 16M pixels and output JPEGs to 64 KiB. Lyric responses default to 1 MiB (maximum configurable 4 MiB); each metadata field is limited to 512 characters. LRC limits are 262,144 characters, 4,096 per line, 8,192 lines and 10,000 events. The LRU defaults to 64 entries (maximum 256), with default positive/no-lyrics/failure TTLs of 3,600/120/5 seconds. Numeric and HTTP-date Retry-After delays are fully respected with jitter; unrepresentably large valid delays conservatively disable requests for the process. No real lyrics or cover files are included in the repository.

### Tests and limitations

Use the shared pytest commands above. Default tests skip real integration; `-m 'not integration'` explicitly runs offline tests. Actual Windows tests require `PASSPORT_RUN_INTEGRATION=1`; mutating transport tests additionally require `PASSPORT_RUN_CONTROLS=1`. Open Spotify on an ordinary track with cover art and avoid concurrent manual controls. Tests exercise real seeks from nonzero positions, paused seeking, UP timeout/double-press and transport actions. They attempt to restore the original status and, only on the original track, its position. Queue modes, identical-metadata tracks and concurrent operations can prevent restoring the original selection. Mock results never stand in for a real pass.

No device or end-to-end v0.1 validation is claimed. Play/pause capability is inferred because upstream does not expose independent capability flags. Stable track IDs are unavailable; identical metadata can make skips unverifiable. Metadata and timeline updates are not atomic; brief stability checks reduce but cannot eliminate transient observations. Strict lyric matching may reject multi-artist/version variants and unknown duration; missing lyrics remain an explicit fallback. Socket timeouts and between-read budget checks do not enforce a hard total deadline for DNS or trickle responses. The lyric wait limit in `status` is not a process-exit limit: an already-running worker may delay shutdown until its request ends, without blocking button controls. Actual ads, full Spotify exit/restart, sleep/resume, long-duration operation and the minimum platform matrix still require testing; only the relevant ad/connection/unavailable boundaries have Mock coverage, not sleep or soak qualification. Review local evidence before changing the M1 roadmap; M2/M3 are not implemented.

## 实测记录 / Verification record

### 2026-11-05

- Windows: Microsoft Windows 11 Pro, build **10.0.26300**, x64; Python **3.12.10**.
- Spotify Desktop product version: **1.3.6.1921**; dependencies: **libspotifyctl 0.3.4**, **Pillow 12.0.0**, **pytest 8.4.2**.
- 最终默认测试 / Final default suite: **246 passed, 2 skipped** (0.81 s). 两项 skip 是未选择真实运行时的集成测试，不计作通过 / The skips are opt-in real integration tests, not passes.
- 显式真实 Windows 集成 / Explicit actual Windows suite: **2 passed** (8.04 s), with both integration/control environment flags enabled. Metadata/title/artist/album, status, position/duration, cover bytes and 160×160 JPEG, Play/Pause/Next/Previous, UP timeout/double-press, nonzero-to-zero Seek in **playing and paused** states were observed; paused Seek stayed paused.
- 真实 CLI / Actual CLI: `doctor` reported all required metadata flags and successful JPEG conversion; installed entry-point `watch` showed advancing positions **7014 → 7131 → 7239 ms** while playing. These are real Windows observations, not Mock output.
- 真实 LRCLIB 请求 / Live LRCLIB lookup: current-track result **`none`**, with empty current/next fallback and working control/art paths. **A successful real synced-lyrics match was not demonstrated.** LRC parsing, positioning, mismatch/no-lyrics/network failures and rate-limit handling passed offline tests using original fictional text.
- 初次真实控制测试暴露过渡态误判；已修复为稳定元数据确认，添加回归测试后真实控制通过 / The initial real control test exposed transient-metadata confirmation; fixed with stable observations, new regression tests and a passing real rerun.
- `pip check`: **No broken requirements found**; `compileall`: passed; editor Problems: **No errors found**. All **17** Python files also parsed with Python 3.11 grammar; **this is not a Python 3.11 runtime/integration test**.
- 本地 Git 三项命令均明确返回 `not a git repository`；远端最近提交只作上下文参考：`02732f628081bdfeb4d93efb4f2758ee8409b9ed`（2026-11-05，documentation bootstrap），不能据此声称本地分支或基线一致 / Local Git commands returned `not a git repository`; the remote commit is context only, not proof of the local branch/baseline.
- 保持 M1 关卡待验收，不更改 ROADMAP。后续需要真实可匹配的同步歌词示例、退出/重启/广告与长期稳定性验证及独立代码审查 / M1 remains unqualified in ROADMAP pending a real synced match, restart/ad/soak checks and independent review.

### 2026-11-07 — 阶段提交复核 / Interim submission check

- 当前 Python **3.12.10** 虚拟环境初次缺少 pytest；按已有 `.[test]` 安装依赖后，默认测试 **246 passed, 2 skipped (0.90 s)**。两项 skip 为未开启真实 Windows 集成，不计作通过。
- `pip check`：**No broken requirements found**。Mock JSON `status` 和 `press up up` 均退出码 0；后者依次返回 `seek_zero`、`previous`，均 `ok: true`。
- 本次未控制真实 Spotify、未查询真实歌词、未验证设备；2026-11-05 的真实 Windows 结果仅作为已有历史记录保留。 / Real Spotify, live lyrics and hardware were not revalidated; the 2026-11-05 real-Windows evidence remains historical.
- 本轮只整理阶段交付文档、状态和忽略规则，不新增产品功能；详情见 [阶段提交说明 / Submission report](../docs/SUBMISSION_STATUS.md)。

## 上游 API 核查 / Upstream API verification

- [Issue #1: M1 scope and acceptance](https://github.com/Bowen-Wang-dev/AI-Passport-Spotify-Controller/issues/1)
- [libspotifyctl 0.3.4 Python source and public signatures](https://github.com/ColdMeekly/spotifyctl/blob/v0.3.4/bindings/python/libspotifyctl/__init__.py)
- [libspotifyctl 0.3.4 SMTC asynchronous dispatch implementation](https://github.com/ColdMeekly/spotifyctl/blob/v0.3.4/src/smtc_source.cpp)
- [libspotifyctl 0.3.4 transport selection](https://github.com/ColdMeekly/spotifyctl/blob/v0.3.4/src/client_win32.cpp)
- [LRCLIB official API documentation](https://lrclib.net/docs)
- [LRCLIB metadata query implementation](https://github.com/tranxuanthang/lrclib/blob/main/server/src/routes/get_lyrics_by_metadata.rs)

核查上游接口并独立编写适配逻辑，没有复制或捆绑第三方项目源码。已安装包元数据显示 libspotifyctl 使用 MIT、Pillow 12.0.0 使用 MIT-CMU、pytest 使用 MIT；再分发依赖前仍须核对上游 LICENSE 和分发包的许可证文件。本仓库自身许可证仍未选定，不能据此推定授权。歌词和封面权利属于相应权利人，运行时处理不意味着允许再分发。

The adapter is independently implemented against verified APIs; no upstream source is vendored. Installed metadata identifies libspotifyctl and pytest as MIT and Pillow 12.0.0 as MIT-CMU; upstream LICENSE files and distribution notices still need review before redistribution. This does not choose a license for this repository. Runtime lyric/art handling does not grant redistribution rights.
