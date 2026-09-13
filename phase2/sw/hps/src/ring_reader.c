/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS DDR-ring reader implementation.
 * File class: [1] hand-written.
 *
 * This file consumes committed telemetry records from the HPS-visible DDR ring.
 * It uses generated packet and CSR constants through public headers and does not
 * duplicate CSR offsets, packet IDs, payload-size constants, or VERSION values.
 */

#include "ring_reader.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define TRECAP_RING_RESET_MAX_POLLS UINT32_C(1000000)

static void trecap_ring_set_err(char *err_buf, size_t err_buf_len, const char *message)
{
    if (err_buf == NULL || err_buf_len == 0u) {
        return;
    }
    if (message == NULL) {
        message = "unknown ring-reader error";
    }
    (void)snprintf(err_buf, err_buf_len, "%s", message);
}

static uint16_t trecap_ring_load_le16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8u));
}

static uint32_t trecap_ring_load_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8u) | ((uint32_t)p[2] << 16u) |
           ((uint32_t)p[3] << 24u);
}

static uint64_t trecap_ring_load_le64(const uint8_t *p)
{
    return (uint64_t)trecap_ring_load_le32(p) |
           ((uint64_t)trecap_ring_load_le32(&p[4]) << 32u);
}

static uint16_t trecap_ring_spec129_expected_nbin(void)
{
    return (uint16_t)((TPKT_SPEC129_MASK_BITS_OFFSET - TPKT_SPEC129_SPEC129_OFFSET) / 2u);
}

static uint16_t trecap_ring_spec64_expected_nbin(void)
{
    return (uint16_t)((TPKT_SPEC64_SUPPRESSED_COUNT_OFFSET - TPKT_SPEC64_SPEC64_OFFSET) / 2u);
}

static bool trecap_ring_pointer_state_is_valid(uint64_t wr, uint64_t rd, uint32_t ring_size_bytes)
{
    if (wr < rd) {
        return false;
    }
    if ((wr % (uint64_t)TPKT_DDR_ALIGN_BYTES) != 0u ||
        (rd % (uint64_t)TPKT_DDR_ALIGN_BYTES) != 0u) {
        return false;
    }
    return trecap_ring_used_bytes(wr, rd) <= (uint64_t)ring_size_bytes;
}

static bool trecap_ring_mapping_is_valid(const trecap_ring_mapping_t *ring)
{
    return ring != NULL && ring->base != NULL && ring->size_bytes > 0u &&
           ring->size_bytes <= (size_t)UINT32_MAX &&
           trecap_ring_size_is_valid((uint32_t)ring->size_bytes);
}

const char *trecap_ring_status_string(trecap_ring_status_t status)
{
    switch (status) {
    case TRECAP_RING_OK:
        return "ok";
    case TRECAP_RING_EMPTY:
        return "empty";
    case TRECAP_RING_WRAP_RECORD:
        return "wrap record";
    case TRECAP_RING_ERR_NULL:
        return "null argument";
    case TRECAP_RING_ERR_RANGE:
        return "range error";
    case TRECAP_RING_ERR_ALIGN:
        return "alignment error";
    case TRECAP_RING_ERR_CONFIG:
        return "configuration error";
    case TRECAP_RING_ERR_IO:
        return "I/O error";
    case TRECAP_RING_ERR_MALFORMED:
        return "malformed record";
    case TRECAP_RING_ERR_OVERSIZED:
        return "oversized record";
    case TRECAP_RING_ERR_BOUNDARY:
        return "ring-boundary error";
    case TRECAP_RING_ERR_CSR:
        return "CSR error";
    case TRECAP_RING_ERR_STALE:
        return "stale snapshot";
    case TRECAP_RING_ERR_TIMEOUT:
        return "timeout";
    case TRECAP_RING_ERR_DISABLED:
        return "transport disabled until reset and reconfiguration";
    default:
        return "unknown ring status";
    }
}

void trecap_ring_reader_config_set_defaults(trecap_ring_reader_config_t *cfg,
                                            const trecap_hps_runtime_config_t *runtime_cfg)
{
    if (cfg == NULL) {
        return;
    }
    memset(cfg, 0, sizeof(*cfg));
    cfg->ring_size_bytes = (uint32_t)(32u * 1024u * 1024u);
    cfg->ring_guard_bytes = (uint32_t)TCSR_RING_GUARD_BYTES_MIN;
    cfg->stop_on_malformed_record = true;
    cfg->commit_rd_after_each_record = true;
    cfg->reject_status_diagnostic_from_ring = true;

    if (runtime_cfg != NULL) {
        cfg->ring_size_bytes = runtime_cfg->ring_size_bytes;
        cfg->ring_guard_bytes = runtime_cfg->ring_guard_bytes;
        cfg->stop_on_malformed_record = runtime_cfg->stop_on_malformed_record;
    }
}

