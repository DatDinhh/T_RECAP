// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/platform/de1soc/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Typed, fail-closed boundary around the Quartus Platform Designer system.
// Contract: Bind the generated `system` module to board HPS pins, the 21-bit Avalon-MM CSR
//           master, and the 64-bit FPGA-to-HPS SDRAM write path.  This file is source-owned;
//           platform/de1soc/qsys/system/** remains generated and must never be hand-edited.

`default_nettype none

// The generated Platform Designer module name and flattened port ABI are frozen by
// platform/de1soc/address_map/platform_designer_wrapper.json.  Generation/normalization with
// Quartus Prime 20.1 must reproduce that ABI; the source checker deliberately has no fallback
// `system` stub, so a missing or incompatible generated system fails full-board elaboration.
module platform_designer_wrapper #(
    parameter int unsigned CSR_ADDR_W             = 21,
    parameter int unsigned CSR_DATA_W             = 32,
    parameter int unsigned CSR_BYTEEN_W           = 4,
    parameter int unsigned CSR_BURSTCOUNT_W       = 1,
    parameter int unsigned AVMM_ADDR_W            = 64,
    parameter int unsigned AVMM_DATA_W            = 64,
    parameter int unsigned AVMM_BYTEEN_W          = 8,
    parameter int unsigned AVMM_BURSTCOUNT_W      = 1,
    parameter int unsigned PD_DDR_ADDR_W          = 32,
    parameter int unsigned PD_DDR_BURSTCOUNT_W    = 1
) (
    // Both signals are part of the frozen single-domain reset contract.  clk_50_i is the
    // controller-owned clk_fabric alias; bridge_reset_n_i is the canonical synchronized reset.
    input  wire                         clk_50_i,
    input  wire                         bridge_reset_n_i,
    // Asynchronous HPS-to-FPGA reset source returned to clock_reset_ctrl for global qualification.
    output wire                         h2f_reset_n_o,

    // HPS DDR3 pins.
    output wire [14:0]                  HPS_DDR3_ADDR,
    output wire [2:0]                   HPS_DDR3_BA,
    output wire                         HPS_DDR3_CAS_N,
    output wire                         HPS_DDR3_CKE,
    output wire                         HPS_DDR3_CK_N,
    output wire                         HPS_DDR3_CK_P,
    output wire                         HPS_DDR3_CS_N,
    output wire [3:0]                   HPS_DDR3_DM,
    inout  wire [31:0]                  HPS_DDR3_DQ,
    inout  wire [3:0]                   HPS_DDR3_DQS_N,
    inout  wire [3:0]                   HPS_DDR3_DQS_P,
    output wire                         HPS_DDR3_ODT,
    output wire                         HPS_DDR3_RAS_N,
    output wire                         HPS_DDR3_RESET_N,
    input  wire                         HPS_DDR3_RZQ,
    output wire                         HPS_DDR3_WE_N,

    // HPS EMAC1, QSPI, SDIO, SPI, UART, USB, I2C, and GPIO pins selected by the frozen preset.
    output wire                         HPS_ENET_GTX_CLK,
    inout  wire                         HPS_ENET_INT_N,
    output wire                         HPS_ENET_MDC,
    inout  wire                         HPS_ENET_MDIO,
    input  wire                         HPS_ENET_RX_CLK,
    input  wire [3:0]                   HPS_ENET_RX_DATA,
    input  wire                         HPS_ENET_RX_DV,
    output wire [3:0]                   HPS_ENET_TX_DATA,
    output wire                         HPS_ENET_TX_EN,
    inout  wire [3:0]                   HPS_FLASH_DATA,
    output wire                         HPS_FLASH_DCLK,
    output wire                         HPS_FLASH_NCSO,
    inout  wire                         HPS_GSENSOR_INT,
    inout  wire                         HPS_I2C_CONTROL,
    inout  wire                         HPS_I2C1_SCLK,
    inout  wire                         HPS_I2C1_SDAT,
    inout  wire                         HPS_I2C2_SCLK,
    inout  wire                         HPS_I2C2_SDAT,
    inout  wire                         HPS_KEY,
    inout  wire                         HPS_LED,
    inout  wire                         HPS_LTC_GPIO,
    output wire                         HPS_SD_CLK,
    inout  wire                         HPS_SD_CMD,
    inout  wire [3:0]                   HPS_SD_DATA,
    output wire                         HPS_SPIM_CLK,
    input  wire                         HPS_SPIM_MISO,
    output wire                         HPS_SPIM_MOSI,
    output wire                         HPS_SPIM_SS,
    input  wire                         HPS_UART_RX,
    output wire                         HPS_UART_TX,
    inout  wire                         HPS_CONV_USB_N,
    input  wire                         HPS_USB_CLKOUT,
    inout  wire [7:0]                   HPS_USB_DATA,
    input  wire                         HPS_USB_DIR,
    input  wire                         HPS_USB_NXT,
    output wire                         HPS_USB_STP,

    // Avalon-MM master exported by trecap_csr_bridge.m0 in Platform Designer.
    output wire [CSR_ADDR_W-1:0]         csr_avs_address_o,
    output wire                         csr_avs_read_o,
    output wire                         csr_avs_write_o,
    output wire [CSR_DATA_W-1:0]         csr_avs_writedata_o,
    output wire [CSR_BYTEEN_W-1:0]       csr_avs_byteenable_o,
    output wire [CSR_BURSTCOUNT_W-1:0]   csr_avs_burstcount_o,
    input  wire                         csr_avs_waitrequest_i,
    input  wire [CSR_DATA_W-1:0]         csr_avs_readdata_i,
    input  wire                         csr_avs_readdatavalid_i,
    input  wire                         csr_avs_writeresponsevalid_i,
    input  wire [1:0]                   csr_avs_response_i,

    // Repository-native DDR write master.  The generated HPS F2SDRAM Avalon slave is 32-bit
    // byte-addressed, 64-bit data, and exposes the bridge's single-beat burstcount.  Platform
    // Designer adapts that field to the raw HPS SDRAM agent's 11-bit burstcount internally.
    input  wire [AVMM_ADDR_W-1:0]        avm_address_i,
    input  wire                         avm_write_i,
    input  wire [AVMM_DATA_W-1:0]        avm_writedata_i,
    input  wire [AVMM_BYTEEN_W-1:0]      avm_byteenable_i,
    input  wire [AVMM_BURSTCOUNT_W-1:0]  avm_burstcount_i,
    output wire                         avm_waitrequest_o,
    output wire                         avm_writeresponsevalid_o,
    output wire [1:0]                   avm_response_o
);

    localparam logic [1:0] AVMM_RESPONSE_OKAY   = 2'b00;
    localparam logic [1:0] AVMM_RESPONSE_SLVERR = 2'b10;
    localparam logic [63:0] HPS_DDR_END_EXCLUSIVE = 64'h0000_0000_4000_0000;

    wire [PD_DDR_ADDR_W-1:0]       pd_ddr_address;
    wire [PD_DDR_BURSTCOUNT_W-1:0] pd_ddr_burstcount;
    wire                            pd_ddr_write;
    wire                            pd_ddr_waitrequest;
    wire [AVMM_DATA_W-1:0]          pd_ddr_readdata_unused;
    wire                            pd_ddr_readdatavalid_unused;
    wire                            ddr_address_in_range;
    wire                            ddr_address_reject;
    logic                           ddr_response_valid_q;
    logic                           ddr_response_error_q;
    wire                            ddr_write_accept;

    // The board has 1 GiB of HPS DDR3 at byte addresses [0, 0x4000_0000).  Never silently truncate
    // or wrap a repository-native 64-bit address: an out-of-range beat is accepted locally and is
    // never forwarded to Platform Designer.  The exported HPS F2SDRAM port has no native response
    // channel, so this boundary returns exactly one registered local response for every accepted
    // single-beat request: OKAY means the legal request crossed the generated bridge's
    // waitrequest/acceptance boundary, while SLVERR means the local range guard rejected it.  This
    // is deliberately not evidence of later physical-DRAM completion or a downstream error check.
    assign ddr_address_in_range = (avm_address_i < HPS_DDR_END_EXCLUSIVE);
    assign ddr_address_reject = avm_write_i && !ddr_address_in_range;
    assign pd_ddr_address = avm_address_i[31:0];
    assign pd_ddr_burstcount = avm_burstcount_i;
    assign pd_ddr_write = avm_write_i && ddr_address_in_range;

    assign avm_waitrequest_o = ddr_address_reject ? 1'b0 : pd_ddr_waitrequest;
    assign ddr_write_accept = avm_write_i && !avm_waitrequest_o;
    assign avm_writeresponsevalid_o = ddr_response_valid_q;
    assign avm_response_o = ddr_response_error_q ? AVMM_RESPONSE_SLVERR : AVMM_RESPONSE_OKAY;

    always_ff @(posedge clk_50_i or negedge bridge_reset_n_i) begin
        if (!bridge_reset_n_i) begin
            ddr_response_valid_q <= 1'b0;
            ddr_response_error_q <= 1'b0;
        end else begin
            ddr_response_valid_q <= ddr_write_accept;
            ddr_response_error_q <= ddr_write_accept && ddr_address_reject;
        end
    end

    // No generated-system compatibility shim is permitted here.  The real Quartus output must
    // provide module `system`; --require-generated in the wrapper checker validates its flattened
    // header, system.qip, system.sopcinfo, and normalized Qsys source before signoff.
    system u_platform_designer_system (
        .clk_50_clk(clk_50_i),
        // This generated reset input owns clk_0.clk_reset and the two typed Avalon bridges only;
        // it is not connected to an HPS reset sink.  clock_reset_ctrl supplies the same canonical
        // reset used by the CSR leaf and DDR writer so transaction state is coherent.
        .reset_n_reset_n(bridge_reset_n_i),
        .h2f_reset_reset_n(h2f_reset_n_o),

        .memory_mem_a(HPS_DDR3_ADDR),
        .memory_mem_ba(HPS_DDR3_BA),
        .memory_mem_ck(HPS_DDR3_CK_P),
        .memory_mem_ck_n(HPS_DDR3_CK_N),
        .memory_mem_cke(HPS_DDR3_CKE),
        .memory_mem_cs_n(HPS_DDR3_CS_N),
        .memory_mem_ras_n(HPS_DDR3_RAS_N),
        .memory_mem_cas_n(HPS_DDR3_CAS_N),
        .memory_mem_we_n(HPS_DDR3_WE_N),
        .memory_mem_reset_n(HPS_DDR3_RESET_N),
        .memory_mem_dq(HPS_DDR3_DQ),
        .memory_mem_dqs(HPS_DDR3_DQS_P),
        .memory_mem_dqs_n(HPS_DDR3_DQS_N),
        .memory_mem_odt(HPS_DDR3_ODT),
        .memory_mem_dm(HPS_DDR3_DM),
        .memory_oct_rzqin(HPS_DDR3_RZQ),

        .hps_io_hps_io_emac1_inst_TX_CLK(HPS_ENET_GTX_CLK),
        .hps_io_hps_io_emac1_inst_TXD0(HPS_ENET_TX_DATA[0]),
        .hps_io_hps_io_emac1_inst_TXD1(HPS_ENET_TX_DATA[1]),
        .hps_io_hps_io_emac1_inst_TXD2(HPS_ENET_TX_DATA[2]),
        .hps_io_hps_io_emac1_inst_TXD3(HPS_ENET_TX_DATA[3]),
        .hps_io_hps_io_emac1_inst_RXD0(HPS_ENET_RX_DATA[0]),
        .hps_io_hps_io_emac1_inst_RXD1(HPS_ENET_RX_DATA[1]),
        .hps_io_hps_io_emac1_inst_RXD2(HPS_ENET_RX_DATA[2]),
        .hps_io_hps_io_emac1_inst_RXD3(HPS_ENET_RX_DATA[3]),
        .hps_io_hps_io_emac1_inst_MDIO(HPS_ENET_MDIO),
        .hps_io_hps_io_emac1_inst_MDC(HPS_ENET_MDC),
        .hps_io_hps_io_emac1_inst_RX_CTL(HPS_ENET_RX_DV),
        .hps_io_hps_io_emac1_inst_TX_CTL(HPS_ENET_TX_EN),
        .hps_io_hps_io_emac1_inst_RX_CLK(HPS_ENET_RX_CLK),
        .hps_io_hps_io_qspi_inst_IO0(HPS_FLASH_DATA[0]),
        .hps_io_hps_io_qspi_inst_IO1(HPS_FLASH_DATA[1]),
        .hps_io_hps_io_qspi_inst_IO2(HPS_FLASH_DATA[2]),
        .hps_io_hps_io_qspi_inst_IO3(HPS_FLASH_DATA[3]),
        .hps_io_hps_io_qspi_inst_SS0(HPS_FLASH_NCSO),
        .hps_io_hps_io_qspi_inst_CLK(HPS_FLASH_DCLK),
        .hps_io_hps_io_sdio_inst_CMD(HPS_SD_CMD),
        .hps_io_hps_io_sdio_inst_D0(HPS_SD_DATA[0]),
        .hps_io_hps_io_sdio_inst_D1(HPS_SD_DATA[1]),
        .hps_io_hps_io_sdio_inst_D2(HPS_SD_DATA[2]),
        .hps_io_hps_io_sdio_inst_D3(HPS_SD_DATA[3]),
        .hps_io_hps_io_sdio_inst_CLK(HPS_SD_CLK),
        .hps_io_hps_io_usb1_inst_D0(HPS_USB_DATA[0]),
        .hps_io_hps_io_usb1_inst_D1(HPS_USB_DATA[1]),
        .hps_io_hps_io_usb1_inst_D2(HPS_USB_DATA[2]),
        .hps_io_hps_io_usb1_inst_D3(HPS_USB_DATA[3]),
        .hps_io_hps_io_usb1_inst_D4(HPS_USB_DATA[4]),
        .hps_io_hps_io_usb1_inst_D5(HPS_USB_DATA[5]),
        .hps_io_hps_io_usb1_inst_D6(HPS_USB_DATA[6]),
        .hps_io_hps_io_usb1_inst_D7(HPS_USB_DATA[7]),
        .hps_io_hps_io_usb1_inst_CLK(HPS_USB_CLKOUT),
        .hps_io_hps_io_usb1_inst_STP(HPS_USB_STP),
        .hps_io_hps_io_usb1_inst_DIR(HPS_USB_DIR),
        .hps_io_hps_io_usb1_inst_NXT(HPS_USB_NXT),
        .hps_io_hps_io_spim1_inst_CLK(HPS_SPIM_CLK),
        .hps_io_hps_io_spim1_inst_MOSI(HPS_SPIM_MOSI),
        .hps_io_hps_io_spim1_inst_MISO(HPS_SPIM_MISO),
        .hps_io_hps_io_spim1_inst_SS0(HPS_SPIM_SS),
        .hps_io_hps_io_uart0_inst_RX(HPS_UART_RX),
        .hps_io_hps_io_uart0_inst_TX(HPS_UART_TX),
        .hps_io_hps_io_i2c0_inst_SDA(HPS_I2C1_SDAT),
        .hps_io_hps_io_i2c0_inst_SCL(HPS_I2C1_SCLK),
        .hps_io_hps_io_i2c1_inst_SDA(HPS_I2C2_SDAT),
        .hps_io_hps_io_i2c1_inst_SCL(HPS_I2C2_SCLK),
        .hps_io_hps_io_gpio_inst_GPIO09(HPS_CONV_USB_N),
        .hps_io_hps_io_gpio_inst_GPIO35(HPS_ENET_INT_N),
        .hps_io_hps_io_gpio_inst_GPIO40(HPS_LTC_GPIO),
        .hps_io_hps_io_gpio_inst_GPIO48(HPS_I2C_CONTROL),
        .hps_io_hps_io_gpio_inst_GPIO53(HPS_LED),
        .hps_io_hps_io_gpio_inst_GPIO54(HPS_KEY),
        .hps_io_hps_io_gpio_inst_GPIO61(HPS_GSENSOR_INT),

        .trecap_csr_lw_master_address(csr_avs_address_o),
        .trecap_csr_lw_master_burstcount(csr_avs_burstcount_o),
        .trecap_csr_lw_master_byteenable(csr_avs_byteenable_o),
        .trecap_csr_lw_master_read(csr_avs_read_o),
        .trecap_csr_lw_master_readdata(csr_avs_readdata_i),
        .trecap_csr_lw_master_readdatavalid(csr_avs_readdatavalid_i),
        .trecap_csr_lw_master_response(csr_avs_response_i),
        .trecap_csr_lw_master_waitrequest(csr_avs_waitrequest_i),
        .trecap_csr_lw_master_write(csr_avs_write_o),
        .trecap_csr_lw_master_writedata(csr_avs_writedata_o),
        .trecap_csr_lw_master_writeresponsevalid(csr_avs_writeresponsevalid_i),

        .trecap_f2h_sdram0_address(pd_ddr_address),
        .trecap_f2h_sdram0_burstcount(pd_ddr_burstcount),
        .trecap_f2h_sdram0_waitrequest(pd_ddr_waitrequest),
        .trecap_f2h_sdram0_read(1'b0),
        .trecap_f2h_sdram0_readdata(pd_ddr_readdata_unused),
        .trecap_f2h_sdram0_readdatavalid(pd_ddr_readdatavalid_unused),
        .trecap_f2h_sdram0_write(pd_ddr_write),
        .trecap_f2h_sdram0_writedata(avm_writedata_i),
        .trecap_f2h_sdram0_byteenable(avm_byteenable_i)
    );

    wire unused_pd_read_path = ^pd_ddr_readdata_unused ^ pd_ddr_readdatavalid_unused;

`ifndef SYNTHESIS
    initial begin
        if ((CSR_ADDR_W != 21) || (CSR_DATA_W != 32) || (CSR_BYTEEN_W != 4) ||
            (CSR_BURSTCOUNT_W != 1)) begin
            $fatal(1, "platform_designer_wrapper: CSR ABI must remain 21/32/4/1");
        end
        if ((AVMM_ADDR_W != 64) || (AVMM_DATA_W != 64) || (AVMM_BYTEEN_W != 8) ||
            (AVMM_BURSTCOUNT_W != 1)) begin
            $fatal(1, "platform_designer_wrapper: repository DDR ABI must remain 64/64/8/1");
        end
        if ((PD_DDR_ADDR_W != 32) || (PD_DDR_BURSTCOUNT_W != 1)) begin
            $fatal(1, "platform_designer_wrapper: generated F2SDRAM export ABI must remain address=32 burstcount=1");
        end
    end
`endif

endmodule : platform_designer_wrapper

`default_nettype wire
