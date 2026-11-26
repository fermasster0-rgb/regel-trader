import unittest

from regeltrader.konto import (
    MUTIG, MUTIG_HEBEL, RUHIG, Konto, Position,
    finanzierung, kaufen, kontowert, nettowert, positionsgroesse, pruefe_pleite, verkaufen,
    verkaufserloes,
)


def neues_konto(stufe, bargeld=10000.0):
    return Konto(name="t", stufe=stufe, bargeld=bargeld)


class NettowertTests(unittest.TestCase):
    """Kontostand "nach allen Gebühren": offene Positionen so bewertet, als würden sie jetzt
    verkauft (Schlupf 0,05 % und Gebühr 0,1 % abgezogen, Geliehenes zurückgezahlt)."""

    def test_ohne_positionen_gleich_bargeld(self):
        k = neues_konto(RUHIG, bargeld=10123.0)
        self.assertEqual(nettowert(k, {"BTC": 100.0}), 10123.0)

    def test_verkaufserloes(self):
        self.assertAlmostEqual(verkaufserloes(2.0, 100.0), 2 * 100 * 0.9995 * 0.999, places=9)

    def test_gleich_bargeld_nach_verkauf(self):
        for stufe in (RUHIG, MUTIG, MUTIG_HEBEL):
            with self.subTest(stufe=stufe.name):
                k = neues_konto(stufe)
                kaufen(k, "BTC", 100.0, 95.0, 0, "test", {"BTC": 100.0})
                kaufen(k, "ETH", 50.0, 48.0, 0, "test", {"BTC": 100.0, "ETH": 50.0})
                preise = {"BTC": 112.0, "ETH": 47.5}
                vorher = nettowert(k, preise)
                self.assertLess(vorher, kontowert(k, preise))
                verkaufen(k, "BTC", 112.0, 1, "test")
                verkaufen(k, "ETH", 47.5, 1, "test")
                self.assertAlmostEqual(k.bargeld, vorher, places=6)

    def test_abzug_genau_die_ausstiegskosten(self):
        k = neues_konto(RUHIG, bargeld=1000.0)
        k.positionen["BTC"] = Position("BTC", 10.0, 100.0, 0, 90.0, 100.0, 0.0)
        self.assertAlmostEqual(kontowert(k, {"BTC": 200.0}), 3000.0)
        self.assertAlmostEqual(nettowert(k, {"BTC": 200.0}), 1000 + 2000 * 0.9995 * 0.999)


class KontoTests(unittest.TestCase):
    def test_groesse_ruhig_nach_risiko(self):
        k = neues_konto(RUHIG)
        m = positionsgroesse(k, "BTC", 100.0, 97.0, {"BTC": 100.0})
        self.assertAlmostEqual(m, 100 / 3, places=6)
        self.assertLess(m * 100, 4500)

    def test_groesse_gedeckelt_pro_coin(self):
        k = neues_konto(MUTIG)
        m = positionsgroesse(k, "BTC", 100.0, 99.0, {"BTC": 100.0})
        self.assertAlmostEqual(m, 90.0, places=6)

    def test_hebel_leiht(self):
        k = neues_konto(MUTIG_HEBEL)
        p = kaufen(k, "BTC", 100.0, 99.0, 0, "test", {"BTC": 100.0})
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.menge, 180.0, places=6)
        erwartet = 180 * 100.05 * 1.001 - 10000
        self.assertAlmostEqual(p.geliehen, erwartet, places=4)
        self.assertGreater(p.geliehen, 0)
        self.assertAlmostEqual(k.bargeld, 0.0, places=6)

    def test_ohne_hebel_nie_geliehen(self):
        k = neues_konto(MUTIG, bargeld=5000.0)
        k.positionen["ETH"] = Position("ETH", 50.0, 100.0, 0, 90.0, 100.0, 0.0)
        preise = {"BTC": 100.0, "ETH": 100.0}
        p = kaufen(k, "BTC", 100.0, 99.0, 0, "test", preise)
        self.assertIsNotNone(p)
        self.assertEqual(p.geliehen, 0.0)
        self.assertLess(p.menge, 50.0)
        self.assertGreater(p.menge, 49.0)
        self.assertGreaterEqual(k.bargeld, -1e-9)

    def test_kosten_rundreise(self):
        k = neues_konto(RUHIG)
        preise = {"BTC": 100.0}
        p = kaufen(k, "BTC", 100.0, 97.0, 0, "kauf", preise)
        nennwert = p.menge * 100.0
        t = verkaufen(k, "BTC", 100.0, 1, "verkauf")
        verlust = 10000.0 - k.bargeld
        self.assertAlmostEqual(verlust, nennwert * (0.001 * 2 + 0.0005 * 2), places=2)
        self.assertAlmostEqual(-t.ergebnis_usd, verlust, places=2)
        self.assertEqual(t.grund_kauf, "kauf")
        self.assertEqual(t.grund_verkauf, "verkauf")
        self.assertEqual(k.trades, [t])
        self.assertEqual(k.positionen, {})

    def test_pleite_schliesst_und_sperrt(self):
        k = neues_konto(MUTIG_HEBEL)
        kaufen(k, "BTC", 100.0, 99.0, 0, "t", {"BTC": 100.0})
        preise = {"BTC": 40.0}
        self.assertLess(kontowert(k, preise), 0)
        self.assertTrue(pruefe_pleite(k, preise, 777))
        self.assertEqual(k.trades[-1].verkauf_zeit, 777)
        self.assertEqual(k.positionen, {})
        self.assertTrue(k.pleite)
        self.assertIsNone(kaufen(k, "BTC", 40.0, 39.0, 1, "t", preise))

    def test_keine_pleite_bei_positivem_wert(self):
        k = neues_konto(RUHIG)
        self.assertFalse(pruefe_pleite(k, {"BTC": 100.0}, 5))
        self.assertFalse(k.pleite)

    def test_finanzierung_nur_auf_geliehenes(self):
        k = neues_konto(MUTIG_HEBEL)
        p = kaufen(k, "BTC", 100.0, 99.0, 0, "t", {"BTC": 100.0})
        vorher = k.bargeld
        finanzierung(k, 4)
        self.assertAlmostEqual(vorher - k.bargeld, 0.0003 * 4 / 24 * p.geliehen, places=8)

    def test_kaufen_none_bei_stop_ueber_preis_und_doppelkauf(self):
        k = neues_konto(RUHIG)
        preise = {"BTC": 100.0}
        self.assertIsNone(kaufen(k, "BTC", 100.0, 101.0, 0, "t", preise))
        self.assertIsNotNone(kaufen(k, "BTC", 100.0, 97.0, 0, "t", preise))
        self.assertIsNone(kaufen(k, "BTC", 100.0, 97.0, 1, "t", preise))


if __name__ == "__main__":
    unittest.main()