void trecap_ring_reader_counters_reset(trecap_ring_reader_counters_t *counters)
{
    if (counters != NULL) {
        memset(counters, 0, sizeof(*counters));
    }
}

void trecap_ring_reader_init(trecap_ring_reader_t *reader,
                             trecap_csr_window_t *csr,
                             const trecap_ring_mapping_t *ring,
                             const trecap_ring_reader_config_t *cfg)
{
    if (reader == NULL) {
        return;
    }
    memset(reader, 0, sizeof(*reader));
    reader->csr = csr;
    if (ring != NULL) {
        reader->ring = *ring;
    }
    if (cfg != NULL) {
        reader->cfg = *cfg;
    } else {
        trecap_ring_reader_config_set_defaults(&reader->cfg, NULL);
    }
    reader->last_seq = 0u;
    reader->have_last_seq = false;
    reader->telemetry_disabled_by_reader = true;
    reader->malformed_disable_commit_confirmed = false;
    reader->state = TRECAP_RING_READER_RESET_REQUIRED;
}

trecap_ring_status_t trecap_ring_map_physical(uint64_t ring_base_hps_phys,
                                              size_t ring_size_bytes,
                                              bool cacheable_mapping,
                                              trecap_ring_mapping_t *ring)
{
    if (ring == NULL) {
        return TRECAP_RING_ERR_NULL;
    }
    memset(ring, 0, sizeof(*ring));
    ring->fd = -1;

    if (ring_size_bytes == 0u || ring_size_bytes > (size_t)UINT32_MAX ||
        !trecap_ring_size_is_valid((uint32_t)ring_size_bytes)) {
        return TRECAP_RING_ERR_CONFIG;
    }
    if (!trecap_ring_base_is_valid(ring_base_hps_phys)) {
        return TRECAP_RING_ERR_ALIGN;
    }
    if (cacheable_mapping) {
        return TRECAP_RING_ERR_CONFIG;
    }

    long page_size_long = sysconf(_SC_PAGESIZE);
    if (page_size_long <= 0) {
        return TRECAP_RING_ERR_IO;
    }
    const uint64_t page_size = (uint64_t)page_size_long;
    if ((ring_base_hps_phys % page_size) != 0u || (ring_size_bytes % (size_t)page_size) != 0u) {
        return TRECAP_RING_ERR_ALIGN;
    }

    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) {
        return TRECAP_RING_ERR_IO;
    }

    void *mapped = mmap(NULL,
                        ring_size_bytes,
                        PROT_READ,
                        MAP_SHARED,
                        fd,
                        (off_t)ring_base_hps_phys);
    if (mapped == MAP_FAILED) {
        const int saved_errno = errno;
        (void)close(fd);
        errno = saved_errno;
        return TRECAP_RING_ERR_IO;
    }

    ring->base = (uint8_t *)mapped;
    ring->size_bytes = ring_size_bytes;
    ring->hps_phys_base = ring_base_hps_phys;
    ring->fpga_visible_base = 0u;
    ring->cacheable_mapping = false;
    ring->fd = fd;
    return TRECAP_RING_OK;
}

void trecap_ring_unmap(trecap_ring_mapping_t *ring)
{
    if (ring == NULL) {
        return;
    }
    if (ring->base != NULL && ring->size_bytes != 0u) {
        (void)munmap(ring->base, ring->size_bytes);
    }
    if (ring->fd >= 0) {
        (void)close(ring->fd);
    }
    memset(ring, 0, sizeof(*ring));
    ring->fd = -1;
}

trecap_ring_status_t trecap_ring_reader_reset_transport(trecap_ring_reader_t *reader)
{
    if (reader == NULL || reader->csr == NULL) {
        return TRECAP_RING_ERR_NULL;
    }

    /* Fail closed in software before the first MMIO access. A partial reset may
     * already have disabled hardware, so ACTIVE must never survive an error. */
    reader->state = TRECAP_RING_READER_RESET_REQUIRED;
    reader->telemetry_disabled_by_reader = true;
    reader->malformed_disable_commit_confirmed = false;

    trecap_csr_status_t csr_status = trecap_csr_set_control_levels(reader->csr, false, false);
    if (csr_status != TRECAP_CSR_OK) {
        return TRECAP_RING_ERR_CSR;
    }
    csr_status = trecap_csr_require_control_levels(reader->csr, false, false);
    if (csr_status != TRECAP_CSR_OK) {
        return TRECAP_RING_ERR_CSR;
    }

    bool writer_drained = false;
    for (uint32_t poll = 0u; poll < TRECAP_RING_RESET_MAX_POLLS; ++poll) {
        uint32_t dma_status = 0u;
        csr_status = trecap_csr_read32(reader->csr, TCSR_DMA_STATUS_OFFSET, &dma_status);
        if (csr_status != TRECAP_CSR_OK) {
            return TRECAP_RING_ERR_CSR;
        }
        const bool writer_idle =
            (dma_status & TCSR_DMA_STATUS_WRITER_IDLE_MASK) != UINT32_C(0);
        const bool writer_busy =
            (dma_status & TCSR_DMA_STATUS_WRITER_BUSY_MASK) != UINT32_C(0);
        if (writer_idle && !writer_busy) {
            writer_drained = true;
            break;
        }
    }
    if (!writer_drained) {
        return TRECAP_RING_ERR_TIMEOUT;
    }

    csr_status = trecap_csr_pulse_control(reader->csr, TCSR_CONTROL_TELEMETRY_SOFT_RESET_MASK);
    if (csr_status != TRECAP_CSR_OK) {
        return TRECAP_RING_ERR_CSR;
    }

    reader->rd = 0u;
    reader->wr_snapshot = 0u;
    reader->last_seq = 0u;
    reader->have_last_seq = false;
    reader->telemetry_disabled_by_reader = true;
    reader->malformed_disable_commit_confirmed = false;
    reader->state = TRECAP_RING_READER_RECONFIG_REQUIRED;
    return TRECAP_RING_OK;
}

