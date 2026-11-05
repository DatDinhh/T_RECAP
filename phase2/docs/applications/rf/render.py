"""Render RF application examples from retained hardware data without board access."""
from pathlib import Path
import csv
import hashlib
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
import scipy

ROOT = Path(__file__).resolve().parent
INK = "#273445"
BLUE = "#718FAE"
SAGE = "#63917A"
LILAC = "#9C85B4"
PEACH = "#C48F70"
FILL = ["#DBE9F4", "#DCEBDD", "#E7DFF0", "#F5E2D3"]
plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 10, "text.color": INK,
                    "axes.labelcolor": INK, "axes.titlecolor": INK, "axes.spines.top": False,
                    "axes.spines.right": False, "figure.facecolor": "white", "svg.fonttype": "none"})


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def figure(fig, name):
    for ext in ("png", "svg"):
        fig.savefig(ROOT / "figures" / (name + "." + ext), dpi=180, bbox_inches="tight")
    plt.close(fig)


def recover_iq(y):
    oscillator = np.resize(np.array([1, 1j, -1, -1j]), len(y))
    return resample_poly(2 * y.astype(float) / 512 * oscillator.conj(), 1, 4,
                         window=("kaiser", 8.6), padtype="constant")


def main():
    measurements = read(ROOT / "data/measurements.json")
    rows = measurements["physical_cases"]
    samples = np.load(ROOT / "data/awgn_samples.npz", allow_pickle=False)
    bindings = read(ROOT / "data/sample_bindings.json")
    assert sha(ROOT / "data/awgn_samples.npz") == bindings["array_archive_sha256"]
    checks = []
    for item in bindings["cases"]:
        y = samples[item["array"]]
        assert hashlib.sha256(y.astype("<i4").tobytes()).hexdigest() == item["valid_y_i32le_sha256"]
        assert sha(ROOT / item["raw_input"]) == item["raw_input_sha256"]
        a, b = bindings["active_real_interval"]
        target = samples["clean_y"][a:b].astype(float)
        reference = samples[f'snr{item["nominal_snr_db"]}_t0'][a:b].astype(float)
        measured = y[a:b].astype(float)
        snr = float(10 * np.log10(np.mean(target ** 2) / np.mean((measured - target) ** 2)))
        row = next(r for r in rows if r["id"] == item["id"])
        assert np.isclose(snr, row["active_interval_snr_after_db"], rtol=0, atol=1e-10)
        gain = float(10 * np.log10(np.mean((reference - target) ** 2) / np.mean((measured - target) ** 2)))
        assert np.isclose(gain, row["active_interval_snr_improvement_db"], rtol=0, atol=1e-10)
        checks.append({"id": item["id"], "recomputed_active_snr_db": snr, "recomputed_snr_gain_db": gain})

    selected = [next(r for r in rows if r["kind"] == "synthetic_awgn" and r["threshold"] == 10 ** 9
                     and r["target_iq_snr_db"] == snr) for snr in (20, 10, 0)]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(3)
    for offset, key, label, color, edge in [(-.19, "active_interval_snr_before_db", "Before threshold, FPGA T = 0", FILL[2], LILAC),
                                          (.19, "active_interval_snr_after_db", "FPGA T = 10^9", FILL[1], SAGE)]:
        bars = axes[0].bar(x + offset, [r[key] for r in selected], .38, label=label, color=color, edgecolor=edge)
        axes[0].bar_label(bars, fmt="%.2f", padding=4, fontsize=9)
    axes[0].set(ylabel="SNR against the known clean target (dB)", ylim=(-1, 25), title="Signal accuracy in the active burst")
    axes[0].legend(fontsize=8, loc="upper right")
    bars = axes[1].bar(x, [r["quiet_power_reduction_pct"] for r in selected], color=FILL[:3], edgecolor=[BLUE, SAGE, LILAC])
    axes[1].bar_label(bars, fmt="%.2f%%", padding=5)
    axes[1].set(ylabel="Quiet-window digital power reduction (%)", ylim=(0, 118), title="Background suppression in fixed windows")
    for ax in axes:
        ax.set_xticks(x, ["20 dB", "10 dB", "0 dB"])
        ax.set_xlabel("Nominal injected complex-IQ SNR")
        ax.grid(axis="y", color="#E3E7EB")
        ax.set_axisbelow(True)
    fig.suptitle("Generated OOK with AWGN, measured on DE1-SoC", fontsize=16)
    fig.text(.5, .015, "Six physical captures. Held-out seed 202. One locked threshold and no amplitude fitting.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .06, 1, .94))
    figure(fig, "awgn_hardware")

    plot_binding = read(ROOT / "data/plot_bindings.json")
    assert sha(ROOT / "data/recorded_plot_values.npz") == plot_binding["published_sha256"]
    values = np.load(ROOT / "data/recorded_plot_values.npz", allow_pickle=False)
    spectral_map = LinearSegmentedColormap.from_list("academic_rf", ["#F7F9FB", "#DBE9F4", "#C3BDD9", "#849BB7", "#384D68"])
    fig, axes = plt.subplots(2, 3, figsize=(14, 7.8), sharex="col", gridspec_kw={"height_ratios": [1, 2]})
    peak = max(float(values["spectrum_0"].max()), 1)
    for j, threshold in enumerate((0, 10 ** 10, 10 ** 11)):
        case = next(r for r in rows if r["id"] == f"fineoffset_wh2a_1_t{threshold}")
        axes[0, j].plot((np.arange(262) + .5) / 1000, values[f"power_{j}"], color=[BLUE, SAGE, PEACH][j], linewidth=1)
        axes[0, j].set_yscale("symlog", linthresh=1)
        axes[0, j].set(ylim=(0, 1e6), title=["Threshold 0", "Threshold 10^10", "Threshold 10^11"][j])
        if j == 0:
            axes[0, j].set_ylabel("1 ms mean power\n(counts squared)")
        db = 10 * np.log10(np.maximum(values[f"spectrum_{j}"], 1) / peak)
        image = axes[1, j].imshow(db.T, origin="lower", aspect="auto", extent=[0, .262144, -250, 250], vmin=-70, vmax=0, cmap=spectral_map)
        for ax in axes[:, j]:
            ax.axvspan(.004, .020, color=SAGE, alpha=.15)
            ax.axvspan(.242144, .258144, color=SAGE, alpha=.15)
        axes[1, j].set_xlabel("Capture time (s)")
        if j == 0:
            axes[1, j].set_ylabel("Offset from 433.92 MHz (kHz)")
        retained = case["decoded_payload_matches_original"]
        axes[1, j].text(.5, .97, "Payload retained" if retained else "PAYLOAD LOST", transform=axes[1, j].transAxes,
                        ha="center", va="top", color=INK, bbox={"facecolor": FILL[1] if retained else FILL[3], "edgecolor": "none", "pad": 5})
    fig.suptitle("Recorded Fineoffset-WH2A g001 after actual FPGA processing", fontsize=16)
    fig.subplots_adjust(left=.07, right=.9, bottom=.12, top=.89, wspace=.23, hspace=.22)
    fig.colorbar(image, cax=fig.add_axes([.93, .13, .012, .47]), label="Spectral power relative to one common peak (dB)")
    fig.text(.5, .035, "Shaded regions are fixed background windows. Identical scales. No clean waveform is available for this recording.", ha="center", fontsize=9)
    fig.text(.5, .005, "Source: sblakegit via rtl_433_tests, pinned commit 1aa8c29. Threshold 10^11 loses the CRC-validated message.", ha="center", fontsize=9)
    figure(fig, "recorded_rf_hardware")

    envelopes = {}
    audio = []
    for snr in (20, 10, 0):
        for threshold in (0, 10 ** 9):
            name = f"snr{snr}_t{threshold}"
            envelope = np.abs(recover_iq(samples[name]))
            envelopes[name] = envelope
            stretched = resample_poly(envelope, 192, 125, window=("kaiser", 8.6))
            sound = stretched * np.sin(2 * np.pi * 800 * np.arange(len(stretched)) / 48000)
            fade = np.sin(np.linspace(0, np.pi / 2, 480)) ** 2
            sound[:480] *= fade
            sound[-480:] *= fade[::-1]
            audio.append((name, snr, threshold, sound))
    common_gain = .70 / max(float(np.max(np.abs(a[3]))) for a in audio)
    entries = []
    for name, snr, threshold, sound in audio:
        pcm = np.rint(np.r_[np.zeros(14400), sound * common_gain, np.zeros(14400)] * 32767).astype("<i2")
        destination = ROOT / "audio" / (name + ".wav")
        wavfile.write(destination, 48000, pcm)
        rate, decoded = wavfile.read(destination)
        assert rate == 48000 and np.array_equal(pcm, decoded)
        assert np.max(np.abs(pcm.astype(int))) < 32767
        entries.append({"file": "audio/" + destination.name, "sha256": sha(destination), "nominal_snr_db": snr,
                        "threshold": threshold, "duration_seconds": len(pcm) / rate, "sample_rate_hz": rate})
    save_json(ROOT / "audio/manifest.json", {"schema": "trecap-rf-awgn-sonification-v1", "new_hardware_run": False,
        "source": "Retained actual FPGA captures of project-generated AWGN examples", "tone_hz": 800,
        "slowdown_factor": 8, "iq_rate_hz": 250000, "playback_rate_hz": 48000, "common_gain": common_gain,
        "per_clip_normalization": False, "agc": False, "noise_gate": False, "padding_seconds_each_side": .3,
        "outer_ramp_seconds": .01, "mapping": "Magnitude of recovered IQ controls the amplitude of an added audible carrier.",
        "meaning": "Illustrative sonification, not speech or sound transmitted by the source. Loudness is not an RF quality metric.",
        "files": entries, "sample_bindings_sha256": sha(ROOT / "data/sample_bindings.json"), "generator_sha256": sha(Path(__file__))})

    fig, axes = plt.subplots(3, 1, figsize=(12, 6.5), sharex=True, sharey=True)
    for ax, envelope, label, color in zip(axes,
        [np.abs(recover_iq(samples["clean_y"])), envelopes["snr10_t0"], envelopes["snr10_t1000000000"]],
        ["Known clean target", "Noisy input after FPGA at threshold 0", "Actual FPGA output at threshold 10^9"], [LILAC, BLUE, SAGE]):
        block = 64
        n = len(envelope) // block
        power = envelope[:n * block].reshape(n, block).mean(axis=1)
        ax.plot((np.arange(n) + .5) * block / 250000, power, color=color, linewidth=1.2)
        ax.set_ylabel("IQ magnitude")
        ax.set_title(label, loc="left", fontsize=11)
        ax.set_ylim(0, .17)
        ax.grid(color="#E3E7EB")
    axes[-1].set_xlabel("Original capture time (s)")
    fig.suptitle("The 10 dB example: background falls while the burst remains", fontsize=16)
    fig.text(.5, .01, "Common 64-IQ-sample display average. Audio uses unsmoothed magnitude and a shared gain across all six examples.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .045, 1, .95))
    figure(fig, "awgn_envelopes")

    with (ROOT / "data/physical_cases.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["id", "kind", "threshold", "epoch", "active_interval_snr_before_db", "active_interval_snr_after_db",
                  "active_interval_snr_improvement_db", "quiet_power_reduction_pct", "quiet_ac_power_reduction_pct",
                  "burst_reference_relative_l2_pct", "decoded_payload_matches_original", "valid_prefix_packet_bytes",
                  "dense_valid_prefix_bytes", "savings_vs_dense_valid_prefix_pct", "y_exact", "tsp1_exact"]
        writer = csv.DictWriter(stream, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    save_json(ROOT / "render_audit.json", {"status": "PASS_RETAINED_DATA_RENDER", "new_hardware_execution": False,
        "numpy": np.__version__, "scipy": scipy.__version__, "matplotlib": matplotlib.__version__,
        "generator_sha256": sha(Path(__file__)), "awgn_snr_checks": checks, "figures": 3, "audio_examples": 6,
        "scope": "Existing waveform values and reported metrics are checked and rendered. No new FPGA, proof or simulation run."})
    print(json.dumps({"status": "PASS_RETAINED_DATA_RENDER", "figures": 3, "audio_examples": 6, "metric_checks": len(checks)}))


if __name__ == "__main__":
    main()
