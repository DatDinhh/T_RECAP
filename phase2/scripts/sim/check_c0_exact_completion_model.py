#!/usr/bin/env python3
"""Dependency-free model checks for the C0 exact-completion contract."""

from dataclasses import dataclass


L = 256
H = 128
G = 128
D = G + L


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def geometry(ns: int) -> tuple[int, int, int]:
    if ns <= 0:
        raise ValueError("Revision-J finite replay requires Ns > 0")
    nframes = (ns + L - 2) // H
    tau_last = nframes * H
    ny = tau_last + D
    return nframes, tau_last, ny


def start_allowed(
    *,
    rst_n: bool,
    clear: bool,
    config_valid: bool,
    structural_busy: bool,
    run_inflight: bool,
    replay_done: bool,
    done: bool,
    restart_allowed: bool,
) -> bool:
    return (
        rst_n
        and not clear
        and config_valid
        and not structural_busy
        and not run_inflight
        and (
            (not replay_done and not done)
            or (restart_allowed and done)
        )
    )


@dataclass
class Completion:
    expected_outputs: int
    run_inflight: bool = False
    done: bool = False
    done_pulses: int = 0
    public_outputs: int = 0
    error: bool = False

    @property
    def busy(self) -> bool:
        return self.run_inflight

    def start(self) -> None:
        require(not self.run_inflight, "start accepted while a run is already in flight")
        self.run_inflight = True
        self.done = False
        self.public_outputs = 0
        self.error = False

    def accept_output(self, sample_idx: int) -> None:
        invalid = (
            not self.run_inflight
            or self.public_outputs >= self.expected_outputs
            or sample_idx != self.public_outputs
        )
        if invalid:
            self.error = True
            self.done = False
        if self.run_inflight and self.public_outputs < self.expected_outputs:
            self.public_outputs += 1

    def observe_quiescence(
        self,
        *,
        replay_outputs: int,
        wola_outputs: int,
        analysis_samples: int,
        frames: int,
        expected_analysis_samples: int,
        expected_frames: int,
    ) -> None:
        if not self.run_inflight:
            return
        exact = (
            self.public_outputs == self.expected_outputs
            and replay_outputs == self.expected_outputs
            and wola_outputs == self.expected_outputs
            and analysis_samples == expected_analysis_samples
            and frames == expected_frames
        )
        if exact and not self.error:
            self.run_inflight = False
            self.done = True
            self.done_pulses += 1
        else:
            self.error = True


def check_normal_final_stall() -> None:
    nframes, tau_last, ny = geometry(1024)
    state = Completion(ny)
    state.start()

    for index in range(ny - 1):
        state.accept_output(index)

    # Replay and WOLA may both be finished while the public output buffer holds y[Ny-1].
    require(state.public_outputs == ny - 1, "final stall did not stop at Ny-1")
    require(state.busy, "busy dropped during the final-output stall")
    require(not state.done, "done asserted during the final-output stall")
    require(not state.error, "normal run raised an error before final output")

    state.accept_output(ny - 1)
    require(state.public_outputs == ny, "final public output was not counted")
    require(state.busy, "busy dropped on the final handshake edge")
    require(not state.done, "done asserted on the final handshake edge")

    state.observe_quiescence(
        replay_outputs=ny,
        wola_outputs=ny,
        analysis_samples=tau_last,
        frames=nframes,
        expected_analysis_samples=tau_last,
        expected_frames=nframes,
    )
    require(not state.busy, "busy remained high after exact quiescence")
    require(state.done, "done did not assert after exact quiescence")
    require(state.done_pulses == 1, "normal run did not produce exactly one done pulse")
    require(not state.error, "normal exact completion raised an error")


def check_fail_closed_faults() -> None:
    nframes, tau_last, ny = geometry(1024)

    undercount = Completion(ny)
    undercount.start()
    for index in range(ny - 1):
        undercount.accept_output(index)
    undercount.observe_quiescence(
        replay_outputs=ny,
        wola_outputs=ny,
        analysis_samples=tau_last,
        frames=nframes,
        expected_analysis_samples=tau_last,
        expected_frames=nframes,
    )
    require(undercount.busy, "undercount did not remain fail-closed busy")
    require(not undercount.done, "undercount produced false done")
    require(undercount.error, "undercount did not set completion error")

    wrong_index = Completion(ny)
    wrong_index.start()
    wrong_index.accept_output(1)
    require(wrong_index.public_outputs == 1, "wrong-index beat was not counted")
    require(wrong_index.error, "wrong-index beat did not set completion error")
    wrong_index.observe_quiescence(
        replay_outputs=ny,
        wola_outputs=ny,
        analysis_samples=tau_last,
        frames=nframes,
        expected_analysis_samples=tau_last,
        expected_frames=nframes,
    )
    require(wrong_index.busy, "wrong-index run did not remain fail-closed busy")
    require(not wrong_index.done, "wrong-index run produced false done")

    extra = Completion(ny)
    extra.start()
    for index in range(ny):
        extra.accept_output(index)
    extra.observe_quiescence(
        replay_outputs=ny,
        wola_outputs=ny,
        analysis_samples=tau_last,
        frames=nframes,
        expected_analysis_samples=tau_last,
        expected_frames=nframes,
    )
    require(extra.done, "exact run did not complete before extra-output injection")
    extra.accept_output(ny)
    require(not extra.done, "extra output failed to revoke done")
    require(extra.error, "extra output did not set completion error")


def check_geometry_boundaries() -> None:
    for ns in (1, 2, 127, 128, 129, 1024, 4096):
        nframes, tau_last, ny = geometry(ns)
        require(nframes > 0, f"Ns={ns}: nonpositive frame count")
        require(tau_last >= ns - 1, f"Ns={ns}: tau_last precedes stream")
        require(tau_last - ns < L, f"Ns={ns}: active flush is too long")
        require(ny == tau_last + D, f"Ns={ns}: Ny geometry mismatch")


def check_start_admission() -> None:
    initial = {
        "rst_n": True,
        "clear": False,
        "config_valid": True,
        "structural_busy": False,
        "run_inflight": False,
        "replay_done": False,
        "done": False,
        "restart_allowed": False,
    }
    require(start_allowed(**initial), "valid initial start was rejected")

    for blocker in ("clear", "structural_busy", "run_inflight"):
        blocked = dict(initial)
        blocked[blocker] = True
        require(
            not start_allowed(**blocked),
            f"start was admitted while {blocker} was asserted",
        )

    invalid = dict(initial)
    invalid["config_valid"] = False
    require(not start_allowed(**invalid), "invalid configuration admitted a start")

    in_reset = dict(initial)
    in_reset["rst_n"] = False
    require(not start_allowed(**in_reset), "reset admitted a start")

    restart = dict(initial)
    restart["replay_done"] = True
    restart["done"] = True
    require(not start_allowed(**restart), "disabled restart was admitted")
    restart["restart_allowed"] = True
    require(start_allowed(**restart), "enabled post-done restart was rejected")


def main() -> None:
    check_geometry_boundaries()
    check_start_admission()
    check_normal_final_stall()
    check_fail_closed_faults()
    print(
        "C0_EXACT_COMPLETION_MODEL_PASS "
        "Ns=1024 frames=9 tau_last=1152 Ny=1536 faults=3"
    )


if __name__ == "__main__":
    main()
