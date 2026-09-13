/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS STATUS patch implementation.
 * File class: [1] hand-written.
 *
 * This file patches only HPS-owned fields in an outgoing STATUS UDP copy and
 * builds HPS diagnostic STATUS packets. It does not modify committed DDR ring
 * contents and does not duplicate packet IDs, STATUS offsets, CSR offsets, or
 * transport-version constants.
 */

#include "status_patch.h"

#include <stdio.h>
#include <string.h>

static void trecap_status_set_error(char *err_buf, size_t err_buf_len, const char *message)
{
    if (err_buf == NULL || err_buf_len == 0u) {
        return;
    }
    if (message == NULL) {
        message = "";
    }
    (void)snprintf(err_buf, err_buf_len, "%s", message);
    err_buf[err_buf_len - 1u] = '\0';
}

static bool trecap_status_inputs_are_valid(const trecap_status_patch_inputs_t *inputs)
{
    if (inputs == NULL || !inputs->fpga.valid) {
        return false;
    }
    if (!trecap_csr_source_mode_is_valid(inputs->fpga.source_mode)) {
        return false;
    }
    if (!trecap_csr_packet_enable_is_valid(inputs->fpga.packet_enable)) {
        return false;
    }
    if (!trecap_csr_thr2_is_valid(inputs->fpga.active_thr2)) {
        return false;
    }
    return true;
}

static void trecap_status_write_header(uint8_t *datagram,
                                       uint16_t flags,
                                       uint32_t seq,
                                       uint64_t timestamp)
{
    trecap_status_store_le32(&datagram[TPKT_HDR_MAGIC_OFFSET], (uint32_t)TPKT_TELEMETRY_MAGIC);
    trecap_status_store_le16(&datagram[TPKT_HDR_VERSION_OFFSET], (uint16_t)TPKT_HEADER_VERSION);
    trecap_status_store_le16(&datagram[TPKT_HDR_HEADER_BYTES_OFFSET], (uint16_t)TPKT_HEADER_BYTES);
    trecap_status_store_le16(&datagram[TPKT_HDR_PACKET_TYPE_OFFSET], (uint16_t)TPKT_TYPE_STATUS);
    trecap_status_store_le16(&datagram[TPKT_HDR_FLAGS_OFFSET], flags);
    trecap_status_store_le32(&datagram[TPKT_HDR_SEQ_OFFSET], seq);
    trecap_status_store_le64(&datagram[TPKT_HDR_TIMESTAMP_OFFSET], timestamp);
    trecap_status_store_le32(&datagram[TPKT_HDR_PAYLOAD_BYTES_OFFSET],
                             (uint32_t)TPKT_PAYLOAD_STATUS_BYTES);
    trecap_status_store_le32(&datagram[TPKT_HDR_HEADER_CRC_OFFSET], 0u);
}

static trecap_status_patch_status_t trecap_status_validate_payload_reserved(
    const uint8_t *payload,
    char *err_buf,
    size_t err_buf_len)
{
    if (payload == NULL) {
        trecap_status_set_error(err_buf, err_buf_len, "null STATUS payload");
        return TRECAP_STATUS_PATCH_ERR_NULL;
    }
    if (trecap_status_load_le32(&payload[TPKT_STATUS_RESERVED_OFFSET]) != 0u) {
        trecap_status_set_error(err_buf, err_buf_len, "STATUS reserved field is nonzero");
        return TRECAP_STATUS_PATCH_ERR_PAYLOAD;
    }
    return TRECAP_STATUS_PATCH_OK;
}