trecap_ring_status_t trecap_ring_reader_configure_fpga_ring(trecap_ring_reader_t *reader,
                                                            uint64_t ring_base_fpga,
                                                            uint32_t ring_size_bytes,
                                                            uint32_t ring_guard_bytes)
{
    if (reader == NULL || reader->csr == NULL) {
        return TRECAP_RING_ERR_NULL;
    }
    if (reader->state != TRECAP_RING_READER_RECONFIG_REQUIRED) {
        return TRECAP_RING_ERR_DISABLED;
    }
    if (!trecap_ring_base_is_valid(ring_base_fpga) || !trecap_ring_size_is_valid(ring_size_bytes) ||
        ring_guard_bytes != (uint32_t)TCSR_RING_GUARD_BYTES_MIN) {
        return TRECAP_RING_ERR_CONFIG;
    }
    if (reader->rd != 0u || reader->wr_snapshot != 0u) {
        return TRECAP_RING_ERR_CONFIG;
    }
    if (reader->ring.base != NULL && reader->ring.size_bytes != 0u &&
        reader->ring.size_bytes != (size_t)ring_size_bytes) {
        return TRECAP_RING_ERR_CONFIG;
    }

    trecap_csr_ring_config_t ring_cfg;
    ring_cfg.base_fpga = ring_base_fpga;
    ring_cfg.size_bytes = ring_size_bytes;
    ring_cfg.guard_bytes = ring_guard_bytes;

    trecap_csr_status_t csr_status = trecap_csr_configure_ring(reader->csr, &ring_cfg);
    if (csr_status != TRECAP_CSR_OK) {
        return TRECAP_RING_ERR_CSR;
    }
    csr_status = trecap_csr_require_ring_configured(reader->csr);
    if (csr_status != TRECAP_CSR_OK) {
        return TRECAP_RING_ERR_CSR;
    }

    reader->cfg.ring_size_bytes = ring_size_bytes;
    reader->cfg.ring_guard_bytes = ring_guard_bytes;
    reader->ring.fpga_visible_base = ring_base_fpga;
    reader->rd = 0u;
    reader->wr_snapshot = 0u;
    reader->have_last_seq = false;
    reader->state = TRECAP_RING_READER_RD0_REQUIRED;
    return TRECAP_RING_OK;
}

trecap_ring_status_t trecap_ring_reader_commit_rd(trecap_ring_reader_t *reader, uint64_t rd)
{
    if (reader == NULL || reader->csr == NULL) {
        return TRECAP_RING_ERR_NULL;
    }
    if (reader->state != TRECAP_RING_READER_ACTIVE &&
        reader->state != TRECAP_RING_READER_RD0_REQUIRED) {
        return TRECAP_RING_ERR_DISABLED;
    }
    if (reader->state == TRECAP_RING_READER_RD0_REQUIRED && rd != 0u) {
        return TRECAP_RING_ERR_CONFIG;
    }
    if (!trecap_ring_size_is_valid(reader->cfg.ring_size_bytes)) {
        return TRECAP_RING_ERR_CONFIG;
    }
    if ((rd % (uint64_t)TPKT_DDR_ALIGN_BYTES) != 0u) {
        return TRECAP_RING_ERR_ALIGN;
    }
    if (rd < reader->rd) {
        return TRECAP_RING_ERR_RANGE;
    }
    if (!trecap_ring_pointer_state_is_valid(reader->wr_snapshot, rd, reader->cfg.ring_size_bytes)) {
        return TRECAP_RING_ERR_RANGE;
    }

    trecap_csr_status_t csr_status = trecap_csr_commit_ring_rd(reader->csr, rd);
    if (csr_status != TRECAP_CSR_OK) {
        return TRECAP_RING_ERR_CSR;
    }
    reader->rd = rd;
    reader->counters.consumer_commit_count += 1u;
    if (reader->state == TRECAP_RING_READER_RD0_REQUIRED) {
        reader->state = TRECAP_RING_READER_ACTIVE;
        reader->telemetry_disabled_by_reader = false;
    }
    return TRECAP_RING_OK;
}

