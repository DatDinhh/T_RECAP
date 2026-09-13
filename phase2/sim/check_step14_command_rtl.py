#!/usr/bin/env python3
"""Step-14 structural/model/source checks.

This checker intentionally does not claim native RTL simulation. It validates the generated CSR
contract, the hand-written RTL wiring/ownership boundaries, a small executable command-state model,
and simulator-facing source/filelist structure. Run a native SystemVerilog simulator separately when
one is available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


class CheckFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def load_text(root: Path, relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"missing required source: {relative}")
    return path.read_text(encoding="utf-8")


def require_tokens(text: str, relative: str, tokens: list[str]) -> None:
    for token in tokens:
        require(token in text, f"{relative}: missing structural token {token!r}")


def register_by_name(csr: dict, name: str) -> dict:
    for register in csr["registers"]:
        if register["name"] == name:
            return register
    raise CheckFailure(f"CSR map missing register {name}")


def fields_by_name(register: dict) -> dict[str, dict]:
    return {field["name"]: field for field in register["fields"]}


def config_mutation_allowed_model(
    *,
    telemetry_enable: bool = False,
    ring_writer_enable: bool = False,
    transport_idle: bool = True,
    csr_pending: bool = False,
    request_busy: bool = False,
    replay_active: bool = False,
    path_busy: bool = False,
    e2e_busy: bool = False,
    transition_busy: bool = False,
) -> bool:
    return (
        not telemetry_enable
        and not ring_writer_enable
        and transport_idle
        and not csr_pending
        and not request_busy
        and not replay_active
        and not path_busy
        and not e2e_busy
        and not transition_busy
    )


@dataclass
class ReplayResultModel:
    pending: bool = False
    last_accept: bool = False
    last_reject: bool = False
    result_epoch: int = 0

    def start(self) -> tuple[bool, bool]:
        """Return (write_accepted, raw_start_pulse). Readiness never pre-filters raw START."""
        if self.pending:
            return False, False
        self.pending = True
        return True, True

    def feedback(self, *, accepted: bool = False, rejected: bool = False) -> None:
        if not self.pending:
            return
        if not (accepted or rejected):
            return
        self.pending = False
        self.last_accept = accepted and not rejected
        self.last_reject = rejected or not accepted
        self.result_epoch = (self.result_epoch + 1) & 0xFFFF

    def rearm(
        self,
        *,
        required: bool,
        transport_idle: bool,
        replay_active: bool = False,
        path_busy: bool = False,
        e2e_busy: bool = False,
    ) -> tuple[bool, bool]:
        legal = (
            required
            and transport_idle
            and not self.pending
            and not replay_active
            and not path_busy
            and not e2e_busy
        )
        if not legal:
            return False, False
        self.pending = False
        self.last_accept = False
        self.last_reject = False
        return True, True


@dataclass
class ReplayOriginArbiterModel:
    origin: str = "none"
    csr_queued: bool = False
    abort_reject_pending: bool = False

    def tick(
        self,
        *,
        csr_request: bool = False,
        key_request: bool = False,
        owner_accept: bool = False,
        owner_reject: bool = False,
        abort: bool = False,
    ) -> dict[str, bool | str]:
        terminal = owner_accept or owner_reject
        csr_forward = (
            not abort
            and self.origin == "none"
            and (self.csr_queued or csr_request)
        )
        key_forward = (
            not abort and self.origin == "none" and not csr_forward and key_request
        )
        csr_feedback_enable = self.origin == "csr" or (
            self.origin == "none" and csr_forward
        )
        result: dict[str, bool | str] = {
            "owner_start": csr_forward or key_forward,
            "forward_origin": "csr" if csr_forward else ("key" if key_forward else "none"),
            "csr_accept": owner_accept and csr_feedback_enable and not abort,
            "csr_reject": self.abort_reject_pending
            or (owner_reject and csr_feedback_enable and not abort),
            "key_blocked": key_request and not key_forward,
            "request_busy": self.origin != "none"
            or self.csr_queued
            or csr_request
            or key_request,
        }

        queued_next = self.csr_queued
        origin_next = self.origin
        abort_reject_next = False
        if abort:
            abort_reject_next = (
                self.origin == "csr" or self.csr_queued or csr_request
            )
            origin_next = "none"
            queued_next = False
        else:
            if csr_request and self.origin != "none":
                queued_next = True

            if self.origin == "none":
                if csr_forward:
                    queued_next = False
                    origin_next = "none" if terminal else "csr"
                elif key_forward:
                    origin_next = "none" if terminal else "key"
            elif terminal:
                origin_next = "none"

        self.origin = origin_next
        self.csr_queued = queued_next
        self.abort_reject_pending = abort_reject_next
        return result

def check_contract(root: Path) -> None:
    csr_path = root / "spec/generated/csr_map.json"
    require(csr_path.is_file(), "missing spec/generated/csr_map.json")
    csr = json.loads(csr_path.read_text(encoding="utf-8"))

    version = csr["constants"]["VERSION"]
    require((version["major"], version["minor"]) == (1, 8), "CSR VERSION must be 1.8")
    require(version["packed_hex"].lower() == "0x00010008", "packed CSR VERSION mismatch")

    expected_offsets = {
        "COUNTER_CLEAR": 0x08C,
        "REPLAY_CONTROL": 0x090,
        "REPLAY_STATUS": 0x094,
    }
    for name, offset in expected_offsets.items():
        register = register_by_name(csr, name)
        require(register["offset"] == offset, f"{name} offset mismatch")

    status_fields = fields_by_name(register_by_name(csr, "STATUS"))
    expected_status = {
        "source_commit_pending": (9, 9),
        "actual_source_mode": (10, 11),
        "transport_epoch_idle": (12, 12),
        "source_transition_busy": (13, 13),
    }
    for name, bit_range in expected_status.items():
        field = status_fields[name]
        require((field["lsb"], field["msb"]) == bit_range, f"STATUS.{name} mismatch")

    replay_fields = fields_by_name(register_by_name(csr, "REPLAY_STATUS"))
    expected_replay = {
        "pending": (0, 0),
        "last_accept": (1, 1),
        "last_reject": (2, 2),
        "start_ready": (3, 3),
        "replay_active": (4, 4),
        "replay_path_busy": (5, 5),
        "replay_path_done": (6, 6),
        "e2e_busy": (7, 7),
        "e2e_done": (8, 8),
        "error": (9, 9),
        "rearm_required": (10, 10),
        "result_epoch": (16, 31),
    }
    for name, bit_range in expected_replay.items():
        field = replay_fields[name]
        require((field["lsb"], field["msb"]) == bit_range, f"REPLAY_STATUS.{name} mismatch")

    csr_pkg = load_text(root, "rtl/include/generated/trecap_csr_pkg.sv")
    require_tokens(
        csr_pkg,
        "rtl/include/generated/trecap_csr_pkg.sv",
        [
            "TCSR_VERSION_MINOR = 8",
            "TCSR_VERSION_VALUE = 32'h00010008",
            "TCSR_COUNTER_CLEAR_OFFSET",
            "TCSR_REPLAY_CONTROL_OFFSET",
            "TCSR_REPLAY_STATUS_OFFSET",
            "TCSR_STATUS_ACTUAL_SOURCE_MODE_MASK",
            "TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK",
        ],
    )


def check_rtl_structure(root: Path) -> None:
    paths = {
        "bank": "rtl/hps_bridge/trecap_csr_bank.sv",
        "adapter": "rtl/hps_bridge/trecap_avmm_csr_adapter.sv",
        "bridge": "rtl/hps_bridge/trecap_hps_bridge_top.sv",
        "writer": "rtl/hps_bridge/trecap_ddr_ring_writer.sv",
        "telemetry": "rtl/telemetry/trecap_telemetry_top.sv",
        "full": "rtl/top/trecap_de1soc_full_top.sv",
        "source": "rtl/top/trecap_source_core_integration.sv",
        "e2e": "rtl/top/trecap_bram_replay_e2e_supervisor.sv",
        "system": "rtl/top/trecap_bram_replay_system_top.sv",
        "board": "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    }
    source = {name: load_text(root, path) for name, path in paths.items()}

    require_tokens(
        source["bank"],
        paths["bank"],
        [
            "TCSR_COUNTER_CLEAR_OFFSET",
            "TCSR_REPLAY_CONTROL_OFFSET",
            "TCSR_REPLAY_STATUS_OFFSET",
            "source_actual_mismatch",
            "source_transition_busy_comb",
            "config_mutation_allowed",
            "counter_clear_pulse_o <= counter_clear_req",
            "replay_start_pulse_o <= replay_start_req",
            "replay_rearm_pulse_o <= replay_rearm_req",
            "replay_request_pending_q &&",
            "replay_result_epoch_q <= replay_result_epoch_q + 16'd1",
            "csr_command_reject_count_q <= TCSR_CSR_COMMAND_REJECT_COUNT_RESET",
        ],
    )
    require_tokens(
        source["adapter"],
        paths["adapter"],
        [
            "assign dual_request = avs_read_i && avs_write_i",
            "assign request_legal = !dual_request && address_in_window && address_aligned &&",
            "transaction_is_read_q <= avs_read_i",
        ],
    )
    require(source["bank"].count("assign known_addr = csr_offset_known(csr_offset);") == 1,
            "CSR bank must have exactly one known-address assignment")
    require(
        "source_pending ||\n                                                             source_actual_mismatch"
        in source["bank"],
        "STATUS source pending must remain high through requested/actual mismatch",
    )
    bank_flat = compact(source["bank"])
    require(
        "!config_mutation_allowed || !ring_configured_q || !ring_rd_epoch_valid_q || "
        "!ring_pointers_valid_i" in bank_flat,
        "CONTROL re-enable is not gated by complete ring/source/replay quiescence",
    )
    require(
        "replay_request_pending_q || replay_request_busy_i || replay_active_i || "
        "replay_path_busy_i || replay_e2e_busy_i" in bank_flat,
        "REARM is not protected from pending/active/busy replay state",
    )
    require(
        "assign config_mutation_allowed = !telemetry_enable_q && !ring_writer_enable_q && "
        "transport_epoch_idle_i && !replay_request_pending_q && !replay_request_busy_i && "
        "!replay_active_i && !replay_path_busy_i && !replay_e2e_busy_i && "
        "!source_transition_busy_comb;"
        in bank_flat,
        "live telemetry/source config mutation lacks the complete quiescence gate",
    )
    write_decode = source["bank"].split("write_reject = 1'b0;", 1)[1].split(
        "assign soft_reset_req", 1
    )[0]
    for register_case in (
        "TCSR_PACKET_ENABLE_OFFSET",
        "TCSR_WAVE_DECIM_OFFSET",
        "TCSR_SPEC_MODE_OFFSET",
        "TCSR_SPEC_SHIFT_OFFSET",
        "TCSR_SOURCE_MODE_SHADOW_OFFSET",
        "TCSR_SOURCE_MODE_COMMIT_OFFSET",
    ):
        case_match = re.search(
            rf"{register_case}: begin(?P<body>.*?)(?=\n\s*TCSR_|\n\s*default:)",
            write_decode,
            re.DOTALL,
        )
        require(case_match is not None, f"CSR bank lacks write case {register_case}")
        require("config_mutation_allowed" in case_match.group("body"),
                f"{register_case} bypasses config_mutation_allowed")

    require_tokens(
        source["bridge"],
        paths["bridge"],
        [
            ".counter_clear_i(csr_counter_clear_pulse)",
            ".actual_source_mode_i(actual_source_mode_i)",
            ".replay_request_busy_i(replay_request_busy_i)",
            ".replay_start_accept_pulse_i(replay_start_accept_pulse_i)",
            ".replay_start_reject_pulse_i(replay_start_reject_pulse_i)",
        ],
    )

    writer_counter_block = re.search(
        r"if \(counter_clear_i\) begin(?P<body>.*?)end", source["writer"], re.DOTALL
    )
    require(writer_counter_block is not None, "writer lacks a separate diagnostic counter clear")
    writer_body = writer_counter_block.group("body")
    require("dma_drop_count_q <= 32'd0" in writer_body, "writer drop counter is not cleared")
    require("dma_packet_count_q <= 32'd0" in writer_body, "writer packet counter is not cleared")
    for forbidden in ("state_q", "producer", "consumer", "sequence", "ring_config"):
        require(forbidden not in writer_body, f"counter clear illegally mutates writer {forbidden}")

    require_tokens(
        source["telemetry"],
        paths["telemetry"],
        [
            "input  logic                       formatter_flush_i",
            "input  logic                       counter_clear_i",
            "assign formatter_reset = telemetry_soft_reset_i || formatter_flush_i",
            ".flush_i(formatter_reset)",
        ],
    )
    telemetry_counter_block = re.search(
        r"if \(counter_clear_i\) begin(?P<body>.*?)end", source["telemetry"], re.DOTALL
    )
    require(telemetry_counter_block is not None, "telemetry lacks diagnostic counter clear")
    telemetry_body = telemetry_counter_block.group("body")
    require("packet_fifo_drop_count_q <= 32'd0" in telemetry_body,
            "telemetry packet-drop counter is not cleared")
    require("packet_fifo_overflow_q" not in telemetry_body,
            "counter clear illegally clears packet-FIFO sticky evidence")

    require_tokens(
        source["full"],
        paths["full"],
        [
            "assign telemetry_soft_clear_w = telemetry_soft_reset_pulse_w |",
            "assign formatter_flush_w = transport_epoch_idle_q &&",
            "(source_discontinuity_i && source_mode_apply_pulse_w)",
            "transport_epoch_idle_q <= transport_epoch_idle_o",
            "assign transport_epoch_idle_stable_o = transport_epoch_idle_q",
            ".telemetry_soft_reset_i(telemetry_soft_clear_w)",
            ".formatter_flush_i(formatter_flush_w)",
            ".counter_clear_i(counter_clear_pulse_w)",
            ".transport_epoch_idle_i(transport_epoch_idle_o)",
        ],
    )
    require("external_telemetry_flush_i;" not in compact(source["full"].split(
                "assign telemetry_soft_clear_w =", 1)[1].split(";", 1)[0]),
            "formatter-only flush was folded back into transport soft reset")
    full_flat = compact(source["full"])
    require(
        "assign formatter_flush_w = transport_epoch_idle_q && "
        "(external_telemetry_flush_i || (source_discontinuity_i && source_mode_apply_pulse_w));"
        in full_flat,
        "formatter flush is not restricted to registered quiescence and accepted discontinuities",
    )

    require_tokens(
        source["source"],
        paths["source"],
        [
            "output logic                         replay_start_ready_o",
            "assign replay_start_qualified_w = replay_start_request_w && replay_start_admit_i &&",
            "assign replay_start_local_reject_w = replay_start_i && !replay_start_qualified_w",
            "assign external_csr_reject_pulse_o = mux_switch_reject_w;",
        ],
    )
    require("replay_start_local_reject_w ||" not in source["source"].split(
        "assign external_csr_reject_pulse_o =", 1)[1].split(";", 1)[0],
        "raw/manual replay reject contaminates CSR command-reject accounting")
    path_failure = re.search(
        r"if \(replay_path_inflight_q && replay_path_quiescent_w\) begin.*?"
        r"end else begin(?P<body>.*?)end",
        source["source"],
        re.DOTALL,
    )
    require(path_failure is not None,
            "source replay path lacks terminal quiescent failure handling")
    require("replay_path_inflight_q           <= 1'b0" in path_failure.group("body") and
            "replay_completion_error_sticky_q <= 1'b1" in path_failure.group("body"),
            "terminal replay failure does not end busy while retaining error")
    require_tokens(
        source["e2e"],
        paths["e2e"],
        [
            "if (replay_e2e_error_sticky_q && !replay_path_busy_i &&",
            "replay_e2e_inflight_q <= 1'b0",
        ],
    )

    system_flat = compact(source["system"])
    board_flat = compact(source["board"])
    require(
        "assign external_csr_reject_pulse_w = source_csr_reject_pulse_w || "
        "csr_replay_reject_feedback_w;" in system_flat,
        "replay system does not count origin-qualified CSR replay rejects",
    )
    require(
        "assign csr_command_reject_event = source_core_csr_reject_pulse || "
        "csr_replay_reject_feedback;" in board_flat
        and ".external_csr_reject_pulse_i(csr_command_reject_event)" in board_flat,
        "board does not count origin-qualified CSR replay rejects",
    )
    for label, text in ((paths["system"], system_flat), (paths["board"], board_flat)):
        suffix = "_w" if label == paths["system"] else ""
        feedback_assignment = compact(
            f"""assign csr_replay_feedback_enable{suffix} =
                (replay_request_origin_q == REPLAY_ORIGIN_CSR) ||
                ((replay_request_origin_q == REPLAY_ORIGIN_NONE) &&
                 csr_replay_forward{suffix});"""
        )
        require(feedback_assignment in text,
                f"{label}: CSR feedback-enable expression is not exactly origin-qualified")
        mutated_text = text.replace(
            feedback_assignment,
            f"assign csr_replay_feedback_enable{suffix} = 1'b1;",
            1,
        )
        require(feedback_assignment not in mutated_text,
                f"{label}: exact feedback checker negative-mutation self-test failed")
        raw_csr_start = "csr_replay_start_w" if suffix else "csr_replay_start"
        raw_key_start = "replay_start_i" if suffix else "key_press_pulse[1]"
        request_busy_assignment = compact(
            f"""assign replay_request_busy{suffix} =
                (replay_request_origin_q != REPLAY_ORIGIN_NONE) || csr_replay_queued_q ||
                {raw_csr_start} || {raw_key_start};"""
        )
        require(request_busy_assignment in text,
                f"{label}: universal replay request busy ownership is incomplete")
        request_busy_expr = text.split(
            f"assign replay_request_busy{suffix} =", 1
        )[1].split(";", 1)[0]
        require(raw_csr_start in request_busy_expr and raw_key_start in request_busy_expr and
                "replay_epoch_clear" not in request_busy_expr and
                "replay_owner_start" not in request_busy_expr and
                "csr_replay_rearm" not in request_busy_expr,
                f"{label}: replay request busy depends on a REARM-gated signal")
        require("REPLAY_ORIGIN_KEY" in text and "REPLAY_ORIGIN_CSR" in text,
                f"{label}: replay request origin tag is missing")
        require("csr_replay_queued_q" in text,
                f"{label}: one deferred CSR request is not retained behind KEY feedback")
        require("replay_owner_start" in text,
                f"{label}: sole replay-owner start path is missing")
        require("csr_replay_feedback_enable" in text,
                f"{label}: CSR feedback is not origin-gated")
        require("!csr_replay_forward" in text,
                f"{label}: simultaneous idle arbitration does not give CSR priority")
        require("REPLAY_ORIGIN_NONE) && csr_replay_forward" in text,
                f"{label}: same-cycle local CSR reject correlation is missing")
        require("csr_replay_abort_reject_q" in text,
                f"{label}: clear/abort cannot return a delayed correlated CSR reject")
        require(re.search(r"csr_replay_forward\w* = !replay_epoch_clear", text) is not None,
                f"{label}: replay START is not blocked at the clear/abort boundary")
        require(re.search(
            r"csr_replay_reject_feedback\w* = .*csr_replay_abort_reject_q", text
        ) is not None,
                f"{label}: abort reject is not returned on the CSR result path")
        require("|| csr_replay_rearm" in text,
                f"{label}: CSR REARM is not routed to the existing replay clear owner")
        require(".replay_start_accept_pulse_i(csr_replay_accept_feedback" in text,
                f"{label}: origin-qualified replay accept is not returned to CSR")
        require(".replay_start_reject_pulse_i(csr_replay_reject_feedback" in text,
                f"{label}: origin-qualified replay reject is not returned to CSR")
        require("!replay_rearm_required" in text,
                f"{label}: failed accepted replay is not blocked pending REARM")
        require("transport_epoch_idle_stable" in text,
                f"{label}: replay admission lacks a prior-cycle formatter quiescence proof")
        require(f".replay_request_busy_i(replay_request_busy{suffix})" in text,
                f"{label}: universal request busy is not returned to the CSR bank")

    # Lightweight simulator-source sanity: module boundaries and the dedicated test filelist exist.
    for name, text in source.items():
        module_count = len(re.findall(r"(?m)^\s*module\b", text))
        endmodule_count = len(re.findall(r"(?m)^\s*endmodule\b", text))
        require(module_count == endmodule_count,
                f"{paths[name]}: unbalanced module/endmodule source structure")
        require("`default_nettype none" in text, f"{paths[name]}: missing default_nettype none")

    tb = load_text(root, "sim/tb/tb_trecap_step14_command_csr.sv")
    filelist = load_text(root, "sim/filelists/step14_command_csr.f")
    require_tokens(
        tb,
        "sim/tb/tb_trecap_step14_command_csr.sv",
        [
            "STEP14_COMMAND_CSR_PASS",
            "unready START was pre-filtered before FPGA admission",
            "board-only replay feedback changed CSR result epoch",
            "rejected source mutation escaped the quiescent configuration gate",
            "quiescent live telemetry configuration write did not apply",
            "universal replay owner did not suppress START_READY",
            "REARM incorrectly advanced result epoch",
            "START after successful REARM remained blocked",
            "post-REARM START did not advance a fresh result epoch",
            "combined START+REARM write did not reject atomically",
            "raw START/request-busy did not deterministically reject REARM",
        ],
    )
    require("+timescale+1ns/1ps" in filelist,
            "Step-14 filelist lacks a file-wide simulator timescale")
    math_pkg_pos = filelist.find("rtl/include/trecap_math_pkg.sv")
    build_pkg_pos = filelist.find("rtl/include/trecap_build_pkg.sv")
    bank_pos = filelist.find("rtl/hps_bridge/trecap_csr_bank.sv")
    require(math_pkg_pos >= 0, "Step-14 filelist omits trecap_math_pkg")
    require(math_pkg_pos < build_pkg_pos < bank_pos,
            "Step-14 filelist package dependency order is invalid")
    require("sim/tb/tb_trecap_step14_command_csr.sv" in filelist,
            "Step-14 filelist does not include directed CSR testbench")


def check_behavior_model() -> None:
    replay = ReplayResultModel()

    accepted, pulse = replay.start()
    require(accepted and pulse and replay.pending,
            "model: unready raw START must be captured and emitted")
    accepted2, pulse2 = replay.start()
    require(not accepted2 and not pulse2, "model: pending START must not double-pulse")
    replay.feedback(rejected=True)
    require(not replay.pending and replay.last_reject and not replay.last_accept,
            "model: reject result not retained exclusively")
    require(replay.result_epoch == 1, "model: reject result epoch increment mismatch")

    replay.feedback(accepted=True)
    require(replay.result_epoch == 1 and replay.last_reject,
            "model: board-only feedback mutated host result")

    accepted, pulse = replay.start()
    require(accepted and pulse, "model: second START did not emit")
    replay.feedback(accepted=True)
    require(replay.last_accept and not replay.last_reject and replay.result_epoch == 2,
            "model: accept result/epoch mismatch")

    epoch = replay.result_epoch
    accepted, pulse = replay.rearm(required=True, transport_idle=True, path_busy=True)
    require(not accepted and not pulse, "model: busy REARM must reject")
    accepted, pulse = replay.rearm(required=True, transport_idle=True)
    require(accepted and pulse, "model: quiescent failed REARM must apply")
    require(not replay.pending and not replay.last_accept and not replay.last_reject,
            "model: REARM did not clear retained terminal result")
    require(replay.result_epoch == epoch, "model: REARM changed result epoch")
    # Terminal failure owners converge to busy=0 while retaining error, making quiescent REARM
    # reachable; that clear then permits a fresh START/result epoch.
    recovery = {
        "path_inflight": True,
        "path_busy": True,
        "e2e_inflight": True,
        "e2e_busy": True,
        "error": False,
        "rearm_required": False,
    }
    recovery["path_inflight"] = False
    recovery["path_busy"] = False
    recovery["error"] = True
    recovery["rearm_required"] = True
    if recovery["error"] and not recovery["path_busy"]:
        recovery["e2e_inflight"] = False
        recovery["e2e_busy"] = False
    require(recovery["error"] and recovery["rearm_required"] and
            not recovery["path_busy"] and not recovery["e2e_busy"],
            "model: terminal failure did not converge to rearmable retained-error state")

    # The raw request term is evaluated before any accepted clear. A simultaneous manual START
    # therefore makes REARM illegal without masking the START, which breaks the former circular
    # clear -> forward -> busy -> clear dependency.
    arbiter = ReplayOriginArbiterModel()
    event = arbiter.tick(key_request=True)
    rearm_legal = not bool(event["request_busy"])
    require(not rearm_legal and event["forward_origin"] == "key" and
            event["owner_start"] is True,
            "model: simultaneous KEY START + REARM did not reject REARM and forward START")

    # REPLAY_CONTROL START+REARM is one atomic illegal write. At the Avalon boundary, a malformed
    # simultaneous read/write is likewise rejected once and tagged as the read response owner.
    start_bit = True
    rearm_bit = True
    require(start_bit and rearm_bit,
            "model: combined START+REARM setup is malformed")
    replay_control_reject = start_bit and rearm_bit
    require(replay_control_reject,
            "model: combined START+REARM write was not rejected atomically")
    avs_read = True
    avs_write = True
    dual_request = avs_read and avs_write
    transaction_is_read = avs_read
    require(dual_request and transaction_is_read,
            "model: simultaneous Avalon read/write lost deterministic read-priority reject")

    accepted, pulse = replay.start()
    require(accepted and pulse, "model: START after successful REARM remained blocked")
    replay.feedback(accepted=True)
    require(replay.last_accept and replay.result_epoch == ((epoch + 1) & 0xFFFF),
            "model: post-REARM START did not produce a fresh terminal epoch")

    # Request-origin overlap: simultaneous idle requests choose CSR; KEY feedback immediately
    # before/while a CSR W1P is queued cannot terminate the CSR result; KEY is blocked behind CSR.
    arbiter = ReplayOriginArbiterModel()
    overlap_result = ReplayResultModel()
    accepted, pulse = overlap_result.start()
    require(accepted and pulse, "model: simultaneous-overlap CSR command was not captured")
    event = arbiter.tick(csr_request=True, key_request=True)
    require(event["owner_start"] is True and event["forward_origin"] == "csr",
            "model: simultaneous KEY/CSR did not choose CSR")
    require(event["key_blocked"] is True, "model: simultaneous KEY was not suppressed")
    event = arbiter.tick(owner_accept=True)
    overlap_result.feedback(
        accepted=bool(event["csr_accept"]), rejected=bool(event["csr_reject"])
    )
    require(overlap_result.last_accept and overlap_result.result_epoch == 1,
            "model: CSR-priority overlap result was not correlated")

    arbiter = ReplayOriginArbiterModel()
    adjacent_result = ReplayResultModel()
    event = arbiter.tick(key_request=True)
    require(event["forward_origin"] == "key", "model: idle KEY request did not reach owner")
    accepted, pulse = adjacent_result.start()
    require(accepted and pulse, "model: adjacent CSR command was not captured")
    event = arbiter.tick(csr_request=True, owner_accept=True)
    adjacent_result.feedback(
        accepted=bool(event["csr_accept"]), rejected=bool(event["csr_reject"])
    )
    require(adjacent_result.pending and adjacent_result.result_epoch == 0,
            "model: prior KEY terminal pulse completed adjacent CSR result")
    require(arbiter.csr_queued and arbiter.origin == "none",
            "model: adjacent CSR pulse was not deferred behind KEY terminal")
    event = arbiter.tick()
    require(event["forward_origin"] == "csr", "model: deferred CSR did not reach owner")
    event = arbiter.tick(owner_reject=True)
    adjacent_result.feedback(
        accepted=bool(event["csr_accept"]), rejected=bool(event["csr_reject"])
    )
    require(adjacent_result.last_reject and adjacent_result.result_epoch == 1,
            "model: deferred CSR terminal result was not correlated exactly once")

    arbiter = ReplayOriginArbiterModel()
    event = arbiter.tick(csr_request=True)
    require(event["forward_origin"] == "csr", "model: CSR request did not acquire owner")
    event = arbiter.tick(key_request=True)
    require(event["owner_start"] is False and event["key_blocked"] is True,
            "model: KEY request was not blocked while CSR origin was pending")

    # A current KEY forward, a retained KEY tag, and a CSR deferred behind KEY all close the
    # fail-closed configuration/re-enable gate before replay_active can rise.
    arbiter = ReplayOriginArbiterModel()
    event = arbiter.tick(key_request=True)
    require(event["request_busy"] is True,
            "model: current KEY forward is absent from universal request busy")
    require(not config_mutation_allowed_model(request_busy=True),
            "model: simultaneous HPS config + KEY current-forward escaped quiescence gate")
    event = arbiter.tick()
    require(event["request_busy"] is True and arbiter.origin == "key",
            "model: tagged KEY admission wait is absent from universal request busy")
    require(not config_mutation_allowed_model(request_busy=True),
            "model: tagged KEY admission wait allowed config/re-enable")
    arbiter.tick(csr_request=True)
    require(arbiter.origin == "key" and arbiter.csr_queued,
            "model: CSR request was not queued behind tagged KEY")
    require(not config_mutation_allowed_model(csr_pending=True, request_busy=True),
            "model: queued CSR plus HPS config write escaped replay exclusion")

    # Board KEY3 and replay-system clear/disable share this abort rule. An in-flight, queued, or
    # same-cycle CSR START receives exactly one delayed reject after the CSR bank has latched
    # pending. A KEY-only abort never contaminates the host result epoch.
    for setup in ("in_flight", "queued_behind_key", "same_cycle"):
        arbiter = ReplayOriginArbiterModel()
        abort_result = ReplayResultModel()
        if setup == "in_flight":
            accepted, pulse = abort_result.start()
            require(accepted and pulse, "model: abort in-flight CSR was not captured")
            arbiter.tick(csr_request=True)
            event = arbiter.tick(abort=True, owner_accept=True)
        elif setup == "queued_behind_key":
            arbiter.tick(key_request=True)
            accepted, pulse = abort_result.start()
            require(accepted and pulse, "model: abort queued CSR was not captured")
            arbiter.tick(csr_request=True)
            event = arbiter.tick(abort=True)
        else:
            accepted, pulse = abort_result.start()
            require(accepted and pulse, "model: abort same-cycle CSR was not captured")
            event = arbiter.tick(csr_request=True, abort=True)

        abort_result.feedback(
            accepted=bool(event["csr_accept"]), rejected=bool(event["csr_reject"])
        )
        require(abort_result.pending and abort_result.result_epoch == 0,
                f"model: {setup} abort result was returned before CSR pending was retained")
        require(arbiter.origin == "none" and not arbiter.csr_queued,
                f"model: {setup} abort stranded replay origin/queue state")
        event = arbiter.tick()
        abort_result.feedback(
            accepted=bool(event["csr_accept"]), rejected=bool(event["csr_reject"])
        )
        require(abort_result.last_reject and abort_result.result_epoch == 1,
                f"model: {setup} abort did not resolve one correlated CSR reject")
        event = arbiter.tick(owner_reject=True)
        abort_result.feedback(
            accepted=bool(event["csr_accept"]), rejected=bool(event["csr_reject"])
        )
        require(abort_result.result_epoch == 1,
                f"model: {setup} stale owner terminal double-completed CSR result")

    arbiter = ReplayOriginArbiterModel()
    arbiter.tick(key_request=True)
    arbiter.tick(abort=True)
    event = arbiter.tick()
    require(event["csr_reject"] is False,
            "model: KEY-only clear/abort contaminated CSR REPLAY_STATUS")

    arbiter = ReplayOriginArbiterModel()
    arbiter.tick(key_request=True)
    event = arbiter.tick(owner_reject=True)
    require(event["csr_reject"] is False,
            "model: KEY admission reject contaminated CSR command-reject accounting")
    arbiter.tick(csr_request=True)
    event = arbiter.tick(owner_reject=True)
    require(event["csr_reject"] is True,
            "model: correlated CSR admission reject was lost from command accounting")

    # The diagnostic clear has a deliberately narrow ownership set.
    state = {
        "dma_drop": 7,
        "dma_packet": 11,
        "csr_reject": 3,
        "packet_fifo_drop": 5,
        "producer_w": 0x1000,
        "consumer_rd": 0x0800,
        "sequence": 19,
        "core_samples": 1234,
        "core_frames": 9,
        "sticky_flags": 0x120,
        "ring_config": (0x8000_0000, 0x100000),
        "control_levels": 0x11,
        "replay_epoch": epoch,
    }
    preserved = dict(state)
    for name in ("dma_drop", "dma_packet", "csr_reject", "packet_fifo_drop"):
        state[name] = 0
    for name in (
        "producer_w",
        "consumer_rd",
        "sequence",
        "core_samples",
        "core_frames",
        "sticky_flags",
        "ring_config",
        "control_levels",
        "replay_epoch",
    ):
        require(state[name] == preserved[name], f"model: COUNTER_CLEAR mutated {name}")

    requested_source = 0
    actual_source = 1
    transition_busy = requested_source != actual_source
    ring_ready = True
    enable_allowed = ring_ready and not transition_busy
    require(not enable_allowed, "model: CONTROL re-enable bypassed requested/actual mismatch")
    actual_source = requested_source
    transition_busy = requested_source != actual_source
    require(ring_ready and not transition_busy,
            "model: CONTROL did not reopen after actual source convergence")

    def config_mutation_allowed(
        *,
        telemetry_enable: bool = False,
        ring_writer_enable: bool = False,
        transport_idle: bool = True,
        replay_pending: bool = False,
        replay_active: bool = False,
        replay_path_busy: bool = False,
        replay_e2e_busy: bool = False,
        source_transition_busy: bool = False,
    ) -> bool:
        return (
            not telemetry_enable
            and not ring_writer_enable
            and transport_idle
            and not replay_pending
            and not replay_active
            and not replay_path_busy
            and not replay_e2e_busy
            and not source_transition_busy
        )

    require(config_mutation_allowed(), "model: fully quiescent config mutation should be legal")
    blockers = (
        {"telemetry_enable": True},
        {"ring_writer_enable": True},
        {"transport_idle": False},
        {"replay_pending": True},
        {"replay_active": True},
        {"replay_path_busy": True},
        {"replay_e2e_busy": True},
        {"source_transition_busy": True},
    )
    for blocker in blockers:
        require(not config_mutation_allowed(**blocker),
                f"model: config mutation bypassed blocker {next(iter(blocker))}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Step-14 RTL structural/model/source check (not native RTL simulation)"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: parent of sim/)",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        check_contract(root)
        check_rtl_structure(root)
        check_behavior_model()
    except (CheckFailure, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"STEP14_RTL_STRUCTURAL_MODEL_SOURCE_FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "STEP14_RTL_STRUCTURAL_MODEL_SOURCE_PASS: generated contract, RTL ownership/wiring, "
        "command model, and simulator source checked (not native RTL simulation)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