const char *trecap_status_patch_status_string(trecap_status_patch_status_t status)
{
    switch (status) {
    case TRECAP_STATUS_PATCH_OK:
        return "TRECAP_STATUS_PATCH_OK";
    case TRECAP_STATUS_PATCH_NOT_STATUS:
        return "TRECAP_STATUS_PATCH_NOT_STATUS";
    case TRECAP_STATUS_PATCH_DIAGNOSTIC:
        return "TRECAP_STATUS_PATCH_DIAGNOSTIC";
    case TRECAP_STATUS_PATCH_ERR_NULL:
        return "TRECAP_STATUS_PATCH_ERR_NULL";
    case TRECAP_STATUS_PATCH_ERR_RANGE:
        return "TRECAP_STATUS_PATCH_ERR_RANGE";
    case TRECAP_STATUS_PATCH_ERR_MAGIC:
        return "TRECAP_STATUS_PATCH_ERR_MAGIC";
    case TRECAP_STATUS_PATCH_ERR_VERSION:
        return "TRECAP_STATUS_PATCH_ERR_VERSION";
    case TRECAP_STATUS_PATCH_ERR_HEADER:
        return "TRECAP_STATUS_PATCH_ERR_HEADER";
    case TRECAP_STATUS_PATCH_ERR_PACKET_TYPE:
        return "TRECAP_STATUS_PATCH_ERR_PACKET_TYPE";
    case TRECAP_STATUS_PATCH_ERR_FLAGS:
        return "TRECAP_STATUS_PATCH_ERR_FLAGS";
    case TRECAP_STATUS_PATCH_ERR_PAYLOAD:
        return "TRECAP_STATUS_PATCH_ERR_PAYLOAD";
    case TRECAP_STATUS_PATCH_ERR_CRC:
        return "TRECAP_STATUS_PATCH_ERR_CRC";
    case TRECAP_STATUS_PATCH_ERR_CAPACITY:
        return "TRECAP_STATUS_PATCH_ERR_CAPACITY";
    default:
        return "TRECAP_STATUS_PATCH_ERR_UNKNOWN";
    }
}

void trecap_status_hps_counters_clear(trecap_status_hps_counters_t *counters)
{
    if (counters != NULL) {
        memset(counters, 0, sizeof(*counters));
    }
}

void trecap_status_hps_counters_from_runtime(const trecap_udp_sender_counters_t *udp,
                                             const trecap_ring_reader_counters_t *ring,
                                             uint64_t hps_command_reject_count,
                                             uint64_t csr_command_reject_count,
                                             trecap_status_hps_counters_t *out)
{
    if (out == NULL) {
        return;
    }
    trecap_status_hps_counters_clear(out);
    if (udp != NULL) {
        out->udp_send_error_count = udp->send_error_count;
        out->oversized_record_count += udp->oversized_count;
    }
    if (ring != NULL) {
        out->malformed_record_count = ring->malformed_record_count;
        out->oversized_record_count += ring->oversized_record_count;
        out->sequence_gap_count = ring->sequence_gap_count;
    }
    out->hps_command_reject_count = hps_command_reject_count;
    out->csr_command_reject_count = csr_command_reject_count;
}

