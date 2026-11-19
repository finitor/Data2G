"""Natural-loss accounting tests, without modem execution."""
import copy
import unittest

from natural_retry_study import classify_pair, outcome, summarize


def record(arm="shipped"):
    r = dict(channel="awgn", snr_db=-14, seed=2001, bytes_each_way=64, horizon_s=180,
             cfo_hz=4.5, bandwidth_cap=2, sample_rate=8000, pool_threads=1, dd_enabled=True, dd_budget_s=1,
             caller_retry_policy=arm, suppression_plan=[], suppressed_bursts=0, transmission_trace=[],
             outcome="complete", connected=True, delivered=True, acknowledged=True, disconnected=True,
             connect_s=10, delivery_s=40, ack_s=45, simulated_s=50, verified_at_a=64, verified_at_b=64,
             acknowledged_ab_bytes=64, acknowledged_ba_bytes=64, a_tx_bursts=5, b_tx_bursts=5,
             a_heard=5, b_heard=5, a_lost=0, b_lost=0, events=["A DISCONNECTED CLIENT"])
    return r


def opportunity(frame, arm, start=100):
    return dict(endpoint="A", frame=frame, occurrence=3, channel_first_sample=start, samples=100,
                suppressed=False, mode="fsk16r25-r1/2" if arm == "shipped" else "fsk8r50-r1/3")


class NaturalAccounting(unittest.TestCase):
    def test_unexposed_pairs_stay_in_denominator(self):
        a, b = record(), record("alternating_cpm")
        self.assertEqual(classify_pair(a, b)["status"], "unexposed_identical")
        pair = dict(**classify_pair(a, b), arms={"shipped": outcome(a), "alternating_cpm": outcome(b)})
        got = summarize([pair])
        self.assertEqual(got["pairs"], 1)
        self.assertEqual(got["shipped"]["confirmed_complete"], 1)

    def test_disc_only_policy_exposure_is_counted(self):
        a, b = record(), record("alternating_cpm")
        for r, arm in [(a, "shipped"), (b, "alternating_cpm")]:
            r["transmission_trace"] = [opportunity("DISC", arm)]
        got = classify_pair(a, b)
        self.assertEqual(got["status"], "exposed_prefix_matched")
        self.assertEqual(got["first_phase"], "DISC")
        self.assertEqual(got["exposure"]["alternating_cpm"], dict(connect=0, disc=1))

    def test_earlier_connect_is_first_even_if_disc_also_changes(self):
        a, b = record(), record("alternating_cpm")
        for r, arm in [(a, "shipped"), (b, "alternating_cpm")]:
            r["transmission_trace"] = [opportunity("CONNECT", arm), opportunity("DISC", arm, 200)]
        self.assertEqual(classify_pair(a, b)["first_phase"], "CONNECT")

    def test_differences_before_change_are_not_attributed(self):
        a, b = record(), record("alternating_cpm")
        b["connect_s"] += 1
        self.assertEqual(classify_pair(a, b)["status"], "unexposed_mismatch")
        a["transmission_trace"] = [opportunity("CONNECT", "shipped")]
        self.assertEqual(classify_pair(a, b)["status"], "prechange_mismatch")
        b["transmission_trace"] = [opportunity("CONNECT", "alternating_cpm", 101)]
        self.assertEqual(classify_pair(a, b)["status"], "prechange_mismatch")

    def test_wrong_input_policy_or_forced_loss_is_rejected(self):
        a, b = record(), record("alternating_cpm")
        for key, value in [("seed", 2002), ("caller_retry_policy", "shipped"), ("suppressed_bursts", 1)]:
            bad = copy.deepcopy(b); bad[key] = value
            with self.assertRaises(ValueError):
                classify_pair(a, bad)
        bad = copy.deepcopy(b)
        bad["transmission_trace"] = [opportunity("DISC", "shipped")]
        with self.assertRaises(ValueError):
            classify_pair(a, bad)

    def test_unconfirmed_close_and_failures_do_not_become_successes(self):
        r = record(); r["events"] = ["A DISCONNECTED CLIENT unconfirmed"]
        got = outcome(r)
        self.assertTrue(got["complete"])
        self.assertFalse(got["confirmed_complete"])
        self.assertEqual(got["capped_confirmed_completion_wait_s"], 180)
        r.update(connected=False, connect_s=-1, outcome="connect_timeout")
        self.assertEqual(outcome(r)["capped_connection_wait_s"], 180)


if __name__ == "__main__":
    unittest.main()
