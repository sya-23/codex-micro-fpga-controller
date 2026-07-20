# Permanent SPI Flash configuration for EF2L15B.
# The command also verifies the written image when -v is present.
set bitfile [file normalize "../bitstream/codex_micro.bit"]
download -bit $bitfile -mode program_spi -v -spd 7 -sec 64 -cable 0 -flashsize 128
exit
