"""Replot published accelerometer measurements or check this compact bundle."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import os
import numpy as np

ROOT = Path(__file__).resolve().parent
THRESHOLDS = [0, 10**8, 10**9, 10**10, 10**11]
LABELS = ['0', r'$10^8$', r'$10^9$', r'$10^{10}$', r'$10^{11}$']
CONDITIONS = ['original', 'added_awgn_0p10g']
BLUE = '#a8c9e3'
PEACH = '#efbd9f'
INK = '#26394a'
GREEN = '#afcdb8'


def rows(name):
    with (ROOT / 'data' / name).open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def check():
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    for record in manifest['files']:
        path = ROOT / record['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'], record['path']
    metrics = rows('metrics.csv')
    per = rows('per_recording_metrics.csv')
    assert len(metrics) == 10 and len(per) == 120
    for r in metrics:
        group = [v for v in per if v['condition'] == r['condition'] and v['threshold'] == r['threshold']]
        assert len(group) == 12
        for key in ['tp', 'fp', 'fn', 'ordinary_truth', 'ordinary_fn', 'shift_truth', 'shift_fn']:
            assert sum(int(v[key]) for v in group) == int(r[key]), (key, r['threshold'])
        tp, fp, fn = [int(r[k]) for k in ['tp', 'fp', 'fn']]
        assert tp + fn == 1665
        assert abs(float(r['f1']) - 2 * tp / (2 * tp + fp + fn)) < 1e-14
    for condition in CONDITIONS:
        before = rows('input_quantized_' + condition + '_excerpt.csv')
        zero = rows('fpga_' + condition + '_t0_excerpt.csv')
        assert before == zero, condition
    print(json.dumps({'status': 'PASS_COMPACT_ACCELEROMETER_BUNDLE', 'files': len(manifest['files']),
                      'aggregate_rows': 10, 'recording_route_rows': 120,
                      'scope': 'Published byte integrity, score accounting and threshold zero excerpt identity. No board run.'}))


def render(output):
    os.environ.setdefault('SOURCE_DATE_EPOCH', '1793750400')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
        'axes.spines.top': False, 'axes.spines.right': False, 'axes.edgecolor': '#71808b',
        'text.color': INK, 'axes.labelcolor': INK, 'xtick.color': INK, 'ytick.color': INK,
        'axes.titleweight': 'bold', 'figure.facecolor': '#fffefa', 'axes.facecolor': '#fffefa',
        'savefig.dpi': 170, 'svg.hashsalt': 'trecap-accelerometer-20261104'})
    output.mkdir(parents=True, exist_ok=True)
    metrics = rows('metrics.csv')
    lookup = {(r['condition'], int(r['threshold'])): r for r in metrics}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.3), sharey=True)
    x = np.arange(5)
    for ax, condition, title in zip(axes, CONDITIONS, ['Original recordings', 'Same recordings with added noise']):
        for shift, key, label, color in [(-.18, 'fp', 'Extra detections (FP)', BLUE),
                                         (.18, 'fn', 'Missed video events (FN)', PEACH)]:
            values = [int(lookup[condition, t][key]) for t in THRESHOLDS]
            bars = ax.bar(x + shift, values, .36, color=color, edgecolor=INK, linewidth=.5, label=label)
            ax.bar_label(bars, padding=4, fontsize=9)
        ax.set_xticks(x, LABELS)
        ax.set_xlabel('Squared-magnitude threshold')
        ax.set_title(title, fontsize=12)
        ax.set_ylim(0, 1140)
        ax.set_axisbelow(True)
        ax.grid(axis='y', alpha=.18)
        ax.legend(frameon=False, fontsize=9, loc='upper right')
    axes[0].set_ylabel('Events across 24 scored minutes')
    fig.suptitle('Rejecting false steps can also remove real steps', fontsize=17, fontweight='bold')
    fig.text(.5, .88, 'Physical FPGA outputs at all five thresholds | 1,665 video labels per condition | fixed detector', ha='center')
    fig.text(.5, .035, 'Noise is simulated Gaussian acceleration with standard deviation 0.10 g per axis.\nThresholds 10^8 and 10^9 are an exploratory follow-up on the same records.', ha='center', fontsize=9)
    fig.subplots_adjust(top=.79, bottom=.19, wspace=.12)
    save(fig, 'event_errors', plt, output)

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), sharey=True)
    for ax, key, title in zip(axes, ['precision', 'recall', 'f1'], ['Precision', 'Recall', 'F1 score']):
        for condition, color, label in [('original', '#527b99', 'Original recordings'),
                                        ('added_awgn_0p10g', '#ab704b', 'Added synthetic noise')]:
            y = [float(lookup[condition, t][key]) * 100 for t in THRESHOLDS]
            ax.plot(x, y, marker='o', markersize=7, color=color, linewidth=1.6, label=label)
        ax.set_xticks(x, LABELS)
        ax.set_xlabel('Threshold')
        ax.set_title(title)
        ax.set_ylim(50, 100)
        ax.grid(alpha=.18)
    axes[0].set_ylabel('Pooled event metric (%)')
    axes[0].legend(frameon=False, fontsize=9, loc='lower left')
    fig.suptitle('An improved F1 score does not mean every true step survived', fontsize=16, fontweight='bold')
    fig.text(.5, .035, 'Four evaluation participants, three gait activities. No retuning of the detector between routes.', ha='center', fontsize=9)
    fig.tight_layout(rect=[0, .08, 1, .9])
    save(fig, 'quality_tradeoff', plt, output)

    fig, axes = plt.subplots(5, 2, figsize=(13, 10.3), sharex=True, sharey=True)
    displayed = []
    for condition in CONDITIONS:
        for threshold in THRESHOLDS:
            values = rows('fpga_' + condition + '_t' + str(threshold) + '_excerpt.csv')
            displayed.extend(float(v['magnitude_minus_1_g']) for v in values if float(v['source_time_s']) < 70)
    minimum, maximum = min(displayed), max(displayed)
    margin = .06 * (maximum - minimum)
    for col, condition in enumerate(CONDITIONS):
        base = rows('input_quantized_' + condition + '_excerpt.csv')
        t = np.array([float(v['source_time_s']) for v in base])
        b = np.array([float(v['magnitude_minus_1_g']) for v in base])
        for row, threshold in enumerate(THRESHOLDS):
            values = rows('fpga_' + condition + '_t' + str(threshold) + '_excerpt.csv')
            y = np.array([float(v['magnitude_minus_1_g']) for v in values])
            ax = axes[row, col]
            ax.plot(t, b, color='#a1abb3', alpha=.65, lw=.8, label='Quantized input')
            ax.plot(t, y, color='#416c8e' if col == 0 else '#996746', lw=1.2, label='Returned FPGA Y')
            ax.set_xlim(60, 70)
            ax.set_ylim(minimum - margin, maximum + margin)
            ax.grid(alpha=.12)
            ax.set_title('Threshold ' + LABELS[row], loc='left', fontsize=10)
            if col == 0: ax.set_ylabel('Magnitude - 1 g')
        axes[0, col].legend(frameon=False, fontsize=8, loc='upper right')
        axes[-1, col].set_xlabel('Source time (s)')
    fig.suptitle('The same motion segment before and after thresholding', fontsize=17, fontweight='bold', y=.995)
    fig.text(.27, .951, 'Original recording', ha='center', fontsize=12, fontweight='bold')
    fig.text(.76, .951, 'Same recording with added noise', ha='center', fontsize=12, fontweight='bold')
    fig.text(.5, .015, 'Participant P003, regular gait. First 10 seconds of the published 20-second excerpt.\nAll axes use the same scale. XYZ was processed separately before forming magnitude on the laptop.', ha='center', fontsize=9)
    fig.tight_layout(rect=[0, .052, 1, .94])
    save(fig, 'waveform_thresholds', plt, output)


def save(fig, name, plt, output):
    for suffix in ['png', 'svg', 'pdf']:
        fig.savefig(output / (name + '.' + suffix), metadata={'Creator': 'T-RECAP measurement replot'})
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'replotted_figures')
    args = parser.parse_args()
    check() if args.check else render(args.output)
