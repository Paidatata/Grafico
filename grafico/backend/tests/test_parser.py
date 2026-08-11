import unittest
import os
import sys

# Add backend/src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from parser import coord_to_time, get_station_code

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

if __name__ == "__main__":
    unittest.main()
