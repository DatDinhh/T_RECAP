# SPDX-License-Identifier: MIT
"""Synthetic host admission checks: no serial, JTAG or child processes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import run_campaign as runner


FREQUENCY = 10_000_000
UTC = 1_800_000_000_000_000_000
QPC = 100_000_000


def fixtures():
    epochs = 16384
    anchors = [{"index": i, "qpc_before": QPC + i*FREQUENCY,
                "qpc_after": QPC + i*FREQUENCY + 50,
                "utc_ns": UTC + i*1_000_000_000, "qpc_frequency": FREQUENCY}
               for i in range(451)]
    events = []
    for i in range(12):
        mode = (1, 2, 2, 1)[i % 4]
        cycles = epochs*88331
        words = [0x54524350, (1 << 24) | 0x82 | (0x10 if mode == 1 else 0x20),
                 epochs << 16 | mode, epochs, epochs*1536, 0,
                 epochs*1024, epochs*9, cycles & 0xffffffff, cycles >> 32,
                 0xffffffff, 0, 1536, 88138, 0]
        raw = f"{sum(word << (32*j) for j, word in enumerate(words)):0120x}"
        start = UTC//1_000_000 + 30_000*(i+1)
        events.append({"event": "trial_complete", "trial_id": f"trial_{i+1:03d}",
                       "pair_id": i//2+1, "condition": "dense" if mode == 1 else "masked",
                       "threshold2": 0 if mode == 1 else 100_000_000_000,
                       "epochs": epochs, "outputs": epochs*1536,
                       "useful_inputs": epochs*1024, "frames": epochs*9,
                       "mismatch_count": 0, "fault_flags": 0,
                       "last_epoch_outputs": 1536, "last_epoch_cycles": 88138,
                       "rolling_checksum": 0, "cycles": cycles,
                       "completed": True, "probe_hex": raw,
                       "launch_before_ms": start, "launch_after_ms": start+1,
                       "completion_before_ms": start+28_900,
                       "completion_after_ms": start+29_001})
    events.append({"event": "campaign_complete", "completed": True,
                   "measured_trials": 12, "epochs_per_trial": epochs,
                   "utc_ms": UTC//1_000_000 + 420_000})
    return events, anchors


class AdmissionChecks(unittest.TestCase):
    def test_complete_abba(self):
        events, anchors = fixtures()
        result = runner.build_trials(events, anchors, FREQUENCY, 16384, 3)
        self.assertEqual(len(result["trials"]), 12)
        self.assertEqual(result["trials"][0]["input_count"], 16_777_216)
        self.assertEqual(result["trials"][0]["launch_before_qpc"], QPC + 30*FREQUENCY - 200001)

    def test_terminal_and_counter_faults(self):
        for field, value in (("outputs", 1), ("useful_inputs", 1), ("frames", 1),
                             ("epochs", 1), ("mismatch_count", 1), ("fault_flags", 4096),
                             ("last_epoch_outputs", 1), ("last_epoch_cycles", 1),
                             ("rolling_checksum", 1), ("threshold2", 1),
                             ("completed", False), ("pair_id", 2),
                             ("cycles", 0), ("condition", "masked")):
            with self.subTest(field=field):
                events, anchors = fixtures()
                events[0][field] = value
                with self.assertRaises(ValueError):
                    runner.build_trials(events, anchors, FREQUENCY, 16384, 3)

    def test_status_bits(self):
        for bit in (0, 2, 3, 6, 10):
            with self.subTest(set_fault_bit=bit):
                events, anchors = fixtures()
                events[0]["probe_hex"] = f"{int(events[0]['probe_hex'], 16) | (1 << (32+bit)):0120x}"
                with self.assertRaises(ValueError):
                    runner.build_trials(events, anchors, FREQUENCY, 16384, 3)
        for bit in (1, 7):
            with self.subTest(clear_done_bit=bit):
                events, anchors = fixtures()
                events[0]["probe_hex"] = f"{int(events[0]['probe_hex'], 16) & ~(1 << (32+bit)):0120x}"
                with self.assertRaises(ValueError):
                    runner.build_trials(events, anchors, FREQUENCY, 16384, 3)

    def test_missing_duplicate_error_or_late_event(self):
        for operation in ("missing", "duplicate", "error", "late", "reorder"):
            with self.subTest(operation=operation):
                events, anchors = fixtures()
                if operation == "missing":
                    events.pop(0)
                elif operation == "duplicate":
                    events.insert(1, copy.deepcopy(events[0]))
                elif operation == "error":
                    events.insert(0, {"event": "campaign_error"})
                elif operation == "late":
                    events.append({"event": "snapshot"})
                else:
                    events[0], events[1] = events[1], events[0]
                with self.assertRaises(ValueError):
                    runner.build_trials(events, anchors, FREQUENCY, 16384, 3)

    def test_clock_step_and_frequency(self):
        for operation in ("step", "frequency", "reverse"):
            with self.subTest(operation=operation):
                _, anchors = fixtures()
                if operation == "step":
                    anchors[5]["utc_ns"] += 20_000_000
                elif operation == "frequency":
                    anchors[5]["qpc_frequency"] += 1
                else:
                    anchors[5]["qpc_after"] = anchors[5]["qpc_before"] - 1
                with self.assertRaises(ValueError):
                    runner.check_anchors(anchors, FREQUENCY)

    def test_mapping_outward_and_out_of_range(self):
        _, anchors = fixtures()
        lo, hi, index = runner.utc_ms_bounds(UTC//1_000_000 + 500, anchors, FREQUENCY)
        self.assertEqual(index, 0)
        self.assertLessEqual(lo, QPC+FREQUENCY//2-200000)
        self.assertGreaterEqual(hi, QPC+FREQUENCY//2+200000)
        with self.assertRaises(ValueError):
            runner.utc_ms_bounds(UTC//1_000_000-1000, anchors, FREQUENCY)
        with self.assertRaises(ValueError):
            runner.utc_ms_bounds(UTC//1_000_000+200000, [anchors[0], anchors[-1]], FREQUENCY)

    def test_strict_json(self):
        for invalid in ('{"a":1,"a":2}', '{"v":NaN}', '{"v":Infinity}', '{} {}'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                runner.strict_json(invalid)
        with self.assertRaises(ValueError):
            runner.integer({"value": True}, "value")

    def test_capture_and_clean_stop(self):
        with tempfile.TemporaryDirectory(prefix="host_admission_") as temp:
            root = Path(temp)
            summary = {"ok": True, "error": None, "stopped_by_file": True,
                       "qpc_frequency": FREQUENCY, "rows": 3,
                       "sync_replies": 2, "capture_start_qpc": 1, "capture_end_qpc": 99}
            for key in ("raw_log", "metadata_jsonl", "host_receipts_jsonl", "sync_jsonl", "csv"):
                path = root/key
                path.write_text("fixture\n", encoding="utf-8")
                summary[key] = str(path)
            rows = [{"event": "sync_reply", "device_session": 1,
                     "qpc_frequency": FREQUENCY, "send_before_qpc": 10+i*10,
                     "send_after_qpc": 11+i*10, "receive_qpc": 12+i*10}
                    for i in range(2)]
            Path(summary["sync_jsonl"]).write_text("".join(json.dumps(r)+"\n" for r in rows), encoding="utf-8")
            summary["sessions"] = [{"rows": 3, "csv": summary.pop("csv")}]
            paths, session = runner.validate_capture(summary, root, FREQUENCY)
            self.assertEqual(session, 1)
            self.assertEqual(len(paths), 5)
            summary["stopped_by_file"] = False
            with self.assertRaises(ValueError):
                runner.validate_capture(summary, root, FREQUENCY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