trecap_status_patch_status_t trecap_status_patch_validate_status_datagram(
    const void *datagram,
    size_t datagram_bytes,
    bool diagnostic_allowed)
{
    if (datagram == NULL) {
        return TRECAP_STATUS_PATCH_ERR_NULL;
    }
    const uint8_t *bytes = (const uint8_t *)datagram;
    if (!trecap_status_datagram_size_is_valid(datagram_bytes)) {
        return TRECAP_STATUS_PATCH_ERR_RANGE;
    }
    if (trecap_status_load_le32(&bytes[TPKT_HDR_MAGIC_OFFSET]) != (uint32_t)TPKT_TELEMETRY_MAGIC) {
        return TRECAP_STATUS_PATCH_ERR_MAGIC;
    }
    if (trecap_status_load_le16(&bytes[TPKT_HDR_VERSION_OFFSET]) !=
        (uint16_t)TPKT_HEADER_VERSION) {
        return TRECAP_STATUS_PATCH_ERR_VERSION;
    }
    if (trecap_status_load_le16(&bytes[TPKT_HDR_HEADER_BYTES_OFFSET]) !=
        (uint16_t)TPKT_HEADER_BYTES) {
        return TRECAP_STATUS_PATCH_ERR_HEADER;
    }
    if (trecap_status_load_le16(&bytes[TPKT_HDR_PACKET_TYPE_OFFSET]) !=
        (uint16_t)TPKT_TYPE_STATUS) {
        return TRECAP_STATUS_PATCH_NOT_STATUS;
    }

    const uint16_t flags = trecap_status_load_le16(&bytes[TPKT_HDR_FLAGS_OFFSET]);
    if (!trecap_status_flags_are_valid(flags, diagnostic_allowed)) {
        return TRECAP_STATUS_PATCH_ERR_FLAGS;
    }
    if ((flags & TPKT_FLAG_STATUS_DIAGNOSTIC_MASK) != 0u &&
        trecap_status_load_le32(&bytes[TPKT_HDR_SEQ_OFFSET]) != 0u) {
        return TRECAP_STATUS_PATCH_ERR_FLAGS;
    }
    if (trecap_status_load_le32(&bytes[TPKT_HDR_PAYLOAD_BYTES_OFFSET]) !=
        (uint32_t)TPKT_PAYLOAD_STATUS_BYTES) {
        return TRECAP_STATUS_PATCH_ERR_PAYLOAD;
    }
    if (trecap_status_load_le32(&bytes[TPKT_HDR_HEADER_CRC_OFFSET]) != 0u) {
        return TRECAP_STATUS_PATCH_ERR_CRC;
    }

    const uint8_t *payload = trecap_status_payload_const(bytes);
    if (trecap_status_load_le32(&payload[TPKT_STATUS_RESERVED_OFFSET]) != 0u) {
        return TRECAP_STATUS_PATCH_ERR_PAYLOAD;
    }

    const bool diagnostic = (flags & TPKT_FLAG_STATUS_DIAGNOSTIC_MASK) != 0u;
    if (!diagnostic) {
        const uint64_t timestamp = trecap_status_load_le64(&bytes[TPKT_HDR_TIMESTAMP_OFFSET]);
        const uint64_t sample_count = trecap_status_load_le64(&payload[TPKT_STATUS_SAMPLE_COUNT_OFFSET]);
        if (timestamp != sample_count) {
            return TRECAP_STATUS_PATCH_ERR_PAYLOAD;
        }
    }
    return diagnostic ? TRECAP_STATUS_PATCH_DIAGNOSTIC : TRECAP_STATUS_PATCH_OK;
}

trecap_status_patch_status_t trecap_status_patch_udp_copy(void *datagram,
                                                          size_t datagram_bytes,
                                                          const trecap_status_hps_counters_t *hps,
                                                          char *err_buf,
                                                          size_t err_buf_len)
{
    if (datagram == NULL || hps == NULL) {
        trecap_status_set_error(err_buf, err_buf_len, "null STATUS patch argument");
        return TRECAP_STATUS_PATCH_ERR_NULL;
    }
    trecap_status_patch_status_t status = trecap_status_patch_validate_status_datagram(
        datagram,
        datagram_bytes,
        false);
    if (status != TRECAP_STATUS_PATCH_OK) {
        trecap_status_set_error(err_buf, err_buf_len, trecap_status_patch_status_string(status));
        return status;
    }

    uint8_t *payload = trecap_status_payload_mut((uint8_t *)datagram);
    status = trecap_status_patch_hps_fields_in_payload(payload, hps);
    if (status != TRECAP_STATUS_PATCH_OK) {
        trecap_status_set_error(err_buf, err_buf_len, trecap_status_patch_status_string(status));
    }
    return status;
}

