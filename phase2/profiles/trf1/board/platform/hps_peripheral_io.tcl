# SPDX-License-Identifier: MIT
# Board-owned electrical standards for the 55 exposed HPS peripheral signals.
# We use the exact non-DDR HPS pin set and standards from Terasic's Rev-H GHRD.
# Physical hard-pin placement remains owned by the generated HPS_LOCATION data.
# Source: https://download.terasic.com/downloads/cd-rom/de1-soc/DE1-SoC_v.6.0.0_HWrevH_SystemCD.zip
# Member: Demonstrations/SOC_FPGA/de1_soc_GHRD/soc_system.qsf, lines 252 and 325-378.
# Member SHA-256: 4e38b4957b044cfd2ef4d8f8776cf590b02fe3bf388c57b9e51445b25ac8b3bd
# The vendor DDR pin script owns HPS_DDR3_* SSTL/OCT assignments separately.

set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_CONV_USB_N}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_GTX_CLK}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_INT_N}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_MDC}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_MDIO}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_RX_CLK}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_RX_DATA[0]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_RX_DATA[1]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_RX_DATA[2]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_RX_DATA[3]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_RX_DV}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_TX_DATA[0]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_TX_DATA[1]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_TX_DATA[2]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_TX_DATA[3]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_ENET_TX_EN}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_FLASH_DATA[0]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_FLASH_DATA[1]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_FLASH_DATA[2]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_FLASH_DATA[3]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_FLASH_DCLK}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_FLASH_NCSO}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_GSENSOR_INT}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_I2C1_SCLK}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_I2C1_SDAT}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_I2C2_SCLK}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_I2C2_SDAT}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_I2C_CONTROL}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_KEY}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_LED}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_LTC_GPIO}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SD_CLK}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SD_CMD}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SD_DATA[0]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SD_DATA[1]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SD_DATA[2]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SD_DATA[3]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SPIM_CLK}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SPIM_MISO}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SPIM_MOSI}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_SPIM_SS}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_UART_RX}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_UART_TX}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_CLKOUT}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DATA[0]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DATA[1]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DATA[2]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DATA[3]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DATA[4]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DATA[5]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DATA[6]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DATA[7]}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_DIR}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_NXT}
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to {HPS_USB_STP}