trecap_ring_status_t trecap_ring_reader_snapshot_wr(trecap_ring_reader_t *reader,
                                                    uint64_t *wr_out)
{
    if (reader == NULL || reader->csr == NULL || wr_out == NULL) {
        return TRECAP_RING_ERR_NULL;
    }
    if (reader->state != TRECAP_RING_READER_ACTIVE || reader->telemetry_disabled_by_reader) {
        return TRECAP_RING_ERR_DISABLED;
    }
    if (!trecap_ring_size_is_valid(reader->cfg.ring_size_bytes)) {
        return TRECAP_RING_ERR_CONFIG;
    }

    uint64_t wr = 0u;
    trecap_csr_status_t csr_status = trecap_csr_snapshot_ring_wr(reader->csr, &wr);
    if (csr_status != TRECAP_CSR_OK) {
        return TRECAP_RING_ERR_CSR;
    }
    reader->wr_snapshot = wr;
    *wr_out = wr;

    if (!trecap_ring_pointer_state_is_valid(wr, reader->rd, reader->cfg.ring_size_bytes)) {
        reader->counters.stale_snapshot_count += 1u;
        return TRECAP_RING_ERR_STALE;
    }
    if (wr == reader->rd) {
        return TRECAP_RING_EMPTY;
    }
    return TRECAP_RING_OK;
}

static bool trecap_ring_validate_wave_payload(const trecap_ring_record_view_t *view,
                                              char *err_buf,
                                              size_t err_buf_len)
{
    if (view == NULL || view->payload_bytes_ptr == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "WAVE payload pointer is null");
        return false;
    }
    const uint8_t *p = view->payload_bytes_ptr;
    const uint64_t sample_base = trecap_ring_load_le64(&p[TPKT_WAVE_SAMPLE_BASE_OFFSET]);
    const uint16_t nsamp = trecap_ring_load_le16(&p[TPKT_WAVE_NSAMP_OFFSET]);
    const uint16_t channels = trecap_ring_load_le16(&p[TPKT_WAVE_CHANNELS_OFFSET]);
    const uint16_t stride = trecap_ring_load_le16(&p[TPKT_WAVE_STRIDE_OFFSET]);
    const uint16_t reserved = trecap_ring_load_le16(&p[TPKT_WAVE_RESERVED_OFFSET]);

    if (sample_base != view->timestamp) {
        trecap_ring_set_err(err_buf, err_buf_len, "WAVE sample_base does not match header timestamp");
        return false;
    }
    if (nsamp < (uint16_t)TPKT_PAYLOAD_WAVE_NSAMP_MIN ||
        nsamp > (uint16_t)TPKT_PAYLOAD_WAVE_NSAMP_MAX || channels != 3u || stride == 0u ||
        reserved != 0u) {
        trecap_ring_set_err(err_buf, err_buf_len, "WAVE payload fields are invalid");
        return false;
    }
    const uint32_t expected_payload_bytes = 16u + (uint32_t)nsamp * 6u;
    if (expected_payload_bytes != view->payload_bytes) {
        trecap_ring_set_err(err_buf, err_buf_len, "WAVE nsamp does not match payload_bytes");
        return false;
    }
    return true;
}

static bool trecap_ring_validate_spec129_payload(const trecap_ring_record_view_t *view,
                                                 char *err_buf,
                                                 size_t err_buf_len)
{
    if (view == NULL || view->payload_bytes_ptr == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "SPEC129 payload pointer is null");
        return false;
    }
    const uint8_t *p = view->payload_bytes_ptr;
    const uint64_t frame_idx = trecap_ring_load_le64(&p[TPKT_SPEC129_FRAME_IDX_OFFSET]);
    const uint16_t nbin = trecap_ring_load_le16(&p[TPKT_SPEC129_NBIN_OFFSET]);
    const uint16_t spec_shift = trecap_ring_load_le16(&p[TPKT_SPEC129_SPEC_SHIFT_OFFSET]);
    if (frame_idx != view->timestamp || nbin != trecap_ring_spec129_expected_nbin() ||
        spec_shift > (uint16_t)TCSR_SPEC_SHIFT_MAX) {
        trecap_ring_set_err(err_buf, err_buf_len, "SPEC129 frame_idx, nbin, or spec_shift invalid");
        return false;
    }

    const uint32_t mask_bytes = (uint32_t)TPKT_PAYLOAD_SPEC129_BYTES - TPKT_SPEC129_MASK_BITS_OFFSET;
    if (mask_bytes == 0u) {
        trecap_ring_set_err(err_buf, err_buf_len, "SPEC129 mask size invalid");
        return false;
    }
    const uint8_t last_mask_byte = p[TPKT_SPEC129_MASK_BITS_OFFSET + mask_bytes - 1u];
    const uint16_t unused_bits = (uint16_t)(mask_bytes * 8u) - nbin;
    if (unused_bits < 8u) {
        const uint8_t unused_mask = (uint8_t)(UINT8_MAX << (8u - unused_bits));
        if ((last_mask_byte & unused_mask) != 0u) {
            trecap_ring_set_err(err_buf, err_buf_len, "SPEC129 unused mask bits are nonzero");
            return false;
        }
    }
    return true;
}

