// AUTO-GENERATED - DO NOT EDIT
// Generator: scripts/gen_headers.py
// Generator version: r1.2.0
// Source manifest: spec/generated/gen_manifest.json

package trecap_packet_pkg;

  // Transport constants.
  localparam logic [31:0] TPKT_TELEMETRY_MAGIC                 = 32'h54524350;
  localparam logic [31:0] TCMD_COMMAND_MAGIC                   = 32'h54524343;
  localparam logic [31:0] TCMD_RESULT_MAGIC                    = 32'h54524352;
  localparam int unsigned TPKT_HEADER_VERSION                  = 1;
  localparam int unsigned TPKT_HEADER_BYTES                    = 32;
  localparam int unsigned TCMD_PACKET_BYTES                    = 28;
  localparam int unsigned TPKT_UDP_MAX_BYTES                   = 1200;
  localparam int unsigned TPKT_DDR_ALIGN_BYTES                 = 64;
  localparam int unsigned TPKT_TRANSPORT_VERSION_MAJOR         = 1;
  localparam int unsigned TPKT_TRANSPORT_VERSION_MINOR         = 8;
  localparam int unsigned TCMD_VERSION_V1                    = 1;
  localparam int unsigned TCMD_VERSION_V2                    = 2;
  localparam int unsigned TCMD_VERSION_CURRENT                 = 2;
  localparam int unsigned TCMD_VERSION                         = TCMD_VERSION_CURRENT;
  localparam int unsigned TCMD_RESULT_VERSION                  = 2;
  localparam int unsigned TCMD_RESULT_BYTES                    = 32;

  // Packet type IDs and drop priorities.
  localparam logic [15:0] TPKT_TYPE_WAVE             = 16'h0001;
  localparam logic [1:0]  TPKT_PRIORITY_WAVE         = 2'd0;
  localparam logic [15:0] TPKT_TYPE_SPEC64           = 16'h0002;
  localparam logic [1:0]  TPKT_PRIORITY_SPEC64       = 2'd1;
  localparam logic [15:0] TPKT_TYPE_SPEC129          = 16'h0003;
  localparam logic [1:0]  TPKT_PRIORITY_SPEC129      = 2'd1;
  localparam logic [15:0] TPKT_TYPE_METRICS          = 16'h0004;
  localparam logic [1:0]  TPKT_PRIORITY_METRICS      = 2'd2;
  localparam logic [15:0] TPKT_TYPE_STATUS           = 16'h0005;
  localparam logic [1:0]  TPKT_PRIORITY_STATUS       = 2'd3;
  localparam logic [15:0] TPKT_TYPE_PEAKS            = 16'h0006;
  localparam logic [1:0]  TPKT_PRIORITY_PEAKS        = 2'd1;
  localparam logic [15:0] TPKT_TYPE_DEBUG            = 16'h007e;
  localparam logic [1:0]  TPKT_PRIORITY_DEBUG        = 2'd0;
  localparam logic [15:0] TPKT_TYPE_WRAP             = 16'h007f;

  // Common telemetry header offsets.
  localparam int unsigned TPKT_HDR_MAGIC_OFFSET                            = 0;
  localparam int unsigned TPKT_HDR_VERSION_OFFSET                          = 4;
  localparam int unsigned TPKT_HDR_HEADER_BYTES_OFFSET                     = 6;
  localparam int unsigned TPKT_HDR_PACKET_TYPE_OFFSET                      = 8;
  localparam int unsigned TPKT_HDR_FLAGS_OFFSET                            = 10;
  localparam int unsigned TPKT_HDR_SEQ_OFFSET                              = 12;
  localparam int unsigned TPKT_HDR_TIMESTAMP_OFFSET                        = 16;
  localparam int unsigned TPKT_HDR_PAYLOAD_BYTES_OFFSET                    = 24;
  localparam int unsigned TPKT_HDR_HEADER_CRC_OFFSET                       = 28;

  // Common telemetry flag bits and masks.
  localparam int unsigned TPKT_FLAG_PAYLOAD_TRUNCATED_LSB                  = 0;
  localparam logic [15:0] TPKT_FLAG_PAYLOAD_TRUNCATED_MASK                 = 16'h0001;
  localparam int unsigned TPKT_FLAG_PAYLOAD_SCALED_LSB                     = 1;
  localparam logic [15:0] TPKT_FLAG_PAYLOAD_SCALED_MASK                    = 16'h0002;
  localparam int unsigned TPKT_FLAG_AGGREGATE_METRICS_LSB                  = 2;
  localparam logic [15:0] TPKT_FLAG_AGGREGATE_METRICS_MASK                 = 16'h0004;
  localparam int unsigned TPKT_FLAG_PER_FRAME_METRICS_LSB                  = 3;
  localparam logic [15:0] TPKT_FLAG_PER_FRAME_METRICS_MASK                 = 16'h0008;
  localparam int unsigned TPKT_FLAG_CRC_ENABLED_LSB                        = 4;
  localparam logic [15:0] TPKT_FLAG_CRC_ENABLED_MASK                       = 16'h0010;
  localparam int unsigned TPKT_FLAG_STATUS_DIAGNOSTIC_LSB                  = 5;
  localparam logic [15:0] TPKT_FLAG_STATUS_DIAGNOSTIC_MASK                 = 16'h0020;
  localparam int unsigned TPKT_FLAG_RESERVED_15_6_LSB                      = 6;
  localparam logic [15:0] TPKT_FLAG_RESERVED_15_6_MASK                     = 16'hffc0;

  // Payload size constants.
  localparam int unsigned TPKT_PAYLOAD_WAVE_MIN_BYTES          = 22;
  localparam int unsigned TPKT_PAYLOAD_WAVE_MAX_BYTES          = 1168;
  localparam int unsigned TPKT_PAYLOAD_WAVE_NSAMP_MIN          = 1;
  localparam int unsigned TPKT_PAYLOAD_WAVE_NSAMP_MAX          = 192;
  localparam int unsigned TPKT_PAYLOAD_SPEC129_BYTES           = 287;
  localparam int unsigned TPKT_PAYLOAD_SPEC64_BYTES            = 268;
  localparam int unsigned TPKT_PAYLOAD_METRICS_BYTES           = 56;
  localparam int unsigned TPKT_PAYLOAD_STATUS_BYTES            = 72;
  localparam int unsigned TPKT_PAYLOAD_WRAP_BYTES              = 0;

  // Payload field offsets.
  localparam int unsigned TPKT_WAVE_SAMPLE_BASE_OFFSET                     = 0;
  localparam int unsigned TPKT_WAVE_NSAMP_OFFSET                           = 8;
  localparam int unsigned TPKT_WAVE_CHANNELS_OFFSET                        = 10;
  localparam int unsigned TPKT_WAVE_STRIDE_OFFSET                          = 12;
  localparam int unsigned TPKT_WAVE_RESERVED_OFFSET                        = 14;
  localparam int unsigned TPKT_WAVE_SAMPLE_OFFSET                          = 16;
  localparam int unsigned TPKT_SPEC129_FRAME_IDX_OFFSET                    = 0;
  localparam int unsigned TPKT_SPEC129_NBIN_OFFSET                         = 8;
  localparam int unsigned TPKT_SPEC129_SPEC_SHIFT_OFFSET                   = 10;
  localparam int unsigned TPKT_SPEC129_SPEC129_OFFSET                      = 12;
  localparam int unsigned TPKT_SPEC129_MASK_BITS_OFFSET                    = 270;
  localparam int unsigned TPKT_SPEC64_FRAME_IDX_OFFSET                     = 0;
  localparam int unsigned TPKT_SPEC64_NBIN_OFFSET                          = 8;
  localparam int unsigned TPKT_SPEC64_SPEC_SHIFT_OFFSET                    = 10;
  localparam int unsigned TPKT_SPEC64_SPEC64_OFFSET                        = 12;
  localparam int unsigned TPKT_SPEC64_SUPPRESSED_COUNT_OFFSET              = 140;
  localparam int unsigned TPKT_SPEC64_ELIGIBLE_COUNT_OFFSET                = 204;
  localparam int unsigned TPKT_METRICS_FRAME_IDX_OFFSET                    = 0;
  localparam int unsigned TPKT_METRICS_ELIGIBLE_UNIQUE_BINS_OFFSET         = 8;
  localparam int unsigned TPKT_METRICS_ELIGIBLE_SUPPRESSED_BINS_OFFSET     = 12;
  localparam int unsigned TPKT_METRICS_ELIGIBLE_KEPT_MAG2_LO_OFFSET        = 16;
  localparam int unsigned TPKT_METRICS_ELIGIBLE_TOTAL_MAG2_LO_OFFSET       = 24;
  localparam int unsigned TPKT_METRICS_SUM_ABS_ERR_LO_OFFSET               = 32;
  localparam int unsigned TPKT_METRICS_SUM_SQ_ERR_LO_OFFSET                = 40;
  localparam int unsigned TPKT_METRICS_MAX_ABS_ERR_OFFSET                  = 48;
  localparam int unsigned TPKT_METRICS_OVERFLOW_FLAGS_OFFSET               = 52;
  localparam int unsigned TPKT_STATUS_SAMPLE_COUNT_OFFSET                  = 0;
  localparam int unsigned TPKT_STATUS_FRAME_COUNT_OFFSET                   = 8;
  localparam int unsigned TPKT_STATUS_SOURCE_MODE_OFFSET                   = 16;
  localparam int unsigned TPKT_STATUS_SAMPLE_RATE_OFFSET                   = 20;
  localparam int unsigned TPKT_STATUS_PACKET_ENABLE_OFFSET                 = 24;
  localparam int unsigned TPKT_STATUS_DMA_DROP_COUNT_OFFSET                = 28;
  localparam int unsigned TPKT_STATUS_UDP_SEND_ERROR_COUNT_OFFSET          = 32;
  localparam int unsigned TPKT_STATUS_MALFORMED_RECORD_COUNT_OFFSET        = 36;
  localparam int unsigned TPKT_STATUS_OVERSIZED_RECORD_COUNT_OFFSET        = 40;
  localparam int unsigned TPKT_STATUS_COMMAND_REJECT_COUNT_OFFSET          = 44;
  localparam int unsigned TPKT_STATUS_SEQUENCE_GAP_COUNT_OFFSET            = 48;
  localparam int unsigned TPKT_STATUS_OVERFLOW_FLAGS_OFFSET                = 52;
  localparam int unsigned TPKT_STATUS_THR2_LO_OFFSET                       = 56;
  localparam int unsigned TPKT_STATUS_THR2_HI_OFFSET                       = 60;
  localparam int unsigned TPKT_STATUS_PACKET_FIFO_DROP_COUNT_OFFSET        = 64;
  localparam int unsigned TPKT_STATUS_RESERVED_OFFSET                      = 68;

  // PC command packet field offsets and command IDs.
  localparam int unsigned TCMD_MAGIC_OFFSET                                = 0;
  localparam int unsigned TCMD_VERSION_OFFSET                              = 4;
  localparam int unsigned TCMD_CMD_TYPE_OFFSET                             = 6;
  localparam int unsigned TCMD_SEQ_OFFSET                                  = 8;
  localparam int unsigned TCMD_ARG0_OFFSET                                 = 12;
  localparam int unsigned TCMD_ARG1_OFFSET                                 = 16;
  localparam int unsigned TCMD_ARG2_OFFSET                                 = 20;
  localparam int unsigned TCMD_CRC32_OFFSET                                = 24;
  localparam logic [15:0] TCMD_TYPE_SET_THR2             = 16'h0001;
  localparam logic [15:0] TCMD_TYPE_CLEAR_METRICS        = 16'h0002;
  localparam logic [15:0] TCMD_TYPE_SET_SOURCE_MODE      = 16'h0003;
  localparam logic [15:0] TCMD_TYPE_SET_PACKET_ENABLE    = 16'h0004;
  localparam logic [15:0] TCMD_TYPE_SET_WAVE_DECIM       = 16'h0005;
  localparam logic [15:0] TCMD_TYPE_SET_SPEC_SHIFT       = 16'h0006;
  localparam logic [15:0] TCMD_TYPE_PING                 = 16'h0007;
  localparam logic [15:0] TCMD_TYPE_SET_SPEC_MODE        = 16'h0008;
  localparam logic [15:0] TCMD_TYPE_SET_TELEMETRY_ENABLE = 16'h0009;
  localparam logic [15:0] TCMD_TYPE_CONFIGURE_DDR_RING   = 16'h000a;
  localparam logic [15:0] TCMD_TYPE_RESET_TRANSPORT      = 16'h000b;
  localparam logic [15:0] TCMD_TYPE_CLEAR_COUNTERS       = 16'h000c;
  localparam logic [15:0] TCMD_TYPE_START_BRAM_REPLAY    = 16'h000d;
  localparam logic [15:0] TCMD_TYPE_READ_STATUS_VERSION  = 16'h000e;

  // Version-2 command-result offsets and enum values.
  localparam int unsigned TCMD_RESULT_MAGIC_OFFSET                         = 0;
  localparam int unsigned TCMD_RESULT_VERSION_OFFSET                       = 4;
  localparam int unsigned TCMD_RESULT_CMD_TYPE_OFFSET                      = 6;
  localparam int unsigned TCMD_RESULT_SEQ_OFFSET                           = 8;
  localparam int unsigned TCMD_RESULT_DISPOSITION_OFFSET                   = 12;
  localparam int unsigned TCMD_RESULT_REJECT_REASON_OFFSET                 = 16;
  localparam int unsigned TCMD_RESULT_FPGA_STATUS_OFFSET                   = 20;
  localparam int unsigned TCMD_RESULT_CSR_VERSION_OFFSET                   = 24;
  localparam int unsigned TCMD_RESULT_CRC32_OFFSET                         = 28;
  localparam int unsigned TCMD_DISPOSITION_APPLIED              = 0;
  localparam int unsigned TCMD_DISPOSITION_NOOP                 = 1;
  localparam int unsigned TCMD_DISPOSITION_REJECTED             = 2;
  localparam int unsigned TCMD_DISPOSITION_FAILED               = 3;
  localparam int unsigned TCMD_REJECT_NONE                      = 0;
  localparam int unsigned TCMD_REJECT_BAD_SOURCE                = 1;
  localparam int unsigned TCMD_REJECT_BAD_LENGTH                = 2;
  localparam int unsigned TCMD_REJECT_BAD_MAGIC                 = 3;
  localparam int unsigned TCMD_REJECT_BAD_VERSION               = 4;
  localparam int unsigned TCMD_REJECT_BAD_CRC                   = 5;
  localparam int unsigned TCMD_REJECT_UNSUPPORTED_TYPE          = 6;
  localparam int unsigned TCMD_REJECT_RANGE                     = 7;
  localparam int unsigned TCMD_REJECT_RESERVED_ARGUMENT         = 8;
  localparam int unsigned TCMD_REJECT_CSR                       = 9;
  localparam int unsigned TCMD_REJECT_IO                        = 10;
  localparam int unsigned TCMD_REJECT_UNSAFE_STATE              = 11;
  localparam int unsigned TCMD_REJECT_SEQUENCE_STALE            = 12;
  localparam int unsigned TCMD_REJECT_SEQUENCE_CONFLICT         = 13;
  localparam int unsigned TCMD_REJECT_TIMEOUT                   = 14;
  localparam int unsigned TCMD_REJECT_RESET_REQUIRED            = 15;
  localparam int unsigned TCMD_REJECT_VERSION_MISMATCH          = 16;

endpackage : trecap_packet_pkg
