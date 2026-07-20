param(
    [string]$SerialPort = "COM5",
    [ValidateSet("enter", "ctrl-enter")]
    [string]$SendHotkey = "enter",
    [switch]$DryRun,
    [switch]$NoSerial
)

$arguments = @("main.py", "--serial-port", $SerialPort, "--send-hotkey", $SendHotkey)
if ($DryRun) { $arguments += "--dry-run" }
if ($NoSerial) { $arguments += "--no-serial" }

python @arguments
