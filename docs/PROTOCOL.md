# v0.1 局域网协议草案 / LAN Protocol Draft

**Version:** 0.1-draft · **Status:** design contract, not implemented / 设计协议，尚未实现

## 简体中文

### 1. 目的与通道

同一可信任局域网中，Windows Companion 提供：
- **WebSocket** `/ws`：设备与主机之间的状态/歌词/按键消息，UTF-8 JSON 文本帧。
- **HTTP GET** `/cover/{track_rev}.jpg`：设备按需拉取当前歌曲的小尺寸 JPEG。**绝不传音乐音频。**

主机地址在设备上手动配置，端口示例 `8765` 仅为约定的初始默认值，可修改。WebSocket 和 HTTP 均要求认证（例如 `Authorization: Bearer <paired-token>` 请求头）；令牌通过本地配置生成并注入设备，**不得放在仓库或 URL 查询字符串中**。MVP 暂用可信 LAN 的明文 WS/HTTP，并不提供公网安全保证。

### 2. 协议约定

- 所有消息都有 `type` 字段和 `v:1` 版本字段；不识别的类型/版本应拒绝或安全忽略。
- 文本以 UTF-8 编码。固定允许的按键枚举为 `up`、`ok`、`down`；**不得提供任意按键/系统命令执行接口**。
- `track_rev` 是 Companion 本次进程会话内递增的歌曲版本号，切歌即增加；重连时以最新状态为准。
- `position_ms` 和 `duration_ms` 为非负整数，0 ≤ position ≤ duration；若时长未知可设 `duration_ms:null`。
- 大于可配置上限的数据包、字符串、图片必须拒绝或截断；具体上限需在硬件测试后确定。
- `state` 是**完整快照**；`lyrics` 只为当前 `track_rev` 有效，旧版本必须丢弃。
- 服务端可发送 `ack` 通知按键结果；事件的 `id` 用于去重。重连**不得自动重放**未确认的非幂等按键操作。

### 3. 消息示例 (示例字段和歌曲均为虚构)

**设备 → Companion：握手**

```json
{
  "v": 1,
  "type": "hello",
  "device": "ai-passport",
  "name": "Passport Spotify Controller"
}
```

**Companion → 设备：欢迎/版本协商**

```json
{
  "v": 1,
  "type": "welcome",
  "server": "passport-companion",
  "track_rev": 12
}
```

**Companion → 设备：当前完整播放状态**

```json
{
  "v": 1,
  "type": "state",
  "track_rev": 12,
  "player": "spotify",
  "status": "playing",
  "title": "Example Song",
  "artist": "Example Artist",
  "album": "Example Album",
  "position_ms": 68000,
  "duration_ms": 192000,
  "capabilities": {
    "seek": true,
    "previous": true,
    "next": true,
    "play_pause": true
  },
  "cover_path": "/cover/12.jpg"
}
```

`status`：`playing`、`paused`、`stopped`、`disconnected`、`ad`（无法检测时可退化为常规状态）。不存在曲目时，`title`、`artist`、`album` 可为空字符串，`cover_path` 为 `null`。

**Companion → 设备：两行歌词更新**

```json
{
  "v": 1,
  "type": "lyrics",
  "track_rev": 12,
  "mode": "synced",
  "current": "Example current line",
  "next": "Example next line",
  "current_at_ms": 62000
}
```

没有同步歌词：

```json
{
  "v": 1,
  "type": "lyrics",
  "track_rev": 12,
  "mode": "none",
  "current": "",
  "next": "",
  "current_at_ms": null
}
```

不发送整首歌词给微控制器，主机只推送当前行与下一行。对 `lyrics` 消息做 track_rev 校验。

**设备 → Companion：物理按键事件**

```json
{
  "v": 1,
  "type": "input",
  "id": "passport-000042",
  "button": "up"
}
```

这里的 `up` 是**逻辑动作**，不是直接 Seek 或 Previous。Windows Companion 负责 2 秒状态机、实际媒体控制及结果验证。

**Companion → 设备：应答**

```json
{
  "v": 1,
  "type": "ack",
  "id": "passport-000042",
  "ok": true,
  "action": "seek_zero",
  "error": null
}
```

动作可为 `seek_zero`、`previous`、`play_pause`、`next`；失败时 `ok:false` 和简短 `error`，例如 `unavailable`、`not_connected`、`not_supported`。不得把异常堆栈或密钥传给设备。

### 4. 进度与歌词一致性

