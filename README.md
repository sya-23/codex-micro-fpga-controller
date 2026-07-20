# Codex Micro FPGA Controller

An open-source FPGA control panel for Codex/ChatGPT desktop workflows. The
hardware handles keys, switches, LEDs, a four-digit seven-segment display and
a buzzer; a Windows controller bridges UART events to desktop actions and
local session status.

> This is an independent educational project. It is not affiliated with or
> endorsed by OpenAI or Work Louder.

## Features

- Four bindable conversation slots on K0-K3.
- K4 switches between conversation selection and operation modes.
- File-first Codex status monitoring through local rollout JSONL events:
  `task_started`, `task_complete` and `turn_aborted`.
- Conservative Windows UI Automation fallback when no Codex log is available.
- Press a bound slot once to open it; press the same slot again to minimize
  Codex/ChatGPT without closing the application.
- Hold K1 for repeated Backspace; hold K2/K3 for repeated cursor movement.
- SW0 sends the current message.
- Four-digit status display, eight status LEDs and completion buzzer.
- Local REST API on `127.0.0.1:8765`.
- Permanent SPI Flash programming script and a verified bitstream.

## Hardware

- FPGA: Anlogic `EF2L15LG100B`
- Clock: 50 MHz
- Keys: K0-K4
- Send switch: physical SW0 on `P37`
- UART: RX `P83`, TX `P84`, 115200 baud
- Buzzer: `P53`
- LEDs: `P38/P39/P40/P41/P42/P43/P45/P47`
- Four-digit seven-segment display: see `fpga/codex_micro.adc`

Display states:

| Value | State |
| --- | --- |
| 0 | Empty |
| 1 | Idle |
| 2 | Running |
| 3 | Needs approval/input |
| 4 | Completed |
| 5 | Error/aborted |
| 6 | Unknown |

## Layout

```text
controller/   Windows UART, desktop integration, REST API and tests
fpga/         Verilog, pin constraints, TD project and programming scripts
bitstream/    Verified SPI/JTAG bitstream
```

## Controller Setup

Python 3.10 or newer is recommended.

```powershell
cd controller
python -m pip install -r requirements.txt
.\run_controller.ps1 -SerialPort COM5
```

Health and slot status:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/v1/health
Invoke-RestMethod http://127.0.0.1:8765/v1/slots
```

Run tests:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q codex_micro main.py tests
```

## Controls

Selection mode:

- Short K0-K3: open a bound conversation.
- Short the same key again: minimize Codex/ChatGPT.
- Long K0-K3: bind the current conversation to that slot.
- Short K4: enter operation mode.

Operation mode:

- Hold K0: hold Right Alt for push-to-talk software.
- K1: Backspace; hold for continuous deletion.
- K2: move right; hold for continuous movement.
- K3: move left; hold for continuous movement.
- Toggle SW0 upward: send.
- Short K4: return to selection mode.
- Long K4: clear the selected slot and return to selection mode.

## FPGA Build and Programming

Use Anlogic TD 5.6.5 or a compatible release and open
`fpga/codex_micro.al`. The target device is `EF2L15LG100B`.

TD command-line tools can fail on paths containing non-ASCII characters. Put
the repository in an ASCII-only path such as
`D:\codex-micro-fpga-controller` before programming.

From the `fpga` directory, temporary JTAG configuration:

```powershell
Get-Content -Raw .\download_jtag.tcl |
  & 'C:\Anlogic\TD_5.6.5_SP3_151.449\bin\td_commands_prompt.exe'
```

Permanent SPI Flash programming:

```powershell
Get-Content -Raw .\program_spi.tcl |
  & 'C:\Anlogic\TD_5.6.5_SP3_151.449\bin\td_commands_prompt.exe'
```

## Status Source and Privacy

For `codex://threads/{id}` sessions, the controller reads lifecycle events
from `%USERPROFILE%\.codex\sessions`. It does not upload session logs, read
cookies, or call private desktop network endpoints. A file-backed slot reports
`"status_source": "file"` from `/v1/slots`; other slots use the conservative
UI fallback.

The REST API intentionally listens only on `127.0.0.1` and has no remote
authentication. Do not expose port 8765 directly to a LAN or the Internet.

## License

MIT. See [LICENSE](LICENSE).
