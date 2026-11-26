import unittest

from regeltrader.indikatoren import atr, donchian_hoch, donchian_tief, ema


class TestIndikatoren(unittest.TestCase):
    def test_ema_startet_mit_sma(self):
        self.assertEqual(ema([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_atr_konstante_spanne(self):
        hoch, tief, schluss = [11] * 20, [9] * 20, [10] * 20
        ergebnis = atr(hoch, tief, schluss)
        self.assertIsNone(ergebnis[12])
        self.assertEqual(ergebnis[13], 2.0)
        self.assertEqual(ergebnis[19], 2.0)

    def test_donchian_ohne_aktuelle_kerze(self):
        self.assertEqual(donchian_hoch([1, 5, 3, 9], 2), [None, None, 5, 5])
        self.assertEqual(donchian_tief([4, 2, 6, 1], 2), [None, None, 2, 2])


if __name__ == "__main__":
    unittest.main()