- 主机在切歌/暂停/恢复/Seek 时立即下发新 `state`。
- 播放期间建议约 **1 Hz** 状态/进度更新；设备可基于收到快照后的本地单调时钟做短时间插值，不依赖两端时钟绝对同步。实际频率需性能测量。
- Companion 用最新已确认的播放位置选取当前/下一句，在行切换时发 `lyrics`。
- 接收新 `track_rev` 后，设备先清空旧歌词/旧封面，再接收属于新版本的内容。
- 封面是 HTTP 二进制图片，与 WebSocket 控制 JSON 分开。HTTP 端需校验令牌、版本、响应大小和 Content-Type。
- 超时断开后 UI 标注离线，不将过时进度持续推进。重连先握手，主机立即发送全量快照及本曲歌词。

### 5. UP 双击控制状态机

维护：`armed_track_rev`、`armed_at_monotonic`，初始为未激活。
1. 有效 `up` 且**未处于同曲 2 秒窗口内** → 调用 Spotify Seek(0)；成功才进入窗口，并返回 `seek_zero`。
2. 有效 `up` 且**处于同曲 2 秒窗口内** → 调用 Previous，并清空窗口，返回 `previous`。
3. **2 秒从第一次有效按键在主机收到并成功执行后开始计时**。换歌、超时、断线立即清除。
4. Seek 不支持或失败时，应答 `not_supported` / `unavailable`，不得暗中发 Previous；窗口不激活。
5. 有限长度事件 ID 去重，避免网络重发造成“意外上一首”。对 `ok` 和 `down` 同样去重。
6. 当用户在 Windows 上改变歌曲时，重置窗口。处于暂停状态 Seek 不改变暂停状态。

### 6. 错误处理

- **设备离线**：按键不应排队待重连后执行。
- **认证失败**：拒绝连接或返回 401/403，不返回敏感内容。
- **封面失败**：设备显示占位图；状态和按键继续工作。
- **歌词缺失**：使用 `mode:none`；其他功能不受影响。
- **Spotify 关闭/广告/受限能力**：返回明确错误与当前能力信息，不伪造成功。

---

## English

### 1. Transport & trust model

On a **trusted local network**, the Windows Companion exposes **WebSocket `/ws`** for UTF-8 JSON state/lyrics/control messages and **HTTP `GET /cover/{track_rev}.jpg`** for resized album art. These channels **never carry music/audio**. Manually configure the host address. Port `8765` is an editable proposed default.

Both endpoints require a pairing token via the `Authorization: Bearer <paired-token>` header. Never commit/log it or place it in a URL query string. Plain WS/HTTP does **not encrypt** traffic and is suitable only for trusted LANs, not public Internet exposure.

### 2. Schema rules

All JSON messages have `v:1` and `type`. Reject unsupported versions and unsafe payloads. The only permitted button enum values are `up`, `ok`, `down`. No arbitrary command execution. `track_rev` monotonically increases per Companion process on track change; stale cover/lyric updates are ignored. Position and duration use milliseconds; position must be nonnegative and clamped to duration when known. Bound message, string and image sizes after measurement.

`state` is a full snapshot; `lyrics` is associated with a specific track revision. The device sends `input` with a unique event `id`; the Companion returns `ack` with action and result, deduplicating recent IDs. **Do not automatically retry non-idempotent controls on reconnection.**

### 3. Example messages

See the JSON examples in Chinese section 3: they are deliberately fictional and are the **shared v0.1 schema**, not two separate language-specific protocols.

- `hello` → `welcome`: identify device and negotiate v1.
- `state`: player status, title/artist/album, position/duration, capabilities and relative cover path.
- `lyrics`: two selected lyric strings (current and next), `mode:synced` or `mode:none`; never the full lyric file.
- `input`: `up | ok | down` with unique event ID.
- `ack`: confirm a concrete host action (`seek_zero | previous | play_pause | next`) or an explicit failure.

### 4. Timing and recovery

Send full state on track/seek/pause/resume changes and target ~1 Hz playback updates initially. The device may interpolate from receipt-time using its own monotonic clock, but must stop on pause/disconnect. Companion selects lyric lines from the latest player timeline and updates them at line boundaries. On track changes clear old art/lyrics immediately; discard stale revisions. HTTP artwork fetches validate token, revision and size. Reconnect always triggers a fresh snapshot and lyric pair. Offline controls are dropped, **not replayed later**.

### 5. UP state machine

Companion maintains the armed track revision and a monotonic timestamp. First UP invokes **Seek(0)**; only success arms a **2-second** window. A second UP on the **same track** in that window invokes Previous and disarms. Timeout, track changes, and disconnect disarm. No hidden Previous fallback if Seek(0) fails. Host-side timer starts after successful first command. Debounced device events and server-side ID deduplication prevent accidental duplicate commands. Seeking while paused must not force playing.

### 6. Failures

Disconnected devices queue no future commands. Reject invalid authentication. Failed cover shows placeholder; unavailable lyrics use `mode:none`. When Spotify is closed, playback is restricted, or capabilities are missing, acknowledge failure rather than falsely claiming success.
