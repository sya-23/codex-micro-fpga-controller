# Codex-Micro FPGA 控制面板

目标器件：安路 `EF2L15LG100B`。

## 板上资源

- `KEY0..KEY4`：`P99/P98/P97/P96/P89`，低电平按下。
- 物理上标为 `SW0` 的发送拨码：管脚 `P37`，向上为高电平。
- 板载 UART：FPGA `uart_rx=P83`、`uart_tx=P84`。
- 蜂鸣器：`P53`。
- 8 个 LED：`P38/P39/P40/P41/P42/P43/P45/P47`。
- 4 位数码管：沿用标准答案管脚。

当前工程不使用外部复位管脚。板上的重配置按键用于重新配置 FPGA，`KEY0` 保留给 K0 功能。

## 数码管状态

从左到右对应 K0、K1、K2、K3：

```text
0 空槽  1 空闲  2 执行中  3 等待确认
4 完成  5 错误  6 未知
```

## 工程

在 TD 中打开 `codex_micro.al`，或者新建 `EF2L15LG100B` 工程后添加：

- `codex_micro_top.v`
- `codex_micro.adc`

电脑端程序位于同级目录 `codex_micro_controller`，默认串口为 `COM5`，可用参数修改。

## 下载

TD 命令行在中文路径下可能把路径转换成 `??`，因此建议把整个仓库放到 ASCII 路径。发布包中已验证的 bitstream 位于 `../bitstream/codex_micro.bit`。

临时下载到 FPGA SRAM：

```powershell
Get-Content -Raw .\download_jtag.tcl | & 'C:\Anlogic\TD_5.6.5_SP3_151.449\bin\td_commands_prompt.exe'
```

永久写入 SPI Flash：

```powershell
Get-Content -Raw .\program_spi.tcl | & 'C:\Anlogic\TD_5.6.5_SP3_151.449\bin\td_commands_prompt.exe'
```

永久烧录后重新启动电脑端 Controller，使槽位状态从空槽重新建立。板上 `KEY0..KEY4` 仍是 K0..K4，不能再把 KEY0 当外部复位键使用。