static bool trecap_ring_validate_spec64_payload(const trecap_ring_record_view_t *view,
                                                char *err_buf,
                                                size_t err_buf_len)
{
    if (view == NULL || view->payload_bytes_ptr == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "SPEC64 payload pointer is null");
        return false;
    }
    const uint8_t *p = view->payload_bytes_ptr;
    const uint64_t frame_idx = trecap_ring_load_le64(&p[TPKT_SPEC64_FRAME_IDX_OFFSET]);
    const uint16_t nbin = trecap_ring_load_le16(&p[TPKT_SPEC64_NBIN_OFFSET]);
    const uint16_t spec_shift = trecap_ring_load_le16(&p[TPKT_SPEC64_SPEC_SHIFT_OFFSET]);
    if (frame_idx != view->timestamp || nbin != trecap_ring_spec64_expected_nbin() ||
        spec_shift > (uint16_t)TCSR_SPEC_SHIFT_MAX) {
        trecap_ring_set_err(err_buf, err_buf_len, "SPEC64 frame_idx, nbin, or spec_shift invalid");
        return false;
    }
    return true;
}

static bool trecap_ring_validate_metrics_payload(const trecap_ring_record_view_t *view,
                                                 char *err_buf,
                                                 size_t err_buf_len)
{
    if (view == NULL || view->payload_bytes_ptr == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "METRICS payload pointer is null");
        return false;
    }
    const uint64_t frame_idx = trecap_ring_load_le64(
        &view->payload_bytes_ptr[TPKT_METRICS_FRAME_IDX_OFFSET]);
    if (frame_idx != view->timestamp) {
        trecap_ring_set_err(err_buf, err_buf_len, "METRICS frame_idx does not match header timestamp");
        return false;
    }
    return true;
}

static bool trecap_ring_validate_status_payload(const trecap_ring_record_view_t *view,
                                                char *err_buf,
                                                size_t err_buf_len)
{
    if (view == NULL || view->payload_bytes_ptr == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "STATUS payload pointer is null");
        return false;
    }
    const uint8_t *p = view->payload_bytes_ptr;
    const uint64_t sample_count = trecap_ring_load_le64(&p[TPKT_STATUS_SAMPLE_COUNT_OFFSET]);
    const uint32_t reserved = trecap_ring_load_le32(&p[TPKT_STATUS_RESERVED_OFFSET]);
    if (sample_count != view->timestamp) {
        trecap_ring_set_err(err_buf, err_buf_len, "STATUS sample_count does not match timestamp");
        return false;
    }
    if (reserved != 0u) {
        trecap_ring_set_err(err_buf, err_buf_len, "STATUS reserved field is nonzero");
        return false;
    }
    return true;
}

static bool trecap_ring_validate_payload_fields(const trecap_ring_record_view_t *view,
                                                char *err_buf,
                                                size_t err_buf_len)
{
    if (view == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "null record view");
        return false;
    }
    switch (view->packet_type) {
    case TPKT_TYPE_WAVE:
        return trecap_ring_validate_wave_payload(view, err_buf, err_buf_len);
    case TPKT_TYPE_SPEC129:
        return trecap_ring_validate_spec129_payload(view, err_buf, err_buf_len);
    case TPKT_TYPE_SPEC64:
        return trecap_ring_validate_spec64_payload(view, err_buf, err_buf_len);
    case TPKT_TYPE_METRICS:
        return trecap_ring_validate_metrics_payload(view, err_buf, err_buf_len);
    case TPKT_TYPE_STATUS:
        return trecap_ring_validate_status_payload(view, err_buf, err_buf_len);
    default:
        trecap_ring_set_err(err_buf, err_buf_len, "payload validation requested for invalid type");
        return false;
    }
}

