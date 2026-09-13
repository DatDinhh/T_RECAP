#!/usr/bin/env python3
"""Adversarial semantic-freeze tests for the Step-14 command-path contract."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_command_path import validate_machine_contract  # noqa: E402
from check_ddr_ring_ownership import (  # noqa: E402
    CheckFailure,
    validate_contract_schema,
)

try:  # Present in the locked verification environment; optional on bare lab hosts.
    import jsonschema  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - dependency-minimal lab host
    jsonschema = None


Mutation = Callable[[dict[str, Any]], None]


def scalar_paths(value: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[tuple[Any, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from scalar_paths(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from scalar_paths(child, (*path, index))
    else:
        yield path, value


def alternate_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return value + "__adversarial_change"
    if value is None:
        return "not_null"
    raise AssertionError(f"unsupported scalar {value!r}")


def set_path(root: Any, path: tuple[Any, ...], value: Any) -> None:
    target = root
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


class CommandPathSemanticFreezeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(
            (ROOT / "config/boards/de1soc_command_path.json").read_text(encoding="utf-8")
        )
        cls.schema = json.loads(
            (ROOT / "spec/schemas/de1soc_command_path.schema.json").read_text(
                encoding="utf-8"
            )
        )
        cls.validator = (
            jsonschema.Draft202012Validator(cls.schema) if jsonschema is not None else None
        )

    @staticmethod
    def mutations() -> tuple[tuple[str, Mutation], ...]:
        return (
            (
                "extension_reinterprets_v1",
                lambda c: c["authority"].__setitem__("extension_policy", "v2 may reinterpret v1"),
            ),
            (
                "duplicate_reapplied",
                lambda c: c["sequence_and_replay"].__setitem__("duplicate_policy", "reapply"),
            ),
            (
                "sequence_conflict_accepted",
                lambda c: c["sequence_and_replay"].__setitem__("conflict_policy", "accept"),
            ),
            (
                "partial_failure_left_enabled",
                lambda c: c["lifecycle"].__setitem__("partial_failure_policy", "leave enabled"),
            ),
            (
                "enable_without_preconditions",
                lambda c: c["lifecycle"].__setitem__("enable_preconditions", ["none"]),
            ),
            (
                "live_control_mutation",
                lambda c: c["control_mutation_safety"].__setitem__(
                    "ordered_operation", ["write live"]
                ),
            ),
            (
                "mutation_failure_continues_enabled",
                lambda c: c["control_mutation_safety"].__setitem__(
                    "failure_policy", "continue enabled"
                ),
            ),
            (
                "wrong_counter_domain",
                lambda c: c["clear_counters"].__setitem__(
                    "fpga_counters_cleared", ["CORE_FRAME_COUNT"]
                ),
            ),
            (
                "replay_bypasses_owner",
                lambda c: c["replay_command"].__setitem__("start_policy", "bypass owner"),
            ),
            (
                "board_key_changes_csr_epoch",
                lambda c: c["replay_command"].__setitem__(
                    "result_epoch_policy", "increment on board keys"
                ),
            ),
        )

    def validate_from_temp(
        self,
        contract: dict[str, Any],
        schema: dict[str, Any],
        force_fallback: bool,
    ) -> tuple[dict[str, Any], str]:
        with tempfile.TemporaryDirectory(prefix="trecap-command-contract-") as temp:
            temp_root = Path(temp)
            contract_path = temp_root / "config/boards/de1soc_command_path.json"
            schema_path = temp_root / "spec/schemas/de1soc_command_path.schema.json"
            contract_path.parent.mkdir(parents=True)
            schema_path.parent.mkdir(parents=True)
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            return validate_machine_contract(temp_root, force_fallback)

    def assert_schema_rejects(self, contract: dict[str, Any]) -> None:
        with self.assertRaises(CheckFailure):
            validate_contract_schema(contract, self.schema, True)
        if self.validator is not None:
            with self.assertRaises(jsonschema.ValidationError):
                self.validator.validate(contract)

    def test_checked_in_contract_passes_both_validators_and_checker(self) -> None:
        self.assertEqual(self.schema.get("const"), self.contract)
        validate_contract_schema(self.contract, self.schema, True)
        if self.validator is not None:
            self.validator.validate(self.contract)
        checked, _ = self.validate_from_temp(self.contract, self.schema, True)
        self.assertEqual(checked, self.contract)

    def test_every_scalar_leaf_is_schema_frozen(self) -> None:
        paths = list(scalar_paths(self.contract))
        self.assertGreaterEqual(len(paths), 350)
        for path, value in paths:
            with self.subTest(path=path):
                mutated = copy.deepcopy(self.contract)
                set_path(mutated, path, alternate_scalar(value))
                self.assert_schema_rejects(mutated)

    def test_every_array_order_membership_and_cardinality_is_schema_frozen(self) -> None:
        arrays: list[tuple[tuple[Any, ...], list[Any]]] = []

        def collect(value: Any, path: tuple[Any, ...] = ()) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    collect(child, (*path, key))
            elif isinstance(value, list):
                arrays.append((path, value))
                for index, child in enumerate(value):
                    collect(child, (*path, index))

        collect(self.contract)
        self.assertGreaterEqual(len(arrays), 20)
        for path, value in arrays:
            candidates: list[list[Any]] = [copy.deepcopy(value) + ["unexpected_extra"]]
            if value:
                candidates.append(copy.deepcopy(value[:-1]))
            if len(value) > 1:
                candidates.append(list(reversed(copy.deepcopy(value))))
            for candidate in candidates:
                with self.subTest(path=path, candidate_size=len(candidate)):
                    mutated = copy.deepcopy(self.contract)
                    set_path(mutated, path, candidate)
                    self.assert_schema_rejects(mutated)

    def test_ten_known_safety_mutations_fail_schema_and_checker(self) -> None:
        for label, mutation in self.mutations():
            with self.subTest(label=label):
                mutated = copy.deepcopy(self.contract)
                mutation(mutated)
                self.assert_schema_rejects(mutated)
                with self.assertRaises(CheckFailure):
                    self.validate_from_temp(mutated, self.schema, True)

    def test_checker_rejects_contract_and_schema_changed_together(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["trusted_peer"]["security_scope"] = "authenticated_public_internet"
        spoofed_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "const": mutated,
        }
        validate_contract_schema(mutated, spoofed_schema, True)
        with self.assertRaises(CheckFailure):
            self.validate_from_temp(mutated, spoofed_schema, True)


if __name__ == "__main__":
    unittest.main()
