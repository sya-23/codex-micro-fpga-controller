# Temporary JTAG configuration. The FPGA loses this image after power-off.
set bitfile [file normalize "../bitstream/codex_micro.bit"]
download -mode jtag -bit $bitfile -cable 0
exit
