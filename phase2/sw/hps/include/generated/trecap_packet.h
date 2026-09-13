/* AUTO-GENERATED - DO NOT EDIT
 * Generator: scripts/gen_headers.py
 * Generator version: r1.2.0
 * Source manifest: spec/generated/gen_manifest.json
 */


#ifndef TRECAP_PACKET_H
#define TRECAP_PACKET_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TPKT_TELEMETRY_MAGIC UINT32_C(0x54524350)
#define TCMD_COMMAND_MAGIC UINT32_C(0x54524343)
#define TCMD_RESULT_MAGIC UINT32_C(0x54524352)
#define TPKT_HEADER_VERSION 1u
#define TPKT_HEADER_BYTES 32u
#define TCMD_PACKET_BYTES 28u
#define TPKT_UDP_MAX_BYTES 1200u
#define TPKT_DDR_ALIGN_BYTES 64u
#define TPKT_TRANSPORT_VERSION_MAJOR 1u
#define TPKT_TRANSPORT_VERSION_MINOR 8u
#define TCMD_VERSION_V1 1u
#define TCMD_VERSION_V2 2u
#define TCMD_VERSION_CURRENT 2u
#define TCMD_VERSION TCMD_VERSION_CURRENT
#define TCMD_RESULT_VERSION 2u
#define TCMD_RESULT_BYTES 32u

/* Packet type IDs and priorities. */
#define TPKT_TYPE_WAVE             UINT16_C(0x0001)
#define TPKT_PRIORITY_WAVE         0u
#define TPKT_TYPE_SPEC64           UINT16_C(0x0002)
#define TPKT_PRIORITY_SPEC64       1u
#define TPKT_TYPE_SPEC129          UINT16_C(0x0003)
#define TPKT_PRIORITY_SPEC129      1u
#define TPKT_TYPE_METRICS          UINT16_C(0x0004)
#define TPKT_PRIORITY_METRICS      2u
#define TPKT_TYPE_STATUS           UINT16_C(0x0005)
#define TPKT_PRIORITY_STATUS       3u
#define TPKT_TYPE_PEAKS            UINT16_C(0x0006)
#define TPKT_PRIORITY_PEAKS        1u
#define TPKT_TYPE_DEBUG            UINT16_C(0x007e)
#define TPKT_PRIORITY_DEBUG        0u
#define TPKT_TYPE_WRAP             UINT16_C(0x007f)

/* Common telemetry header offsets. */
#define TPKT_HDR_MAGIC_OFFSET                            0u
#define TPKT_HDR_VERSION_OFFSET                          4u
#define TPKT_HDR_HEADER_BYTES_OFFSET                     6u
#define TPKT_HDR_PACKET_TYPE_OFFSET                      8u
#define TPKT_HDR_FLAGS_OFFSET                            10u
#define TPKT_HDR_SEQ_OFFSET                              12u
#define TPKT_HDR_TIMESTAMP_OFFSET                        16u
#define TPKT_HDR_PAYLOAD_BYTES_OFFSET                    24u
#define TPKT_HDR_HEADER_CRC_OFFSET                       28u

/* Common telemetry flag bits and masks. */
#define TPKT_FLAG_PAYLOAD_TRUNCATED_LSB                          0u
#define TPKT_FLAG_PAYLOAD_TRUNCATED_MASK                         UINT16_C(0x0001)
#define TPKT_FLAG_PAYLOAD_SCALED_LSB                             1u
#define TPKT_FLAG_PAYLOAD_SCALED_MASK                            UINT16_C(0x0002)
#define TPKT_FLAG_AGGREGATE_METRICS_LSB                          2u
#define TPKT_FLAG_AGGREGATE_METRICS_MASK                         UINT16_C(0x0004)
#define TPKT_FLAG_PER_FRAME_METRICS_LSB                          3u
#define TPKT_FLAG_PER_FRAME_METRICS_MASK                         UINT16_C(0x0008)
#define TPKT_FLAG_CRC_ENABLED_LSB                                4u
#define TPKT_FLAG_CRC_ENABLED_MASK                               UINT16_C(0x0010)
#define TPKT_FLAG_STATUS_DIAGNOSTIC_LSB                          5u
#define TPKT_FLAG_STATUS_DIAGNOSTIC_MASK                         UINT16_C(0x0020)
#define TPKT_FLAG_RESERVED_15_6_LSB                              6u
#define TPKT_FLAG_RESERVED_15_6_MASK                             UINT16_C(0xffc0)

