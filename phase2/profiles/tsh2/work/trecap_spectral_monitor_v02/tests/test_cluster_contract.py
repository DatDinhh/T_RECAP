"""Independent tests for the explicitly revised coarse-activity consumer."""
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor import cluster_events, match_events


def event(band, time, block=8):
    return {'band': band, 'time': time, 'block': block}


class ClusterContractTests(unittest.TestCase):
    def test_adjacent_alerts_join_and_keep_actual_member_times(self):
        alerts = [event(5, 2.2), event(6, 2.4)]
        original = copy.deepcopy(alerts)
        groups = cluster_events(alerts)
        self.assertEqual(alerts, original)  # Caller evidence is never mutated.
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['bands'], [5, 6])
        self.assertEqual(groups[0]['time'], 2.2)
        self.assertEqual(groups[0]['last_update_time'], 2.4)
        self.assertEqual(groups[0]['bandwidth_bands'], 2)
        self.assertEqual(groups[0]['members'], original)

    def test_window_is_fixed_to_first_alert_not_extended_by_new_members(self):
        groups = cluster_events([event(5, 2.0), event(6, 2.2), event(7, 2.4)])
        self.assertEqual([g['bands'] for g in groups], [[5, 6], [7]])
        self.assertEqual([g['time'] for g in groups], [2.0, 2.4])

    def test_nonadjacent_and_repeated_same_band_stay_separate(self):
        groups = cluster_events([event(5, 2.0), event(9, 2.1), event(5, 2.2)])
        self.assertEqual([g['bands'] for g in groups], [[5], [9], [5]])

    def test_window_boundary_is_inclusive(self):
        self.assertEqual(len(cluster_events([event(5, 2.0), event(6, 2.256)])), 1)
        self.assertEqual(len(cluster_events([event(5, 2.0), event(6, 2.257)])), 2)

    def test_later_member_cannot_borrow_anchor_to_pass_target_deadline(self):
        groups = cluster_events([event(5, 2.4), event(6, 2.6)])
        result = match_events([event(6, 2.0)], groups, .512)
        self.assertEqual(len(groups), 1)
        self.assertLess(groups[0]['time'] - 2.0, .512)
        self.assertFalse(result['pass'])
        self.assertEqual(result['matched'], 0)

    def test_matching_records_target_member_time_not_first_display_time(self):
        groups = cluster_events([event(5, 2.1), event(6, 2.3)])
        result = match_events([event(6, 2.0)], groups, .512)
        self.assertTrue(result['pass'])
        self.assertEqual(result['matches'][0]['detected_time'], 2.3)
        self.assertAlmostEqual(result['matches'][0]['delay'], .3)

    def test_two_physical_targets_can_merge_but_cannot_count_as_two_successes(self):
        # The intended resolution limitation is exposed, rather than hidden.
        groups = cluster_events([event(5, 2.2), event(6, 2.3)])
        result = match_events([event(5, 2.0), event(6, 2.0)], groups, .512)
        self.assertEqual(len(groups), 1)
        self.assertEqual(result['matched'], 1)
        self.assertEqual(len(result['missed']), 1)
        self.assertFalse(result['pass'])

    def test_order_is_deterministic_and_ties_use_earlier_created_cluster(self):
        alerts = [event(7, 2.0), event(5, 2.0), event(6, 2.1)]
        groups = cluster_events(alerts)
        self.assertEqual([g['bands'] for g in groups], [[5, 6], [7]])
        self.assertEqual(groups, cluster_events(list(reversed(alerts))))

    def test_nearest_anchor_wins_without_merging_existing_clusters(self):
        groups = cluster_events([event(5, 2.0), event(7, 2.1), event(6, 2.2)])
        self.assertEqual([g['bands'] for g in groups], [[5], [6, 7]])
        self.assertEqual(groups[1]['band'], 7)
        self.assertEqual(groups[1]['time'], 2.1)

    def test_earlier_anchor_does_not_make_postonset_member_a_preonset_detection(self):
        groups = cluster_events([event(5, 1.9), event(6, 2.1)])
        result = match_events([event(6, 2.0)], groups, .512)
        self.assertTrue(result['pass'])
        self.assertEqual(result['matches'][0]['detected_time'], 2.1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
