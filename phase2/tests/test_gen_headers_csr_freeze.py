#!/usr/bin/env python3
"""Negative regression tests for the Step-14 legacy CSR semantic freeze."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_headers  # noqa: E402  (repository script imported after sys.path setup)

try:  # The locked verification environment provides this; bare lab hosts may not.
    import jsonschema  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - exercised on dependency-minimal lab hosts
    jsonschema = None


Mutation = Callable[[dict[str, Any]], None]


class LegacyCsrFreezeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "spec/generated/csr_map.json").read_text(encoding="utf-8"))
        cls.schema = json.loads(
            (ROOT / "spec/schemas/csr_map.schema.json").read_text(encoding="utf-8")
        )
        cls.schema_frozen_registers = [
            item["const"] for item in cls.schema["properties"]["registers"]["prefixItems"]
        ]
        cls.schema_legacy_registers = cls.schema_frozen_registers[
            : gen_headers.LEGACY_CSR_REGISTER_COUNT
        ]
        cls.schema_validator = (
            jsonschema.Draft202012Validator(cls.schema) if jsonschema is not None else None
        )

    @staticmethod
    def register(csr: dict[str, Any], name: str) -> dict[str, Any]:
        return next(reg for reg in csr["registers"] if reg["name"] == name)

    @staticmethod
    def field(reg: dict[str, Any], name: str) -> dict[str, Any]:
        return next(field for field in reg["fields"] if field["name"] == name)

    def mutated(self, mutation: Mutation) -> dict[str, Any]:
        csr = copy.deepcopy(self.source)
        mutation(csr)
        return csr

    def assert_generator_rejected(self, csr: dict[str, Any]) -> None:
        with self.assertRaises(SystemExit):
            gen_headers.check_csr(csr)

    def assert_legacy_rejected(self, mutation: Mutation) -> None:
        csr = self.mutated(mutation)
        self.assert_generator_rejected(csr)

        # This comparison is dependency-free evidence that the schema's actual
        # prefixItems/const surface rejects the mutated legacy array.  When the
        # locked jsonschema dependency is present, also exercise Draft 2020-12
        # directly so a schema-keyword regression cannot hide behind the model.
        self.assertNotEqual(
            csr["registers"][: gen_headers.LEGACY_CSR_REGISTER_COUNT],
            self.schema_legacy_registers,
        )
        if self.schema_validator is not None:
            with self.assertRaises(jsonschema.ValidationError):
                self.schema_validator.validate(csr)

    def assert_extension_rejected(self, mutation: Mutation) -> None:
        csr = self.mutated(mutation)
        self.assert_generator_rejected(csr)
        self.assertNotEqual(csr["registers"], self.schema_frozen_registers)
        if self.schema_validator is not None:
            with self.assertRaises(jsonschema.ValidationError):
                self.schema_validator.validate(csr)

    def test_checked_in_contract_passes(self) -> None:
        gen_headers.check_csr(copy.deepcopy(self.source))
        self.assertEqual(
            self.source["registers"][: gen_headers.LEGACY_CSR_REGISTER_COUNT],
            self.schema_legacy_registers,
        )
        self.assertEqual(self.source["registers"], self.schema_frozen_registers)
        self.assertEqual(
            self.source["legacy_register_freeze"]["sha256"],
            self.schema["$defs"]["legacy_register_freeze"]["properties"]["sha256"]["const"],
        )
        if self.schema_validator is not None:
            self.schema_validator.validate(self.source)

    def test_rejects_legacy_offset_hex_mismatch(self) -> None:
        self.assert_legacy_rejected(
            lambda csr: self.register(csr, "PACKET_ENABLE").__setitem__("offset_hex", "0x020")
        )

    def test_rejects_legacy_access_mutation(self) -> None:
        self.assert_legacy_rejected(
            lambda csr: self.register(csr, "PACKET_ENABLE").__setitem__("access", "R")
        )

    def test_rejects_legacy_owner_mutation(self) -> None:
        self.assert_legacy_rejected(
            lambda csr: self.register(csr, "PACKET_ENABLE").__setitem__("owner", "fpga_counter")
        )

    def test_rejects_legacy_reset_mutation(self) -> None:
        self.assert_legacy_rejected(
            lambda csr: self.register(csr, "PACKET_ENABLE").__setitem__("reset", "0x00000001")
        )

    def test_rejects_legacy_description_mutation(self) -> None:
        self.assert_legacy_rejected(
            lambda csr: self.register(csr, "PACKET_ENABLE").__setitem__(
                "description", "silently changed"
            )
        )

    def test_rejects_legacy_field_range_mutation(self) -> None:
        def mutate(csr: dict[str, Any]) -> None:
            wave = self.field(self.register(csr, "PACKET_ENABLE"), "WAVE_EN")
            wave["lsb"] = 1
            wave["msb"] = 1

        self.assert_legacy_rejected(mutate)

    def test_rejects_legacy_field_kind_mutation(self) -> None:
        def mutate(csr: dict[str, Any]) -> None:
            wave = self.field(self.register(csr, "PACKET_ENABLE"), "WAVE_EN")
            wave["kind"] = "normal"

        self.assert_legacy_rejected(mutate)

    def test_rejects_legacy_field_description_mutation(self) -> None:
        def mutate(csr: dict[str, Any]) -> None:
            wave = self.field(self.register(csr, "PACKET_ENABLE"), "WAVE_EN")
            wave["description"] = "silently changed field meaning"

        self.assert_legacy_rejected(mutate)

    def test_rejects_legacy_field_write_semantics_mutation(self) -> None:
        def mutate(csr: dict[str, Any]) -> None:
            pulse = self.field(self.register(csr, "CONTROL"), "telemetry_soft_reset")
            pulse["write_semantics"] = "changed pulse semantics"

        self.assert_legacy_rejected(mutate)

    def test_rejects_missing_legacy_register(self) -> None:
        self.assert_legacy_rejected(
            lambda csr: csr["registers"].remove(self.register(csr, "PACKET_ENABLE"))
        )

    def test_rejects_reordered_legacy_registers(self) -> None:
        def mutate(csr: dict[str, Any]) -> None:
            csr["registers"][0], csr["registers"][1] = csr["registers"][1], csr["registers"][0]

        self.assert_legacy_rejected(mutate)

    def test_rejects_metadata_spoof_after_legacy_mutation(self) -> None:
        def mutate(csr: dict[str, Any]) -> None:
            self.register(csr, "PACKET_ENABLE")["description"] = "changed and re-hashed"
            legacy = [reg for reg in csr["registers"] if reg["offset"] <= 0x088]
            csr["legacy_register_freeze"]["sha256"] = gen_headers.sha256_bytes(
                gen_headers.canonical_compact_json_bytes(legacy)
            )

        self.assert_legacy_rejected(mutate)

    def test_rejects_extension_register_description_mutation(self) -> None:
        self.assert_extension_rejected(
            lambda data: self.register(data, "COUNTER_CLEAR").__setitem__(
                "description", "compatible post-0x088 extension wording"
            )
        )

    def test_rejects_counter_clear_functional_semantics_mutation(self) -> None:
        mutations: tuple[Mutation, ...] = (
            lambda data: self.register(data, "COUNTER_CLEAR").__setitem__(
                "write_semantics", "changed root write behavior"
            ),
            lambda data: self.field(
                self.register(data, "COUNTER_CLEAR"), "transport_counters"
            ).__setitem__("write_semantics", "changed counter-clear pulse behavior"),
            lambda data: self.field(
                self.register(data, "COUNTER_CLEAR"), "transport_counters"
            ).__setitem__("description", "changed counter ownership or preservation set"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_extension_rejected(mutation)

    def test_rejects_replay_control_functional_semantics_mutation(self) -> None:
        mutations: tuple[Mutation, ...] = (
            lambda data: self.register(data, "REPLAY_CONTROL").__setitem__(
                "write_semantics", "START and REARM may be combined"
            ),
            lambda data: self.field(self.register(data, "REPLAY_CONTROL"), "start").__setitem__(
                "write_semantics", "bypass replay admission"
            ),
            lambda data: self.field(self.register(data, "REPLAY_CONTROL"), "rearm").__setitem__(
                "write_semantics", "reset transport state"
            ),
            lambda data: self.field(self.register(data, "REPLAY_CONTROL"), "start").__setitem__(
                "description", "changed start authority"
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_extension_rejected(mutation)

    def test_rejects_replay_status_result_semantics_mutation(self) -> None:
        mutations: tuple[Mutation, ...] = (
            lambda data: self.register(data, "REPLAY_STATUS").__setitem__(
                "description", "changed epoch observation algorithm"
            ),
            lambda data: self.field(
                self.register(data, "REPLAY_STATUS"), "result_epoch"
            ).__setitem__("description", "increment on rearm too"),
            lambda data: self.field(
                self.register(data, "REPLAY_STATUS"), "last_accept"
            ).__setitem__("description", "not retained or mutually exclusive"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_extension_rejected(mutation)

    def test_offset_hex_parity_applies_to_extensions_too(self) -> None:
        self.assert_extension_rejected(
            lambda data: self.register(data, "REPLAY_STATUS").__setitem__(
                "offset_hex", "0x098"
            )
        )


if __name__ == "__main__":
    unittest.main()
