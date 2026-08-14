import unittest
import os
import sys

# Add backend/src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from parser import coord_to_time, compute_train_codes, disambiguate_trip_ids, get_station_code

class TestParserConversions(unittest.TestCase):
    
    def test_coord_to_time(self):
        # 1 minute = 20 units, 1 hour = 1200 units
        # X = 0 -> 00:00:00
        self.assertEqual(coord_to_time(0), "00:00:00")
        
        # X = 5720.0815 -> 5720.0815 / 20 = 286.004 minutes -> 4 hours 46 minutes
        self.assertEqual(coord_to_time(5720.0815)[:5], "04:46")
        
        # X = 5920.0815 -> 4 hours 56 minutes
        self.assertEqual(coord_to_time(5920.0815)[:5], "04:56")
        
        # X = 12000 -> 10 hours 00 minutes
        self.assertEqual(coord_to_time(12000), "10:00:00")

    def test_get_station_code(self):
        # Y = 500.32 -> RGS (Rio Grande da Serra)
        self.assertEqual(get_station_code(500.32), "RGS")
        
        # Y = 5860.32 -> BFU (Barra Funda)
        self.assertEqual(get_station_code(5860.32), "BFU")
        
        # Y = 11520.32 -> JUN (Jundiaí)
        self.assertEqual(get_station_code(11520.32), "JUN")
        
        # Sligthly offset Y should still snap to nearest station
        self.assertEqual(get_station_code(501.0), "RGS")
        self.assertEqual(get_station_code(5859.9), "BFU")
        
        # Far away Y coordinate should return None
        self.assertIsNone(get_station_code(100.0))
        self.assertIsNone(get_station_code(15000.0))


class TestDisambiguateTripIds(unittest.TestCase):

    def test_leaves_unique_ids_untouched(self):
        trips = [{"trip_id": "TRIP_BFU-RGS_050000"}, {"trip_id": "TRIP_BFU-RGS_060000"}]
        disambiguate_trip_ids(trips)
        self.assertEqual([t["trip_id"] for t in trips], ["TRIP_BFU-RGS_050000", "TRIP_BFU-RGS_060000"])

    def test_suffixes_later_occurrences_of_a_collision(self):
        # Reproduces the real-data collision: two distinct trips (different stop
        # lists) sharing direction + start_time.
        trips = [
            {"trip_id": "TRIP_RGS-BFU_043700", "stops": ["SAN", "PSA"]},
            {"trip_id": "TRIP_RGS-BFU_043700", "stops": ["MAU", "CPV"]},
        ]
        disambiguate_trip_ids(trips)
        self.assertEqual(trips[0]["trip_id"], "TRIP_RGS-BFU_043700")
        self.assertEqual(trips[1]["trip_id"], "TRIP_RGS-BFU_043700_2")

    def test_handles_three_way_collision(self):
        trips = [{"trip_id": "X"}, {"trip_id": "X"}, {"trip_id": "X"}]
        disambiguate_trip_ids(trips)
        self.assertEqual([t["trip_id"] for t in trips], ["X", "X_2", "X_3"])

    def test_result_has_no_duplicate_ids(self):
        trips = [{"trip_id": "A"}, {"trip_id": "B"}, {"trip_id": "A"}, {"trip_id": "A"}, {"trip_id": "B"}]
        disambiguate_trip_ids(trips)
        ids = [t["trip_id"] for t in trips]
        self.assertEqual(len(ids), len(set(ids)))


def _trip(start_time, origin_station, origin_y, dest_station, dest_y):
    return {
        "start_time": start_time,
        "stops": [
            {"station": origin_station, "y_coord": origin_y},
            {"station": dest_station, "y_coord": dest_y},
        ],
    }


class TestComputeTrainCodes(unittest.TestCase):

    def test_bfu_destination_gets_odd_p_codes_in_departure_order(self):
        trips = [
            _trip("05:00:00", "RGS", 500.32, "BFU", 5860.32),
            _trip("04:30:00", "RGS", 500.32, "BFU", 5860.32),
        ]
        compute_train_codes(trips)
        # Earlier departure (04:30) gets the smaller odd number, regardless of list order.
        codes_by_start = {t["start_time"]: t["train_code"] for t in trips}
        self.assertEqual(codes_by_start["04:30:00"], "P1")
        self.assertEqual(codes_by_start["05:00:00"], "P3")

    def test_rgs_destination_gets_even_r_codes(self):
        trips = [
            _trip("04:30:00", "BFU", 5860.32, "RGS", 500.32),
            _trip("05:00:00", "BFU", 5860.32, "RGS", 500.32),
        ]
        compute_train_codes(trips)
        self.assertEqual(trips[0]["train_code"], "R2")
        self.assertEqual(trips[1]["train_code"], "R4")

    def test_mau_destination_gets_even_m_codes(self):
        trips = [_trip("04:30:00", "BFU", 5860.32, "MAU", 2100.32)]
        compute_train_codes(trips)
        self.assertEqual(trips[0]["train_code"], "M2")

    def test_rgs_and_mau_share_one_even_sequence(self):
        # Same start_time is fine here (different destinations don't collide);
        # ordering between them then falls to the y-distance tiebreak.
        trips = [
            _trip("04:30:00", "BFU", 5860.32, "MAU", 2100.32),   # shorter route
            _trip("04:30:00", "BFU", 5860.32, "RGS", 500.32),    # longer route
            _trip("05:00:00", "BFU", 5860.32, "RGS", 500.32),
        ]
        compute_train_codes(trips)
        codes = sorted(t["train_code"] for t in trips)
        self.assertEqual(codes, ["M2", "R4", "R6"])

    def test_same_start_time_breaks_tie_by_geographic_proximity_to_destination(self):
        # Reproduces the real collision: two RGS-BFU trips both starting 04:37:00,
        # one from SAN (closer to BFU) and one from MAU (farther from BFU).
        trips = [
            _trip("04:37:00", "MAU", 2100.32, "BFU", 5860.32),  # farther -> larger number
            _trip("04:37:00", "SAN", 2980.32, "BFU", 5860.32),  # closer -> smaller number
        ]
        compute_train_codes(trips)
        codes_by_origin = {t["stops"][0]["station"]: t["train_code"] for t in trips}
        self.assertEqual(codes_by_origin["SAN"], "P1")
        self.assertEqual(codes_by_origin["MAU"], "P3")

    def test_raises_on_unknown_destination(self):
        trips = [_trip("04:30:00", "BFU", 5860.32, "LUZ", 5380.32)]
        with self.assertRaises(ValueError):
            compute_train_codes(trips)


if __name__ == "__main__":
    unittest.main()