trecap_ring_status_t trecap_ring_validate_record_header(const trecap_ring_mapping_t *ring,
                                                        uint64_t rd,
                                                        uint64_t wr,
                                                        trecap_ring_record_view_t *view,
                                                        char *err_buf,
                                                        size_t err_buf_len)
{
    if (ring == NULL || view == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "null ring or view");
        return TRECAP_RING_ERR_NULL;
    }
    memset(view, 0, sizeof(*view));

    if (!trecap_ring_mapping_is_valid(ring)) {
        trecap_ring_set_err(err_buf, err_buf_len, "ring mapping is invalid");
        return TRECAP_RING_ERR_CONFIG;
    }
    const uint32_t ring_size = (uint32_t)ring->size_bytes;
    if (!trecap_ring_pointer_state_is_valid(wr, rd, ring_size)) {
        trecap_ring_set_err(err_buf, err_buf_len, "producer/consumer pointer state is invalid");
        return TRECAP_RING_ERR_STALE;
    }
    if (rd == wr) {
        return TRECAP_RING_EMPTY;
    }
    if (trecap_ring_used_bytes(wr, rd) < (uint64_t)TPKT_HEADER_BYTES) {
        trecap_ring_set_err(err_buf, err_buf_len, "producer boundary does not commit a full header");
        return TRECAP_RING_ERR_MALFORMED;
    }
    if ((rd & ((uint64_t)TPKT_DDR_ALIGN_BYTES - 1u)) != 0u) {
        trecap_ring_set_err(err_buf, err_buf_len, "consumer pointer is not 64-byte aligned");
        return TRECAP_RING_ERR_ALIGN;
    }

    const uint32_t off = trecap_ring_offset(rd, ring_size);
    const uint32_t tail = ring_size - off;
    if (tail < (uint32_t)TPKT_HEADER_BYTES) {
        trecap_ring_set_err(err_buf, err_buf_len, "not enough physical tail for telemetry header");
        return TRECAP_RING_ERR_BOUNDARY;
    }

    const uint8_t *header = &ring->base[off];
    const uint32_t magic = trecap_ring_load_le32(&header[TPKT_HDR_MAGIC_OFFSET]);
    const uint16_t version = trecap_ring_load_le16(&header[TPKT_HDR_VERSION_OFFSET]);
    const uint16_t header_bytes = trecap_ring_load_le16(&header[TPKT_HDR_HEADER_BYTES_OFFSET]);
    const uint16_t packet_type = trecap_ring_load_le16(&header[TPKT_HDR_PACKET_TYPE_OFFSET]);
    const uint16_t flags = trecap_ring_load_le16(&header[TPKT_HDR_FLAGS_OFFSET]);
    const uint32_t seq = trecap_ring_load_le32(&header[TPKT_HDR_SEQ_OFFSET]);
    const uint64_t timestamp = trecap_ring_load_le64(&header[TPKT_HDR_TIMESTAMP_OFFSET]);
    const uint32_t payload_bytes = trecap_ring_load_le32(&header[TPKT_HDR_PAYLOAD_BYTES_OFFSET]);
    const uint32_t header_crc = trecap_ring_load_le32(&header[TPKT_HDR_HEADER_CRC_OFFSET]);

    view->record_bytes = header;
    view->payload_bytes_ptr = &header[TPKT_HEADER_BYTES];
    view->absolute_rd = rd;
    view->ring_offset = off;
    view->physical_tail_bytes = tail;
    view->payload_bytes = payload_bytes;
    view->packet_type = packet_type;
    view->flags = flags;
    view->seq = seq;
    view->timestamp = timestamp;
    view->header_crc = header_crc;
    view->record_class = TRECAP_RING_RECORD_CLASS_MALFORMED;

    if (magic != (uint32_t)TPKT_TELEMETRY_MAGIC || version != (uint16_t)TPKT_HEADER_VERSION ||
        header_bytes != (uint16_t)TPKT_HEADER_BYTES || header_crc != 0u) {
        trecap_ring_set_err(err_buf, err_buf_len, "telemetry header magic/version/header/crc invalid");
        return TRECAP_RING_ERR_MALFORMED;
    }
    if (!trecap_ring_packet_type_is_wrap(packet_type) &&
        !trecap_ring_packet_type_is_forwardable(packet_type)) {
        trecap_ring_set_err(err_buf, err_buf_len, "packet type is unknown or reserved-disabled");
        return TRECAP_RING_ERR_MALFORMED;
    }
    if (!trecap_ring_flags_are_valid_for_ddr(packet_type, flags)) {
        trecap_ring_set_err(err_buf, err_buf_len, "packet flags are invalid for DDR-originated record");
        return TRECAP_RING_ERR_MALFORMED;
    }

    if (trecap_ring_packet_type_is_wrap(packet_type)) {
        if (off == 0u || tail < (uint32_t)TPKT_DDR_ALIGN_BYTES || payload_bytes != 0u ||
            timestamp != 0u) {
            trecap_ring_set_err(err_buf, err_buf_len, "WRAP record location or header fields are invalid");
            return TRECAP_RING_ERR_BOUNDARY;
        }
        if (rd + (uint64_t)tail > wr) {
            trecap_ring_set_err(err_buf, err_buf_len, "WRAP record extends beyond producer snapshot");
            return TRECAP_RING_ERR_MALFORMED;
        }
        for (uint32_t i = (uint32_t)TPKT_HEADER_BYTES; i < tail; ++i) {
            if (header[i] != 0u) {
                trecap_ring_set_err(err_buf, err_buf_len, "WRAP physical-tail padding is nonzero");
                return TRECAP_RING_ERR_MALFORMED;
            }
        }
        view->record_class = TRECAP_RING_RECORD_CLASS_WRAP;
        view->ddr_record_bytes = tail;
        view->udp_datagram_bytes = 0u;
        view->absolute_next_rd = rd + (uint64_t)tail;
        return TRECAP_RING_WRAP_RECORD;
    }

    const uint64_t udp_datagram_bytes64 = (uint64_t)TPKT_HEADER_BYTES + (uint64_t)payload_bytes;
    const uint64_t ddr_record_bytes64 =
        (udp_datagram_bytes64 + ((uint64_t)TPKT_DDR_ALIGN_BYTES - UINT64_C(1))) &
        ~((uint64_t)TPKT_DDR_ALIGN_BYTES - UINT64_C(1));
    if (ddr_record_bytes64 > (uint64_t)UINT32_MAX ||
        ddr_record_bytes64 > (uint64_t)ring_size - (uint64_t)TCSR_RING_GUARD_BYTES_MIN) {
        trecap_ring_set_err(err_buf, err_buf_len, "record length exceeds safe ring capacity");
        return TRECAP_RING_ERR_MALFORMED;
    }
    const uint32_t ddr_record_bytes = (uint32_t)ddr_record_bytes64;
    if (ddr_record_bytes > tail) {
        trecap_ring_set_err(err_buf, err_buf_len, "normal record crosses physical ring end without WRAP");
        return TRECAP_RING_ERR_BOUNDARY;
    }
    if (rd + (uint64_t)ddr_record_bytes > wr) {
        trecap_ring_set_err(err_buf, err_buf_len, "record body extends beyond producer snapshot");
        return TRECAP_RING_ERR_MALFORMED;
    }

    view->ddr_record_bytes = ddr_record_bytes;
    view->udp_datagram_bytes = (uint32_t)udp_datagram_bytes64;
    view->absolute_next_rd = rd + ddr_record_bytes64;

    if (udp_datagram_bytes64 > (uint64_t)TPKT_UDP_MAX_BYTES) {
        view->record_class = TRECAP_RING_RECORD_CLASS_OVERSIZED;
        trecap_ring_set_err(err_buf, err_buf_len, "record exceeds UDP datagram bound");
        return TRECAP_RING_ERR_OVERSIZED;
    }
    if (!trecap_ring_payload_size_is_valid(packet_type, payload_bytes)) {
        trecap_ring_set_err(err_buf, err_buf_len, "packet payload size is invalid");
        return TRECAP_RING_ERR_MALFORMED;
    }

    view->record_class = TRECAP_RING_RECORD_CLASS_NORMAL;

    if (!trecap_ring_validate_payload_fields(view, err_buf, err_buf_len)) {
        view->record_class = TRECAP_RING_RECORD_CLASS_MALFORMED;
        return TRECAP_RING_ERR_MALFORMED;
    }
    return TRECAP_RING_OK;
}

