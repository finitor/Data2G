"""Evidence-accounting tests; no modem execution or third-party dependencies."""
import copy
import unittest

from study_retries import exposure, matching_prefix


def tx(endpoint, frame, occurrence, first, mode="fsk16r25-r1/2", suppressed=False):
    return dict(endpoint=endpoint, frame=frame, occurrence=occurrence,
                channel_first_sample=first, samples=100, mode=mode, suppressed=suppressed)


def record():
    return dict(suppression_plan_applied=True, sample_rate=8000, connected=True,
                disconnected=True, connect_s=1, simulated_s=2,
                transmission_trace=[tx("A", "CONNECT", 1, 0, suppressed=True),
                                    tx("A", "CONNECT", 2, 200, suppressed=True),
                                    tx("A", "CONNECT", 3, 400, "fsk8r50-r1/3")])


class EvidenceAccounting(unittest.TestCase):
    def test_exercised_candidate(self):
        r = record()
        got = exposure(r, "connect", "alternating_cpm")
        self.assertTrue(got["eligible"])
        self.assertTrue(got["stage_recovered"])
        self.assertEqual(got["stage_recovery_s"], .95)
        r["connected"] = False
        got = exposure(r, "connect", "alternating_cpm")
        self.assertTrue(got["eligible"])
        self.assertFalse(got["stage_recovered"])
        self.assertIsNone(got["stage_recovery_s"])

    def test_unapplied_or_unreached_is_not_evidence(self):
        r = record()
        r["suppression_plan_applied"] = False
        self.assertFalse(exposure(r, "connect", "alternating_cpm")["eligible"])
        r = record()
        r["transmission_trace"].pop()
        self.assertFalse(exposure(r, "connect", "alternating_cpm")["eligible"])

    def test_ack_loss_after_third_attempt_requires_later_opportunity(self):
        r = record()
        r["transmission_trace"] += [tx("B", "CONNECT_ACK", 2, 600, suppressed=True)]
        self.assertFalse(exposure(r, "connect_ack", "alternating_cpm")["eligible"])
        r["transmission_trace"] += [tx("A", "CONNECT", 4, 800), tx("A", "CONNECT", 5, 1000, "fsk8r50-r1/3")]
        self.assertTrue(exposure(r, "connect_ack", "alternating_cpm")["eligible"])

    def test_wrong_mode_is_not_exposure(self):
        self.assertFalse(exposure(record(), "connect", "shipped")["eligible"])

    def test_matching_history_excludes_changed_waveform(self):
        a, b = record(), record()
        b["transmission_trace"][-1]["mode"] = "fsk16r25-r1/2"
        b["transmission_trace"][-1]["samples"] = 200
        self.assertTrue(matching_prefix(a, b, "connect"))
        b["transmission_trace"][0]["channel_first_sample"] += 1
        self.assertFalse(matching_prefix(a, b, "connect"))

    def test_disc_has_separate_target_and_end(self):
        r = record()
        for t in r["transmission_trace"]:
            t["frame"] = "DISC"
        self.assertTrue(exposure(r, "disc", "alternating_cpm")["eligible"])
        self.assertEqual(exposure(r, "disc", "alternating_cpm")["stage_recovery_s"], 1.95)
        self.assertFalse(matching_prefix(r, record(), "disc"))


if __name__ == "__main__":
    unittest.main()