/* Payload size constants. */
#define TPKT_PAYLOAD_WAVE_MIN_BYTES          22u
#define TPKT_PAYLOAD_WAVE_MAX_BYTES          1168u
#define TPKT_PAYLOAD_WAVE_NSAMP_MIN          1u
#define TPKT_PAYLOAD_WAVE_NSAMP_MAX          192u
#define TPKT_PAYLOAD_SPEC129_BYTES           287u
#define TPKT_PAYLOAD_SPEC64_BYTES            268u
#define TPKT_PAYLOAD_METRICS_BYTES           56u
#define TPKT_PAYLOAD_STATUS_BYTES            72u
#define TPKT_PAYLOAD_WRAP_BYTES              0u

/* Payload field offsets. */
#define TPKT_WAVE_SAMPLE_BASE_OFFSET                     0u
#define TPKT_WAVE_NSAMP_OFFSET                           8u
#define TPKT_WAVE_CHANNELS_OFFSET                        10u
#define TPKT_WAVE_STRIDE_OFFSET                          12u
#define TPKT_WAVE_RESERVED_OFFSET                        14u
#define TPKT_WAVE_SAMPLE_OFFSET                          16u
#define TPKT_SPEC129_FRAME_IDX_OFFSET                    0u
#define TPKT_SPEC129_NBIN_OFFSET                         8u
#define TPKT_SPEC129_SPEC_SHIFT_OFFSET                   10u
#define TPKT_SPEC129_SPEC129_OFFSET                      12u
#define TPKT_SPEC129_MASK_BITS_OFFSET                    270u
#define TPKT_SPEC64_FRAME_IDX_OFFSET                     0u
#define TPKT_SPEC64_NBIN_OFFSET                          8u
#define TPKT_SPEC64_SPEC_SHIFT_OFFSET                    10u
#define TPKT_SPEC64_SPEC64_OFFSET                        12u
#define TPKT_SPEC64_SUPPRESSED_COUNT_OFFSET              140u
#define TPKT_SPEC64_ELIGIBLE_COUNT_OFFSET                204u
#define TPKT_METRICS_FRAME_IDX_OFFSET                    0u
#define TPKT_METRICS_ELIGIBLE_UNIQUE_BINS_OFFSET         8u
#define TPKT_METRICS_ELIGIBLE_SUPPRESSED_BINS_OFFSET     12u
#define TPKT_METRICS_ELIGIBLE_KEPT_MAG2_LO_OFFSET        16u
#define TPKT_METRICS_ELIGIBLE_TOTAL_MAG2_LO_OFFSET       24u
#define TPKT_METRICS_SUM_ABS_ERR_LO_OFFSET               32u
#define TPKT_METRICS_SUM_SQ_ERR_LO_OFFSET                40u
#define TPKT_METRICS_MAX_ABS_ERR_OFFSET                  48u
#define TPKT_METRICS_OVERFLOW_FLAGS_OFFSET               52u
#define TPKT_STATUS_SAMPLE_COUNT_OFFSET                  0u
#define TPKT_STATUS_FRAME_COUNT_OFFSET                   8u
#define TPKT_STATUS_SOURCE_MODE_OFFSET                   16u
#define TPKT_STATUS_SAMPLE_RATE_OFFSET                   20u
#define TPKT_STATUS_PACKET_ENABLE_OFFSET                 24u
#define TPKT_STATUS_DMA_DROP_COUNT_OFFSET                28u
#define TPKT_STATUS_UDP_SEND_ERROR_COUNT_OFFSET          32u
#define TPKT_STATUS_MALFORMED_RECORD_COUNT_OFFSET        36u
#define TPKT_STATUS_OVERSIZED_RECORD_COUNT_OFFSET        40u
#define TPKT_STATUS_COMMAND_REJECT_COUNT_OFFSET          44u
#define TPKT_STATUS_SEQUENCE_GAP_COUNT_OFFSET            48u
#define TPKT_STATUS_OVERFLOW_FLAGS_OFFSET                52u
#define TPKT_STATUS_THR2_LO_OFFSET                       56u
#define TPKT_STATUS_THR2_HI_OFFSET                       60u
#define TPKT_STATUS_PACKET_FIFO_DROP_COUNT_OFFSET        64u
#define TPKT_STATUS_RESERVED_OFFSET                      68u