trecap_ring_status_t trecap_ring_reader_peek(const trecap_ring_reader_t *reader,
                                             trecap_ring_record_view_t *view,
                                             char *err_buf,
                                             size_t err_buf_len)
{
    if (reader == NULL || view == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "null reader or view");
        return TRECAP_RING_ERR_NULL;
    }
    if (reader->state != TRECAP_RING_READER_ACTIVE || reader->telemetry_disabled_by_reader) {
        trecap_ring_set_err(err_buf, err_buf_len, "ring reader is latched disabled");
        return TRECAP_RING_ERR_DISABLED;
    }
    if (reader->ring.cacheable_mapping) {
        trecap_ring_set_err(err_buf, err_buf_len, "cached ring mapping is forbidden");
        return TRECAP_RING_ERR_CONFIG;
    }
    trecap_ring_status_t status = trecap_ring_validate_record_header(&reader->ring,
                                                                     reader->rd,
                                                                     reader->wr_snapshot,
                                                                     view,
                                                                     err_buf,
                                                                     err_buf_len);
    if (status == TRECAP_RING_WRAP_RECORD && view->seq != 0u &&
        (!reader->have_last_seq || view->seq != reader->last_seq)) {
        view->record_class = TRECAP_RING_RECORD_CLASS_MALFORMED;
        trecap_ring_set_err(err_buf, err_buf_len, "WRAP seq is neither zero nor previous normal seq");
        return TRECAP_RING_ERR_MALFORMED;
    }
    return status;
}

