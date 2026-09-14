# SPDX-License-Identifier: MIT
# Board-name aliases for the generated HPS hard-peripheral timing exceptions.
# We retain the vendor's directions and scalar endpoints while matching the
# HPS_* names exposed by our board top. These cuts cover hard peripherals only;
# they do not apply to HPS DDR, FPGA peripherals, or HPS-to-fabric data paths.
# Vendor source: system_hps_0_hps_io_border.sdc, lines 1-84.
# Vendor source SHA256: 208f249ea4a140fcecc8eb60a33d2ffb4c3f679f9c6a2acb19d0c250d2e2397a
# Mapping: rtl/platform/de1soc/platform_designer_wrapper.sv, lines 195-249.
# Mapping source SHA256: 3123d253447c91903e41c646049a3f4c837ff871f3ca493b3019382d00934c4e
# Keep this explicit list aligned with the wrapper and the generated HPS preset.

proc trecap_hps_peripheral_cut {direction name} {
    set port [get_ports -nowarn $name]
    if {[get_collection_size $port] != 1} {
        error "T-RECAP: expected one HPS hard-peripheral pin for $name"
    }
    if {$direction eq "from"} {
        set_false_path -from $port -to *
    } elseif {$direction eq "to"} {
        set_false_path -from * -to $port
    } else {
        error "T-RECAP: invalid hard-peripheral cut direction $direction"
    }
}

# 40 vendor from-pin exceptions. Every list entry is one scalar pin.
foreach trecap_hps_peripheral_pin {
    HPS_ENET_RX_DATA[0]
    HPS_ENET_MDIO
    HPS_ENET_RX_DV
    HPS_ENET_RX_CLK
    HPS_ENET_RX_DATA[1]
    HPS_ENET_RX_DATA[2]
    HPS_ENET_RX_DATA[3]
    HPS_FLASH_DATA[0]
    HPS_FLASH_DATA[1]
    HPS_FLASH_DATA[2]
    HPS_FLASH_DATA[3]
    HPS_SD_CMD
    HPS_SD_DATA[0]
    HPS_SD_DATA[1]
    HPS_SD_DATA[2]
    HPS_SD_DATA[3]
    HPS_USB_DATA[0]
    HPS_USB_DATA[1]
    HPS_USB_DATA[2]
    HPS_USB_DATA[3]
    HPS_USB_DATA[4]
    HPS_USB_DATA[5]
    HPS_USB_DATA[6]
    HPS_USB_DATA[7]
    HPS_USB_CLKOUT
    HPS_USB_DIR
    HPS_USB_NXT
    HPS_SPIM_MISO
    HPS_UART_RX
    HPS_I2C1_SDAT
    HPS_I2C1_SCLK
    HPS_I2C2_SDAT
    HPS_I2C2_SCLK
    HPS_CONV_USB_N
    HPS_ENET_INT_N
    HPS_LTC_GPIO
    HPS_I2C_CONTROL
    HPS_LED
    HPS_KEY
    HPS_GSENSOR_INT
} {
    trecap_hps_peripheral_cut from $trecap_hps_peripheral_pin
}

# 44 vendor to-pin exceptions. Every list entry is one scalar pin.
foreach trecap_hps_peripheral_pin {
    HPS_ENET_GTX_CLK
    HPS_ENET_TX_DATA[0]
    HPS_ENET_TX_DATA[1]
    HPS_ENET_TX_DATA[2]
    HPS_ENET_TX_DATA[3]
    HPS_ENET_MDIO
    HPS_ENET_MDC
    HPS_ENET_TX_EN
    HPS_FLASH_DATA[0]
    HPS_FLASH_DATA[1]
    HPS_FLASH_DATA[2]
    HPS_FLASH_DATA[3]
    HPS_FLASH_NCSO
    HPS_FLASH_DCLK
    HPS_SD_CMD
    HPS_SD_DATA[0]
    HPS_SD_DATA[1]
    HPS_SD_CLK
    HPS_SD_DATA[2]
    HPS_SD_DATA[3]
    HPS_USB_DATA[0]
    HPS_USB_DATA[1]
    HPS_USB_DATA[2]
    HPS_USB_DATA[3]
    HPS_USB_DATA[4]
    HPS_USB_DATA[5]
    HPS_USB_DATA[6]
    HPS_USB_DATA[7]
    HPS_USB_STP
    HPS_SPIM_CLK
    HPS_SPIM_MOSI
    HPS_SPIM_SS
    HPS_UART_TX
    HPS_I2C1_SDAT
    HPS_I2C1_SCLK
    HPS_I2C2_SDAT
    HPS_I2C2_SCLK
    HPS_CONV_USB_N
    HPS_ENET_INT_N
    HPS_LTC_GPIO
    HPS_I2C_CONTROL
    HPS_LED
    HPS_KEY
    HPS_GSENSOR_INT
} {
    trecap_hps_peripheral_cut to $trecap_hps_peripheral_pin
}

unset trecap_hps_peripheral_pin