/* PC command packet field offsets and command IDs. */
#define TCMD_MAGIC_OFFSET                                0u
#define TCMD_VERSION_OFFSET                              4u
#define TCMD_CMD_TYPE_OFFSET                             6u
#define TCMD_SEQ_OFFSET                                  8u
#define TCMD_ARG0_OFFSET                                 12u
#define TCMD_ARG1_OFFSET                                 16u
#define TCMD_ARG2_OFFSET                                 20u
#define TCMD_CRC32_OFFSET                                24u
#define TCMD_TYPE_SET_THR2             UINT16_C(0x0001)
#define TCMD_TYPE_CLEAR_METRICS        UINT16_C(0x0002)
#define TCMD_TYPE_SET_SOURCE_MODE      UINT16_C(0x0003)
#define TCMD_TYPE_SET_PACKET_ENABLE    UINT16_C(0x0004)
#define TCMD_TYPE_SET_WAVE_DECIM       UINT16_C(0x0005)
#define TCMD_TYPE_SET_SPEC_SHIFT       UINT16_C(0x0006)
#define TCMD_TYPE_PING                 UINT16_C(0x0007)
#define TCMD_TYPE_SET_SPEC_MODE        UINT16_C(0x0008)
#define TCMD_TYPE_SET_TELEMETRY_ENABLE UINT16_C(0x0009)
#define TCMD_TYPE_CONFIGURE_DDR_RING   UINT16_C(0x000a)
#define TCMD_TYPE_RESET_TRANSPORT      UINT16_C(0x000b)
#define TCMD_TYPE_CLEAR_COUNTERS       UINT16_C(0x000c)
#define TCMD_TYPE_START_BRAM_REPLAY    UINT16_C(0x000d)
#define TCMD_TYPE_READ_STATUS_VERSION  UINT16_C(0x000e)

/* Version-2 command-result offsets and enum values. */
#define TCMD_RESULT_MAGIC_OFFSET                         0u
#define TCMD_RESULT_VERSION_OFFSET                       4u
#define TCMD_RESULT_CMD_TYPE_OFFSET                      6u
#define TCMD_RESULT_SEQ_OFFSET                           8u
#define TCMD_RESULT_DISPOSITION_OFFSET                   12u
#define TCMD_RESULT_REJECT_REASON_OFFSET                 16u
#define TCMD_RESULT_FPGA_STATUS_OFFSET                   20u
#define TCMD_RESULT_CSR_VERSION_OFFSET                   24u
#define TCMD_RESULT_CRC32_OFFSET                         28u
#define TCMD_DISPOSITION_APPLIED              0u
#define TCMD_DISPOSITION_NOOP                 1u
#define TCMD_DISPOSITION_REJECTED             2u
#define TCMD_DISPOSITION_FAILED               3u
#define TCMD_REJECT_NONE                      0u
#define TCMD_REJECT_BAD_SOURCE                1u
#define TCMD_REJECT_BAD_LENGTH                2u
#define TCMD_REJECT_BAD_MAGIC                 3u
#define TCMD_REJECT_BAD_VERSION               4u
#define TCMD_REJECT_BAD_CRC                   5u
#define TCMD_REJECT_UNSUPPORTED_TYPE          6u
#define TCMD_REJECT_RANGE                     7u
#define TCMD_REJECT_RESERVED_ARGUMENT         8u
#define TCMD_REJECT_CSR                       9u
#define TCMD_REJECT_IO                        10u
#define TCMD_REJECT_UNSAFE_STATE              11u
#define TCMD_REJECT_SEQUENCE_STALE            12u
#define TCMD_REJECT_SEQUENCE_CONFLICT         13u
#define TCMD_REJECT_TIMEOUT                   14u
#define TCMD_REJECT_RESET_REQUIRED            15u
#define TCMD_REJECT_VERSION_MISMATCH          16u

#ifdef __cplusplus
}
#endif

#endif /* TRECAP_PACKET_H */