trecap_ring_status_t trecap_ring_reader_advance(trecap_ring_reader_t *reader,
                                                const trecap_ring_record_view_t *view)
{
    if (reader == NULL || view == NULL) {
        return TRECAP_RING_ERR_NULL;
    }
    if (reader->state != TRECAP_RING_READER_ACTIVE || reader->telemetry_disabled_by_reader) {
        return TRECAP_RING_ERR_DISABLED;
    }
    if (!reader->cfg.commit_rd_after_each_record) {
        return TRECAP_RING_ERR_CONFIG;
    }
    if (view->absolute_next_rd < reader->rd) {
        return TRECAP_RING_ERR_RANGE;
    }
    if (!trecap_ring_pointer_state_is_valid(reader->wr_snapshot,
                                            view->absolute_next_rd,
                                            reader->cfg.ring_size_bytes)) {
        return TRECAP_RING_ERR_RANGE;
    }

    trecap_ring_status_t status =
        trecap_ring_reader_commit_rd(reader, view->absolute_next_rd);
    if (status != TRECAP_RING_OK) {
        return status;
    }

    if (view->record_class == TRECAP_RING_RECORD_CLASS_WRAP) {
        reader->counters.wrap_records_seen += 1u;
    } else {
        reader->counters.records_seen += 1u;
    }
    return TRECAP_RING_OK;
}

trecap_ring_status_t trecap_ring_reader_note_forwarded(trecap_ring_reader_t *reader,
                                                       const trecap_ring_record_view_t *view)
{
    if (reader == NULL || view == NULL) {
        return TRECAP_RING_ERR_NULL;
    }
    if (reader->state != TRECAP_RING_READER_ACTIVE || reader->telemetry_disabled_by_reader) {
        return TRECAP_RING_ERR_DISABLED;
    }
    if (!trecap_ring_record_view_is_forwardable(view)) {
        return TRECAP_RING_ERR_MALFORMED;
    }

    reader->counters.records_forwardable += 1u;

    if (reader->have_last_seq) {
        const uint32_t expected = reader->last_seq + 1u;
        if (view->seq != expected) {
            const uint32_t forward_delta = view->seq - expected;
            reader->counters.sequence_gap_count +=
                (forward_delta < UINT32_C(0x80000000)) ? (uint64_t)forward_delta : UINT64_C(1);
        }
    }
    reader->last_seq = view->seq;
    reader->have_last_seq = true;
    return TRECAP_RING_OK;
}

trecap_ring_status_t trecap_ring_reader_handle_malformed(trecap_ring_reader_t *reader,
                                                         const trecap_ring_record_view_t *view,
                                                         char *err_buf,
                                                         size_t err_buf_len)
{
    (void)view;
    if (reader == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "null reader in malformed handler");
        return TRECAP_RING_ERR_NULL;
    }

    if (reader->state == TRECAP_RING_READER_MALFORMED_LATCHED) {
        trecap_ring_set_err(err_buf, err_buf_len, "malformed latch is already active");
        return TRECAP_RING_ERR_DISABLED;
    }
    if (reader->state != TRECAP_RING_READER_ACTIVE || reader->csr == NULL) {
        trecap_ring_set_err(err_buf, err_buf_len, "malformed handler requires an active reader and CSR");
        return TRECAP_RING_ERR_DISABLED;
    }

    /* Latch in software before MMIO so the same bad Rd can never be counted or
     * scanned again, even if a fail-closed hardware write reports an error. */
    reader->state = TRECAP_RING_READER_MALFORMED_LATCHED;
    reader->telemetry_disabled_by_reader = true;
    reader->malformed_disable_commit_confirmed = false;
    reader->counters.malformed_record_count += 1u;

    const trecap_csr_status_t disable_status =
        trecap_csr_set_control_levels(reader->csr, false, false);
    const trecap_csr_status_t disable_verify_status =
        trecap_csr_require_control_levels(reader->csr, false, false);
    const trecap_csr_status_t commit_status =
        trecap_csr_commit_ring_rd(reader->csr, reader->rd);
    if (disable_status != TRECAP_CSR_OK || disable_verify_status != TRECAP_CSR_OK ||
        commit_status != TRECAP_CSR_OK) {
        trecap_ring_set_err(err_buf, err_buf_len,
                            "malformed latch active, but hardware disable/current-Rd commit failed");
        return TRECAP_RING_ERR_CSR;
    }
    reader->counters.consumer_commit_count += 1u;
    reader->malformed_disable_commit_confirmed = true;

    trecap_ring_set_err(err_buf, err_buf_len, "malformed DDR record caused telemetry disable");
    return TRECAP_RING_ERR_MALFORMED;
}
