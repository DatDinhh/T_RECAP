"""Independent monitor-contract checks; no threshold/corpus results are used."""
from pathlib import Path
import copy
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor import monitor, natural_quality, match_events


def geometry(blocks=16, remainder=0):
    ns = 128 * (1 + 48 * blocks + remainder)
    return np.zeros((ns // 128 + 1, 21), dtype=np.uint64), ns


def block_rows(features, block):
    return features[1 + 48 * block:1 + 48 * (block + 1)]


def set_block(features, block, energy, band=3, peak=25):
    """Construct finite coherent aggregate fields for one constant block."""
    rows = block_rows(features, block)
    rows[:] = 0
    rows[:, band] = energy
    rows[:, 16] = energy
    moment = int(energy) * peak
    rows[:, 17] = moment % (1 << 64)
    rows[:, 20] = moment >> 64
    if energy:
        rows[:, 18] = energy // 2 or 1
        rows[:, 19] = peak


class GeometryTests(unittest.TestCase):
    def test_zero_has_invalid_frequency_and_no_events(self):
        features, ns = geometry()
        m = monitor(features, ns)
        self.assertFalse(m['valid'].any())
        self.assertTrue(np.all(m['peak'] == -1))
        self.assertEqual(m['events'], [])
        self.assertTrue(np.all(np.isfinite(m['centroid'])))
        self.assertTrue(natural_quality(m, m)['pass'])

    def test_exact_context_end_and_discarded_partial_tail(self):
        features, ns = geometry(blocks=9, remainder=47)
        # Frame0, incomplete final group, and finite flush frame are not scored.
        features[0, :] = 999
        features[1 + 48 * 9:, :] = 999
        m = monitor(features, ns)
        np.testing.assert_allclose(m['ends'], (1 + 48 * np.arange(1, 10)) / 375,
                                   rtol=0, atol=1e-15)
        self.assertEqual(len(m['ends']), 9)
        self.assertFalse(m['valid'].any())
        self.assertLess(m['ends'][-1], ns / 48000)

    def test_frame_boundary_and_future_changes_do_not_leak(self):
        features, ns = geometry()
        before = monitor(features, ns)
        set_block(features, 10, 10**10)
        after = monitor(features, ns)
        for name in ('bands', 'total', 'centroid', 'valid', 'peak', 'active'):
            np.testing.assert_array_equal(before[name][:10], after[name][:10])
        self.assertEqual(after['total'][9], 0)
        self.assertEqual(after['total'][10], 10**10)
        self.assertEqual(after['total'][11], 0)

    def test_highword_centroid_is_not_truncated_to_uint64(self):
        features, ns = geometry()
        # Four equal-power bins98,99,101,102 have mean100 and moment>2**64.
        # Their aggregate fits one band and the unsigned64 energy field.
        for block in range(16):
            set_block(features, block, 1 << 58, band=12, peak=100)
        self.assertGreater(int(features[1, 20]), 0)
        m = monitor(features, ns)
        np.testing.assert_array_equal(m['centroid'], np.full(16, 18750.0))
        self.assertTrue(m['valid'].all())

    def test_peak_is_mode_not_average_and_ties_choose_lower(self):
        features, ns = geometry()
        set_block(features, 0, 10**10)
        rows = block_rows(features, 0)
        rows[:24, 19] = 3
        rows[24:, 19] = 80
        self.assertEqual(monitor(features, ns)['peak'][0], 3)
        rows[23, 19] = 80
        self.assertEqual(monitor(features, ns)['peak'][0], 80)

    def test_invalid_feature_geometry_is_rejected(self):
        features, ns = geometry()
        with self.assertRaises(ValueError):
            monitor(features[:-1], ns)
        with self.assertRaises(ValueError):
            monitor(features.astype(np.int64), ns)


class PersistenceTests(unittest.TestCase):
    def test_requires_three_consecutive_blocks_and_no_baseline_alert(self):
        features, ns = geometry()
        for block in (8, 9):
            set_block(features, block, 10**10)
        self.assertEqual(monitor(features, ns)['events'], [])
        set_block(features, 10, 10**10)
        m = monitor(features, ns)
        self.assertEqual(len(m['events']), 1)
        self.assertEqual(m['events'][0]['block'], 10)
        self.assertEqual(m['events'][0]['band'], 3)
        self.assertEqual(m['events'][0]['time'], m['ends'][10])
        self.assertFalse(m['active'][:8].any())

    def test_continuation_emits_once_and_inactive_resets(self):
        features, ns = geometry(blocks=20)
        for block in list(range(8, 14)) + list(range(15, 19)):
            set_block(features, block, 10**10)
        self.assertEqual([e['block'] for e in monitor(features, ns)['events']], [10, 17])

    def test_absolute_floor_is_inclusive_and_below_floor_never_alerts(self):
        features, ns = geometry()
        for block in range(8, 12):
            set_block(features, block, 10**9 - 1)
        self.assertEqual(monitor(features, ns)['events'], [])
        for block in range(8, 12):
            set_block(features, block, 10**9)
        self.assertEqual(len(monitor(features, ns)['events']), 1)

    def test_fourfold_baseline_and_absolute_increase_both_required(self):
        features, ns = geometry()
        for block in range(8):
            set_block(features, block, 10**9)
        for block in range(8, 12):
            set_block(features, block, 4 * 10**9 - 1)
        self.assertEqual(monitor(features, ns)['events'], [])
        for block in range(8, 12):
            set_block(features, block, 4 * 10**9)
        self.assertEqual(len(monitor(features, ns)['events']), 1)

    def test_share_floor_prevents_tiny_relative_band_alert(self):
        features, ns = geometry()
        for block in range(16):
            set_block(features, block, 10**14, band=0, peak=3)
        for block in range(8, 12):
            rows = block_rows(features, block)
            rows[:, 3] = 10**9
            rows[:, 16] += np.uint64(10**9)
        self.assertEqual(monitor(features, ns)['events'], [])


class QualityTests(unittest.TestCase):
    def test_weak_active_band_loss_fails_despite_small_total_error(self):
        features, ns = geometry()
        for block in range(16):
            set_block(features, block, 10**14, band=0, peak=3)
            rows = block_rows(features, block)
            rows[:, 6] = 2 * 10**10  # Only0.02% of total, but task-active.
            rows[:, 16] += np.uint64(2 * 10**10)
        base = monitor(features, ns)
        got = copy.deepcopy(base)
        got['bands'][:, 6] = 0
        got['total'] -= 2 * 10**10
        q = natural_quality(base, got)
        self.assertFalse(q['pass'])
        self.assertEqual(q['per_band'][6]['active_groups'], 16)
        self.assertEqual(q['per_band'][6]['relative_error_p95_percent'], 100)

    def test_invalid_filtered_centroid_fails_even_when_numeric_error_small(self):
        features, ns = geometry()
        for block in range(16):
            set_block(features, block, 10**10, band=0, peak=0)
        base = monitor(features, ns)
        got = copy.deepcopy(base)
        got['valid'][0] = False
        got['peak'][0] = -1
        q = natural_quality(base, got)
        self.assertEqual(q['centroid_p95_hz'], 0)
        self.assertEqual(q['centroid_invalid_groups'], 1)
        self.assertFalse(q['pass'])

    def test_zero_baseline_cannot_gain_nonzero_group(self):
        features, ns = geometry()
        base = monitor(features, ns)
        set_block(features, 10, 10**10)
        q = natural_quality(base, monitor(features, ns))
        self.assertEqual(q['extra_nonzero_groups'], 1)
        self.assertFalse(q['pass'])

    def test_excluded_weak_bands_are_reported(self):
        features, ns = geometry()
        for block in range(16):
            set_block(features, block, 10**14, band=0, peak=3)
            block_rows(features, block)[:, 8] = 10**8
        base = monitor(features, ns)
        q = natural_quality(base, base)
        self.assertEqual(q['per_band'][8]['active_groups'], 0)
        self.assertEqual(q['per_band'][8]['excluded_groups'], 16)
        self.assertIsNone(q['per_band'][8]['relative_error_p95_percent'])


class EventMatchingTests(unittest.TestCase):
    def test_wrong_identity_cannot_replace_missed_event(self):
        expected = [{'band': 3, 'time': 2.0}, {'band': 6, 'time': 2.0}]
        got = [{'band': 3, 'time': 2.1}, {'band': 9, 'time': 2.1}]
        result = match_events(expected, got, .512)
        self.assertEqual(result['matched'], 1)
        self.assertEqual(result['missed'][0]['band'], 6)
        self.assertEqual(result['extra'][0]['band'], 9)
        self.assertFalse(result['pass'])

    def test_one_detection_cannot_satisfy_two_events(self):
        expected = [{'band': 3, 'time': 2.0}, {'band': 3, 'time': 2.1}]
        result = match_events(expected, [{'band': 3, 'time': 2.2}], .512)
        self.assertEqual(result['matched'], 1)
        self.assertEqual(len(result['missed']), 1)

    def test_synthetic_matching_forbids_preonset_but_natural_is_symmetric(self):
        expected = [{'band': 3, 'time': 2.0}]
        got = [{'band': 3, 'time': 1.9}]
        self.assertFalse(match_events(expected, got, .256)['pass'])
        self.assertTrue(match_events(expected, got, .256, symmetric=True)['pass'])

    def test_tolerance_includes_boundary_and_rejects_late_event(self):
        expected = [{'band': 3, 'time': 2.0}]
        self.assertTrue(match_events(expected, [{'band': 3, 'time': 2.512}], .512)['pass'])
        self.assertFalse(match_events(expected, [{'band': 3, 'time': 2.513}], .512)['pass'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
