# Baseline PDF page 016

Historical Part I, core algorithm. Printed page 3. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=16).

[Previous](../../baseline/page-015.md) | [Index](../../README.md) | [Next](../../baseline/page-017.md)

At trigger time $\tau_m$, the frame contains the most recent $L$ samples ending at $\tau_m-1$:

$$
x_m[i]=x[\tau_m-L+i],\qquad 0\le i<L.\tag{2.3}
$$

That frame contributes to output slots $\tau_m+G+i$. Therefore sample $x[\tau_m-L+i]$ contributes to $y[\tau_m+G+i]$, which establishes the delay $D=L+G$.

### 2.3 Finite-stream signoff policy

For a finite input vector $x[0],\ldots,x[N_s-1]$, define zero extension:

$$
x_z[n]=\begin{cases}x[n],&0\le n<N_s\\0,&\text{otherwise.}\end{cases}\tag{2.4}
$$

Revision J signoff vectors require $N_s>0$. Empty input is not a signoff case. The default finite-stream policy is `full_tail`. Revision J defines the signoff frame set by active overlap after analysis-windowing, not only by raw finite-input overlap:

$$
\mathcal{M}_{\mathrm{active}}=\{m\in\mathbb{N}_0:\exists i\in\{0,\ldots,L-1\}\text{ such that }Q_w[i]\ne0\text{ and }0\le\tau_m-L+i<N_s\}.\tag{2.5}
$$

This prevents a zero-window edge frame from contributing artificial all-zero frame statistics when the only remaining real input sample lies at an analysis-window index whose quantized coefficient is zero. For the periodic square-root Hann baseline, $Q_w[0]=0$ and $Q_w[i]>0$ for $1\le i<L$, so the active-frame set reduces to

$$
\mathcal{M}_{\mathrm{active}}=\{m\in\mathbb{N}_0:\tau_m=(m+1)H\le N_s+L-2\}.\tag{2.6}
$$

For $N_s>0$, the required closed-form frame-count invariant is therefore

$$
N_{\mathrm{frames}}=\left\lfloor\frac{N_s+L-2}{H}\right\rfloor.\tag{2.7}
$$

Let

$$
\tau_{\mathrm{last}}=N_{\mathrm{frames}}H.\tag{2.8}
$$

The full-tail emitted length is

$$
N_y=\tau_{\mathrm{last}}+G+L.\tag{2.9}
$$

For a future window table with a different zero pattern, the general definition of $\mathcal{M}_{\mathrm{active}}$ is normative and the closed-form shortcut above must be re-derived. Under `full_tail`, the driver shall continue asserting sample ticks after the $N_s$ real input samples. Every post-input tick uses $x_{\mathrm{in}}=0$ from the zero-extended stream, and ticks continue until exactly $N_y$ output samples have been emitted. These post-input values are flush samples. They are not counted as original input samples. A board replay or RTL testbench that stops sample-enable immediately after $N_s$ real samples is not executing the Revision J finite-stream contract. An optional diagnostic policy `fixed_delay_truncate` may set

$$
N_y=N_s+D.\tag{2.10}
$$

That policy intentionally truncates post-interval tail energy and is not the Revision J signoff default.