trecap_status_patch_status_t trecap_status_patch_from_ring_view(
    void *udp_datagram,
    size_t udp_datagram_bytes,
    const trecap_ring_record_view_t *view,
    const trecap_status_hps_counters_t *hps,
    char *err_buf,
    size_t err_buf_len)
{
    if (udp_datagram == NULL || view == NULL || hps == NULL) {
        trecap_status_set_error(err_buf, err_buf_len, "null STATUS ring-view patch argument");
        return TRECAP_STATUS_PATCH_ERR_NULL;
    }
    if (view->packet_type != TPKT_TYPE_STATUS ||
        view->record_class != TRECAP_RING_RECORD_CLASS_NORMAL) {
        trecap_status_set_error(err_buf, err_buf_len, "ring view is not a normal STATUS record");
        return TRECAP_STATUS_PATCH_NOT_STATUS;
    }
    if (view->udp_datagram_bytes != (uint32_t)trecap_status_datagram_bytes() ||
        udp_datagram_bytes < trecap_status_datagram_bytes() || view->record_bytes == NULL) {
        trecap_status_set_error(err_buf, err_buf_len, "STATUS ring view size is invalid");
        return TRECAP_STATUS_PATCH_ERR_RANGE;
    }

    memcpy(udp_datagram, view->record_bytes, trecap_status_datagram_bytes());
    return trecap_status_patch_udp_copy(udp_datagram,
                                        trecap_status_datagram_bytes(),
                                        hps,
                                        err_buf,
                                        err_buf_len);
}

trecap_status_patch_status_t trecap_status_build_diagnostic(void *out_datagram,
                                                            size_t out_capacity_bytes,
                                                            const trecap_status_patch_inputs_t *inputs,
                                                            size_t *out_datagram_bytes,
                                                            char *err_buf,
                                                            size_t err_buf_len)
{
    if (out_datagram == NULL || inputs == NULL || out_datagram_bytes == NULL) {
        trecap_status_set_error(err_buf, err_buf_len, "null diagnostic STATUS argument");
        return TRECAP_STATUS_PATCH_ERR_NULL;
    }
    *out_datagram_bytes = 0u;
    const size_t datagram_bytes = trecap_status_datagram_bytes();
    if (out_capacity_bytes < datagram_bytes) {
        trecap_status_set_error(err_buf, err_buf_len, "diagnostic STATUS buffer too small");
        return TRECAP_STATUS_PATCH_ERR_CAPACITY;
    }
    if (!trecap_status_inputs_are_valid(inputs)) {
        trecap_status_set_error(err_buf, err_buf_len, "diagnostic STATUS inputs are invalid");
        return TRECAP_STATUS_PATCH_ERR_RANGE;
    }

    uint8_t *bytes = (uint8_t *)out_datagram;
    memset(bytes, 0, datagram_bytes);
    trecap_status_write_header(bytes,
                               TPKT_FLAG_STATUS_DIAGNOSTIC_MASK,
                               0u,
                               inputs->fpga.sample_count);
    trecap_status_patch_status_t status = trecap_status_write_payload_from_snapshot(
        trecap_status_payload_mut(bytes),
        inputs);
    if (status != TRECAP_STATUS_PATCH_OK) {
        trecap_status_set_error(err_buf, err_buf_len, trecap_status_patch_status_string(status));
        return status;
    }
    status = trecap_status_validate_payload_reserved(trecap_status_payload_const(bytes),
                                                     err_buf,
                                                     err_buf_len);
    if (status != TRECAP_STATUS_PATCH_OK) {
        return status;
    }
    status = trecap_status_patch_validate_status_datagram(bytes, datagram_bytes, true);
    if (status != TRECAP_STATUS_PATCH_OK && status != TRECAP_STATUS_PATCH_DIAGNOSTIC) {
        trecap_status_set_error(err_buf, err_buf_len, trecap_status_patch_status_string(status));
        return status;
    }

    *out_datagram_bytes = datagram_bytes;
    return TRECAP_STATUS_PATCH_OK;
}
