# Codex-Micro Controller

本地 Controller 将 FPGA 串口事件转换成桌面端快捷键，并提供 `127.0.0.1` REST API。

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 冒烟模式

不连接 FPGA、不发送真实快捷键：

```powershell
.\run_controller.ps1 -DryRun -NoSerial
```

打开 <http://127.0.0.1:8765/v1/health> 应返回：

```json
{"ok": true}
```

## 正常运行

板载 UART 在 Windows 中枚举为 CH340，当前默认端口为 `COM5`：

```powershell
.\run_controller.ps1 -SerialPort COM5
```

默认 SW0 使用 `Enter` 发送普通输入框内容。若在桌面端把“Send message”绑定为 `Ctrl+Enter`，可以改用：

```powershell
python main.py --serial-port COM5 --send-hotkey ctrl-enter
```

这是更安全的配置，因为快捷键表中的 `Enter` 也用于“Approve request”。

如果重新插拔后端口号变化，在设备管理器查看新的 `COMx`。

## 操作

- 选择状态短按 K0~K3：首次打开已绑定会话；再次短按同一键最小化 ChatGPT/Codex，切换到其他会话键则直接打开对应会话。
- 选择状态长按 K0~K3：SW7 向下时绑定当前桌面会话；SW7 向上且对应状态为4时，播报该会话最后一次完成回复。
- 短按 K4：切换选择/操作状态。
- 操作状态长按 K4：删除当前槽位并返回选择状态。
- 操作状态 K0：按住/释放 Right Alt。
- 操作状态 K1：Backspace；K2：右方向键；K3：左方向键，均支持按住连续移动。
- 必须先用 K4 进入操作状态，并让 ChatGPT/Codex 输入框获得焦点。
- 操作状态将物理 SW0 从下拨到上：获取当前 session ID、自动占用空槽并发送 Enter。

## REST API

```text
GET    /v1/health
GET    /v1/slots
POST   /v1/mode
POST   /v1/sync
POST   /v1/slots/0/bind
POST   /v1/slots/0/activate
POST   /v1/slots/0/status
DELETE /v1/slots/0
```

示例：手工绑定测试槽位，不操作桌面端。

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8765/v1/slots/0/bind `
  -ContentType application/json `
  -Body '{"session_id":"test-1","deeplink":"codex://test-1"}'
```

设置完成状态会向 FPGA 发送状态4，并只在首次进入状态4时发送一次 120ms 蜂鸣命令：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8765/v1/slots/0/status `
  -ContentType application/json `
  -Body '{"status":4}'
```

## 自动状态监测

状态源按以下优先级处理：

1. Codex 会话 JSONL 日志（文件优先）
2. ChatGPT/Codex 左侧会话列表 UI Automation（兼容降级）

对于 `codex://threads/{id}` 会话，Controller 会只读监测
`%USERPROFILE%\\.codex\\sessions` 下以该 session ID 结尾的 rollout JSONL 文件：

- `task_started` -> 执行中（2）
- `task_complete` -> 完成（4）
- `turn_aborted` -> 错误/中止（5）

文件状态被识别后，该槽位的 UI 图标不会覆盖文件状态。读取失败、文件不完整或找不到生命周期事件时不会猜测为完成；`GET /v1/slots` 中的 `status_source` 会显示 `file` 或 `ui`。

可用 `--session-log-root` 指定日志目录，或用 `--no-session-log-monitor` 关闭文件监测。文件监测只读 JSONL，不读取 Cookie、缓存数据库或私有网络接口。

正常启动时，Controller 会通过 Windows UI Automation 读取 ChatGPT 左侧会话列表：

- 会话项右侧的圆环识别为执行中（2）。
- 会话项右侧的蓝点识别为已完成（4），只对本次发送后经历过执行态的槽位生效，并鸣叫一次。
- 如果 ChatGPT 版本很快把蓝点收回为时间，且只有一个槽位仍处于执行中，连续两次看到该标题全部变为空闲时间后也判定为完成。
- 多个运行槽位、同名状态混杂或无法唯一对应时不会猜测完成；对应槽位会保持执行中或显示未知（6）。
- 状态图标没有无障碍文字时，程序只在该会话项自己的图标区域取屏幕像素，不点击、不滚动、不使用绝对坐标。

如果 ChatGPT 版本改变了会话列表的图标结构，可以用 `--no-status-monitor` 暂时关闭自动监测，手工调用状态 API；程序不会用弹窗作为唯一完成依据。

## 安全行为

- deeplink 打开后重新复制 session ID 并校验，失败时不发送操作键。
- 串口断开自动重连。
- 默认只在串口连接时向 FPGA 同步状态；需要覆盖 FPGA 重配置后的状态丢失时，可调用 `/v1/sync`，或用 `--sync-interval 10` 开启低频同步。
- 只读记录 ChatGPT/Codex 主窗口进程 ID；检测到桌面端重启后，下一次硬件事件会清空四个槽位并回到选择状态。
- 程序退出时释放 Right Alt、Backspace、Left、Right，避免按键卡住。

## 语音播报

语音播报只对带本地 Codex rollout JSONL 的会话生效。Controller 从最新
`task_complete.last_agent_message` 读取回复，并调用 Windows 离线 SAPI；优先选择
`zh-CN` 的 `Microsoft Huihui Desktop` 语音。播报前会移除 Markdown、代码块、
链接和 URL，避免把格式符号逐字念出。输入以 UTF-8 传给 PowerShell，播报在线程
中执行，不阻塞串口和按键。可用 `--no-speech` 关闭。
- ChatGPT/Codex 桌面端目前没有公开的会话状态 API；本控制器不会读取私有接口或用坐标点击猜状态。列表状态读取失败时使用状态6或保留当前状态，不误报完成。

## 桌面端边界

桌面端控制使用公开的应用快捷键、复制 session ID/deeplink 和 `codex://` 打开链接。列表监测依赖 ChatGPT 当前公开的无障碍树和会话列表视觉状态；若需要官方、完全确定的完成事件，需将会话改由 OpenAI API 后端托管，那是独立会话，不是 ChatGPT 桌面端当前会话。
