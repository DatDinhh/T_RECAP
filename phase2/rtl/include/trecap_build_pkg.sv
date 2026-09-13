// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL package.
// Layer: rtl/include/
// Purpose: Build-profile aliases and contract checks layered on generated constants.
// Contract: No duplicated CSR, packet, or core constants; all aliases derive from generated packages.

`default_nettype none

package trecap_build_pkg;

  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_math_pkg::*;
  localparam string TBUILD_PROJECT_NAME        = "T_RECAP_Phase2";
  localparam string TBUILD_CONTRACT_REVISION   = "core_rev_j__telemetry_rev_g";
  localparam string TBUILD_REPOSITORY_PHASE    = "implementation_core_first";

  typedef enum logic [2:0] {
    TBUILD_TARGET_CORE_ONLY        = 3'd0,
    TBUILD_TARGET_BRAM_REPLAY      = 3'd1,
    TBUILD_TARGET_CORE_TELEMETRY   = 3'd2,
    TBUILD_TARGET_HPS_BRIDGE       = 3'd3,
    TBUILD_TARGET_DE1SOC_FULL      = 3'd4
  } trecap_build_target_e;

  typedef enum logic [1:0] {
    TBUILD_PACKET_PROFILE_DISABLED     = 2'd0,
    TBUILD_PACKET_PROFILE_STATUS_ONLY  = 2'd1,
    TBUILD_PACKET_PROFILE_FULL_DEMO    = 2'd2
  } trecap_packet_profile_e;

  // Artifact paths used by ROM wrappers and BRAM replay modules. These are path aliases;
  // the mathematical constants remain generated in trecap_core_pkg.sv.
  localparam string TBUILD_COEFF_DIR                  = "artifacts/coefficients";
  localparam string TBUILD_WINDOW_QW_MEMH             = "artifacts/coefficients/window_qw.memh";
  localparam string TBUILD_TWIDDLE_RE_MEMH            = "artifacts/coefficients/twiddle_re.memh";
  localparam string TBUILD_TWIDDLE_IM_MEMH            = "artifacts/coefficients/twiddle_im.memh";
  localparam string TBUILD_TWIDDLE_INV_RE_MEMH        = "artifacts/coefficients/twiddle_inv_re.memh";
  localparam string TBUILD_TWIDDLE_INV_IM_MEMH        = "artifacts/coefficients/twiddle_inv_im.memh";
  localparam string TBUILD_TEST_VECTOR_DIR            = "artifacts/test_vectors";
  localparam string TBUILD_REFERENCE_OUTPUT_DIR       = "artifacts/reference_outputs";

  // C0 defaults: BRAM replay is the first correctness path and transport starts disabled.
  localparam int unsigned TBUILD_DEFAULT_SOURCE_MODE  = TCSR_SOURCE_MODE_BRAM_REPLAY;
  localparam int unsigned TBUILD_DEFAULT_SPEC_MODE    = TCSR_SPEC_MODE_SPEC_DISABLED;
  localparam int unsigned TBUILD_DEFAULT_WAVE_DECIM   = TCSR_WAVE_DECIM_RESET;
  localparam int unsigned TBUILD_DEFAULT_SPEC_SHIFT   = TCSR_SPEC_SHIFT_RESET;

  localparam logic [31:0] TBUILD_PACKET_ENABLE_NONE = 32'h00000000;
  localparam logic [31:0] TBUILD_PACKET_ENABLE_STATUS_ONLY =
      TCSR_PACKET_ENABLE_STATUS_EN_MASK;
  localparam logic [31:0] TBUILD_PACKET_ENABLE_FULL_DEMO =
      TCSR_PACKET_ENABLE_WAVE_EN_MASK    |
      TCSR_PACKET_ENABLE_SPEC_EN_MASK    |
      TCSR_PACKET_ENABLE_METRICS_EN_MASK |
      TCSR_PACKET_ENABLE_STATUS_EN_MASK;

  localparam logic [31:0] TBUILD_CONTROL_TELEMETRY_OFF = 32'h00000000;
  localparam logic [31:0] TBUILD_CONTROL_TELEMETRY_ON =
      TCSR_CONTROL_TELEMETRY_ENABLE_MASK |
      TCSR_CONTROL_RING_WRITER_ENABLE_MASK;

  localparam bit TBUILD_CORE_GEOMETRY_OK =
      (T_DELAY_D == (T_FFT_L + T_CUSHION_G)) &&
      (T_HOP_H * 2 == T_FFT_L) &&
      (T_UNIQUE_BINS == ((T_FFT_L / 2) + 1)) &&
      (T_MAG2_W == (2 * T_CAN_W));

  localparam bit TBUILD_TRANSPORT_VERSION_OK =
      (TCSR_VERSION_VALUE == ((TCSR_VERSION_MAJOR << 16) | TCSR_VERSION_MINOR)) &&
      (TPKT_TRANSPORT_VERSION_MAJOR == TCSR_VERSION_MAJOR) &&
      (TPKT_TRANSPORT_VERSION_MINOR == TCSR_VERSION_MINOR);

  localparam int unsigned TBUILD_WAVE_TRIPLET_BYTES = $bits(trecap_wave_triplet_t) / 8;

  localparam bit TBUILD_PACKET_SIZE_OK =
      (TPKT_HEADER_BYTES != 0) &&
      (TPKT_DDR_ALIGN_BYTES >= TPKT_HEADER_BYTES) &&
      (TPKT_PAYLOAD_STATUS_BYTES != 0) &&
      (TPKT_PAYLOAD_METRICS_BYTES != 0) &&
      (TPKT_PAYLOAD_SPEC129_BYTES != 0) &&
      (TPKT_PAYLOAD_SPEC64_BYTES != 0) &&
      (TPKT_PAYLOAD_WRAP_BYTES == 0) &&
      ((TPKT_HEADER_BYTES + TPKT_PAYLOAD_WAVE_MAX_BYTES) <= TPKT_UDP_MAX_BYTES);

  localparam bit TBUILD_CONTRACT_OK =
      TBUILD_CORE_GEOMETRY_OK && TBUILD_TRANSPORT_VERSION_OK && TBUILD_PACKET_SIZE_OK;

  function automatic logic [31:0] trecap_packet_enable_for_profile(
      input trecap_packet_profile_e profile
  );
    unique case (profile)
      TBUILD_PACKET_PROFILE_DISABLED: begin
        return TBUILD_PACKET_ENABLE_NONE;
      end
      TBUILD_PACKET_PROFILE_STATUS_ONLY: begin
        return TBUILD_PACKET_ENABLE_STATUS_ONLY;
      end
      TBUILD_PACKET_PROFILE_FULL_DEMO: begin
        return TBUILD_PACKET_ENABLE_FULL_DEMO;
      end
      default: begin
        return TBUILD_PACKET_ENABLE_NONE;
      end
    endcase
  endfunction : trecap_packet_enable_for_profile

  function automatic bit trecap_build_target_has_transport(input trecap_build_target_e target);
    return (target == TBUILD_TARGET_CORE_TELEMETRY) ||
           (target == TBUILD_TARGET_HPS_BRIDGE) ||
           (target == TBUILD_TARGET_DE1SOC_FULL);
  endfunction : trecap_build_target_has_transport

  function automatic bit trecap_build_target_has_hps_bridge(input trecap_build_target_e target);
    return (target == TBUILD_TARGET_HPS_BRIDGE) ||
           (target == TBUILD_TARGET_DE1SOC_FULL);
  endfunction : trecap_build_target_has_hps_bridge


  function automatic bit trecap_packet_type_known(input logic [15:0] packet_type);
    return (packet_type == TPKT_TYPE_WAVE) ||
           (packet_type == TPKT_TYPE_SPEC64) ||
           (packet_type == TPKT_TYPE_SPEC129) ||
           (packet_type == TPKT_TYPE_METRICS) ||
           (packet_type == TPKT_TYPE_STATUS) ||
           (packet_type == TPKT_TYPE_PEAKS) ||
           (packet_type == TPKT_TYPE_DEBUG) ||
           (packet_type == TPKT_TYPE_WRAP);
  endfunction : trecap_packet_type_known

  function automatic bit trecap_packet_type_reserved_disabled(input logic [15:0] packet_type);
    return (packet_type == TPKT_TYPE_PEAKS) || (packet_type == TPKT_TYPE_DEBUG);
  endfunction : trecap_packet_type_reserved_disabled

  function automatic logic [1:0] trecap_packet_drop_priority(input logic [15:0] packet_type);
    unique case (packet_type)
      TPKT_TYPE_WAVE: begin
        return TPKT_PRIORITY_WAVE;
      end
      TPKT_TYPE_SPEC64: begin
        return TPKT_PRIORITY_SPEC64;
      end
      TPKT_TYPE_SPEC129: begin
        return TPKT_PRIORITY_SPEC129;
      end
      TPKT_TYPE_METRICS: begin
        return TPKT_PRIORITY_METRICS;
      end
      TPKT_TYPE_STATUS: begin
        return TPKT_PRIORITY_STATUS;
      end
      TPKT_TYPE_PEAKS: begin
        return TPKT_PRIORITY_PEAKS;
      end
      TPKT_TYPE_DEBUG: begin
        return TPKT_PRIORITY_DEBUG;
      end
      default: begin
        return 2'd0;
      end
    endcase
  endfunction : trecap_packet_drop_priority

  function automatic int unsigned trecap_wave_payload_bytes(input int unsigned nsamp);
    return TPKT_WAVE_SAMPLE_OFFSET + (TBUILD_WAVE_TRIPLET_BYTES * nsamp);
  endfunction : trecap_wave_payload_bytes

  function automatic bit trecap_wave_payload_bytes_valid(input int unsigned payload_bytes);
    int unsigned delta;

    if ((payload_bytes < TPKT_PAYLOAD_WAVE_MIN_BYTES) ||
        (payload_bytes > TPKT_PAYLOAD_WAVE_MAX_BYTES)) begin
      return 1'b0;
    end
    if (payload_bytes < TPKT_WAVE_SAMPLE_OFFSET) begin
      return 1'b0;
    end

    delta = payload_bytes - TPKT_WAVE_SAMPLE_OFFSET;
    if ((delta % TBUILD_WAVE_TRIPLET_BYTES) != 0) begin
      return 1'b0;
    end
    return ((delta / TBUILD_WAVE_TRIPLET_BYTES) >= TPKT_PAYLOAD_WAVE_NSAMP_MIN) &&
           ((delta / TBUILD_WAVE_TRIPLET_BYTES) <= TPKT_PAYLOAD_WAVE_NSAMP_MAX);
  endfunction : trecap_wave_payload_bytes_valid

  function automatic bit trecap_payload_bytes_valid(
      input logic [15:0] packet_type,
      input int unsigned payload_bytes
  );
    unique case (packet_type)
      TPKT_TYPE_WAVE: begin
        return trecap_wave_payload_bytes_valid(payload_bytes);
      end
      TPKT_TYPE_SPEC64: begin
        return payload_bytes == TPKT_PAYLOAD_SPEC64_BYTES;
      end
      TPKT_TYPE_SPEC129: begin
        return payload_bytes == TPKT_PAYLOAD_SPEC129_BYTES;
      end
      TPKT_TYPE_METRICS: begin
        return payload_bytes == TPKT_PAYLOAD_METRICS_BYTES;
      end
      TPKT_TYPE_STATUS: begin
        return payload_bytes == TPKT_PAYLOAD_STATUS_BYTES;
      end
      TPKT_TYPE_WRAP: begin
        return payload_bytes == TPKT_PAYLOAD_WRAP_BYTES;
      end
      default: begin
        return 1'b0;
      end
    endcase
  endfunction : trecap_payload_bytes_valid

  function automatic longint unsigned trecap_record_aligned_bytes(input int unsigned payload_bytes);
    return trecap_align_up_pow2(TPKT_HEADER_BYTES + payload_bytes, TPKT_DDR_ALIGN_BYTES);
  endfunction : trecap_record_aligned_bytes

  function automatic bit trecap_ring_base_valid(input longint unsigned base_addr);
    return ((base_addr & (TCSR_RING_ALIGNMENT_BYTES - 1)) == 0);
  endfunction : trecap_ring_base_valid

  function automatic bit trecap_ring_size_valid(input longint unsigned ring_size_bytes);
    return trecap_is_power_of_two(ring_size_bytes) &&
           ((ring_size_bytes & (TCSR_RING_ALIGNMENT_BYTES - 1)) == 0);
  endfunction : trecap_ring_size_valid

endpackage : trecap_build_pkg

`default_nettype wire
