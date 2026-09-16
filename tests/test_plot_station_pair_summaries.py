import tempfile
import unittest
from pathlib import Path

import plot_station_pair_summaries as station_plots


class StationPairSummaryTests(unittest.TestCase):
    def test_measurement_status_prioritizes_exclusion(self):
        self.assertEqual(
            station_plots.measurement_status(
                {"manual_excluded": "True", "good": "True"}
            ),
            "X",
        )
        self.assertEqual(
            station_plots.measurement_status(
                {"manual_excluded": "False", "good": "True"}
            ),
            "A",
        )
        self.assertEqual(
            station_plots.measurement_status(
                {"manual_excluded": "False", "good": "False"}
            ),
            "R",
        )

    def test_minimum_snr_requires_both_events(self):
        self.assertEqual(
            station_plots.minimum_snr(
                {"automatic_pick1_snr": "2.5", "automatic_pick2_snr": "0.8"}
            ),
            0.8,
        )

    def test_inventory_keeps_stations_without_measurements(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inventory.csv"
            path.write_text(
                "station_id,sort_distance_degrees,first_pair_label\n"
                "IU.COLA,150.8,P30\nIU.PET,175.4,P30\n",
                encoding="utf-8",
            )
            self.assertEqual(
                station_plots.load_inventory_stations(path),
                {"IU.COLA", "IU.PET"},
            )
        self.assertIsNone(
            station_plots.minimum_snr(
                {"automatic_pick1_snr": "2.5", "automatic_pick2_snr": ""}
            )
        )


if __name__ == "__main__":
    unittest.main()
