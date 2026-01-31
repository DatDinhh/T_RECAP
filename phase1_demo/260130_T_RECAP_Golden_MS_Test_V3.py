# T-RECAP Phase 1 (DE10-Lite) Haar Demo - Python Golden Model ModelSim Test V2 1/30/26 (Applebee)
# Test #1 failed due to the LSFR ordering 
# LFSR -> signed noise u[n] ->  noise shaper -> x[n]
# Pairing (x0,x1) -> Haar forward (a,d) -> selective suppression -> Haar inverse -> y
# Metrics: total pairs, suppressed pairs, sum abs err, sum sq err

import csv
from dataclasses import dataclass
import matplotlib.pyplot as plt
import json
from pathlib import Path

# Output metrics
@dataclass
class Metrics:
    total_pairs: int = 0
    suppressed_pairs: int = 0
    sum_abs_err: int = 0
    sum_sq_err: int = 0

    def __str__(self):
        return (
            "Metrics:\n"
            f"  total_pairs      = {self.total_pairs}\n"
            f"  suppressed_pairs = {self.suppressed_pairs}\n"
            f"  sum_abs_err      = {self.sum_abs_err}\n"
            f"  sum_sq_err       = {self.sum_sq_err}"
        )

# Run parameters
K = 1000            # Number of Haar pairs
N = 12              # Sample bit width x[n] y[n] 
T = 15              # Threshold (0-255)
SHIFT = 3           # Noise-shaper smoothing factor
W = 16              # LFSR bit width
rseed = 0xACE1      # LFSR initial state

# Functions

def satN(z: int, N: int):
    
    lo = -(1 << (N - 1))
    hi = (1 << (N - 1)) - 1
    if z < lo:
        return lo
    if z > hi:
        return hi
    return z


def asr(z: int, k: int):
    
    """
    Arithmetic shift right (sign-preserving), equivalent to SystemVerilog '>>>'
    IMPORTANT: If ported to another language, ensure sign-extension behavior.
    """
    if k < 0:
        raise ValueError("asr: k must be >= 0")
    return z >> k


def rnd2(q: int):

    if (q & 1) == 0:  # even
        return q // 2
    # odd
    if q >= 0:
        return (q + 1) // 2
    else:
        return (q - 1) // 2


def lfsr_step(r: int, W: int):

    if r == 0:
        raise ValueError("LFSR state must be non-zero (rseed != 0)")
   
    b = ((r >> 0) ^ (r >> 2) ^ (r >> 3) ^ (r >> 5)) & 0x1
    r_next = ((b << (W - 1)) | (r >> 1)) & ((1 << W) - 1)
    return r_next


def lfsr_to_signed_noise(r: int, N: int):

    u_t = r & ((1 << N) - 1)
    u = u_t - (1 << (N - 1))
    return u


def run_trecap_phase1_csv(K_pairs: int, N: int, T: int, SHIFT: int, W: int, rseed: int, csv_path: str,):

    if K_pairs <= 0:
        raise ValueError("K_pairs must be positive")
    if rseed == 0:
        raise ValueError("rseed must be non-zero")

    r = rseed & ((1 << W) - 1)
    s = 0  
    metrics = Metrics()

    x_stream = []
    y_stream = []
    supp_hist = []   # cumulative suppression ratio
    err_hist  = []   # per-pair absolute error
    have_x0 = False
    x0 = 0
    pair_k = 0

    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["K_Pairs", "N", "T", "SHIFT", "W", "r_seed"])
        w.writerow([K_pairs, N, T, SHIFT, W, rseed])
        w.writerow(["k", "x0", "x1", "a", "d", "sk", "d_prime", "y0", "y1"])

        DEBUG_N = 10

        # Iterate over 2K samples 
        for n in range(2 * K_pairs):
            
            u = lfsr_to_signed_noise(r, N)
            x = satN(s, N)
            s = s + asr(u - s, SHIFT)
            r = lfsr_step(r, W)
            
            x_stream.append(x)

            if not have_x0:
                x0 = x
                have_x0 = True
            else:
                x1 = x
                have_x0 = False

                a = x0 + x1
                d = x0 - x1

                sk = 1 if abs(d) < T else 0
                d_prime = (1 - sk) * d

                y0 = satN(rnd2(a + d_prime), N)
                y1 = satN(rnd2(a - d_prime), N)

                y_stream.append(y0)
                y_stream.append(y1)

                e0 = x0 - y0
                e1 = x1 - y1

                metrics.total_pairs += 1
                metrics.suppressed_pairs += sk
                metrics.sum_abs_err += abs(e0) + abs(e1)
                metrics.sum_sq_err += e0 * e0 + e1 * e1

                supp_hist.append(metrics.suppressed_pairs / metrics.total_pairs)
                err_hist.append(abs(e0) + abs(e1))
                
                w.writerow([pair_k, x0, x1, a, d, sk, d_prime, y0, y1])
                pair_k += 1

    return x_stream, y_stream, metrics, supp_hist, err_hist


# Main Function 
if __name__ == "__main__":
    out_dir = Path("csv_out")
    out_dir.mkdir(exist_ok=True)

    def run_one(T_val: int):
        csv_file = out_dir / f"haar_pairs_N{N}_SHIFT{SHIFT}_W{W}_seed{rseed:04X}_T{T_val}.csv"
        x, y, m, s_hist, e_hist = run_trecap_phase1_csv(
            K_pairs=K, N=N, T=T_val, SHIFT=SHIFT, W=W, rseed=rseed, csv_path=str(csv_file)
        )
        print(f"N={N} T={T_val} SHIFT={SHIFT} W={W} rseed={rseed}")
        print(m)
        print("  Suppressed %     =", (m.suppressed_pairs / m.total_pairs)*100, "%\n")

    # T = 0 case
    run_one(0)

    # T = 2^i - 1 sweep
    for i in range(1, 9):
        run_one((2**i) - 1)