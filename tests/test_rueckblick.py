import unittest

from regeltrader.kerzen import INTERVALL_MS, Kerze
from regeltrader.konto import GEBUEHR, MUTIG, MUTIG_HEBEL, RUHIG, SCHLUPF
from regeltrader.regeln import Parameter
from regeltrader.rueckblick import (
    RASTER,
    Ergebnis,
    ausduennen,
    halten,
    robust_waehlen,
    simuliere,
    tiefster_absturz,
    waehle_mutig,
)


def kerze(i, o, h, t, s):
    return Kerze(i * INTERVALL_MS, float(o), float(h), float(t), float(s))


def flach(i, preis):
    return kerze(i, preis, preis, preis, preis)


def ergebnis(punktzahl, trades=50):
    """Fake-Ergebnis mit gewünschter Punktzahl (Absturz 10 %)."""
    return Ergebnis(rendite_pct=punktzahl * 10.0, tiefster_absturz_pct=10.0, trades=trades,
                    trefferquote_pct=50.0, groesster_trade_pct=5.0, trades_ueber_10=0,
                    verlauf=[])


def P(n_trend, n_ein, n_aus, k_stop):
    return Parameter(n_trend=n_trend, n_ein=n_ein, n_aus=n_aus, k_stop=float(k_stop))


class RasterTests(unittest.TestCase):
    def test_raster_hat_24_kombinationen(self):
        self.assertEqual(len(RASTER), 24)
        self.assertEqual(len(set(RASTER)), 24)
        self.assertEqual({p.n_trend for p in RASTER}, {100, 200})
        self.assertEqual({p.n_ein for p in RASTER}, {20, 40, 55})
        self.assertEqual({p.n_aus for p in RASTER}, {10, 20})
        self.assertEqual({p.k_stop for p in RASTER}, {2.0, 3.0})
        self.assertTrue(all(p.k_trail == 3.0 and p.n_atr == 14 for p in RASTER))


class AbsturzUndHaltenTests(unittest.TestCase):
    def test_absturz_berechnung(self):
        self.assertAlmostEqual(tiefster_absturz([100, 120, 60, 130]), 50.0)

    def test_absturz_ohne_verlust_ist_null(self):
        self.assertEqual(tiefster_absturz([100, 110, 120]), 0.0)

    def test_halten_rendite(self):
        kerzen = {"BTC": [flach(0, 100), flach(1, 150)]}
        e = halten(kerzen, {"BTC": 1.0}, 0, 2 * INTERVALL_MS)
        erwartet = (150 / (100 * (1 + SCHLUPF) * (1 + GEBUEHR)) - 1) * 100
        self.assertAlmostEqual(e.rendite_pct, erwartet, places=6)
        self.assertLess(e.rendite_pct, 50.0)
        self.assertGreater(e.rendite_pct, 49.5)
        self.assertEqual(e.trades, 0)

    def test_halten_nur_im_zeitraum(self):
        kerzen = {"BTC": [flach(0, 50), flach(1, 100), flach(2, 150), flach(3, 300)]}
        e = halten(kerzen, {"BTC": 1.0}, INTERVALL_MS, 3 * INTERVALL_MS)
        self.assertAlmostEqual(e.rendite_pct, (150 / (100 * (1 + SCHLUPF) * (1 + GEBUEHR)) - 1) * 100)

    def test_halten_50_50(self):
        kerzen = {"BTC": [flach(0, 100), flach(1, 200)], "ETH": [flach(0, 10), flach(1, 10)]}
        e = halten(kerzen, {"BTC": 0.5, "ETH": 0.5}, 0, 2 * INTERVALL_MS)
        kauf = (1 + SCHLUPF) * (1 + GEBUEHR)
        erwartet = ((5000 / kauf * 2 + 5000 / kauf) / 10000 - 1) * 100
        self.assertAlmostEqual(e.rendite_pct, erwartet)


class SimuliereTests(unittest.TestCase):
    P_KLEIN = Parameter(n_trend=5, n_ein=3, n_aus=3, k_stop=2.0, k_trail=3.0, n_atr=3)

    def reihe(self, anzahl, start=100.0, schritt=1.0):
        out = []
        for i in range(anzahl):
            s = start + i * schritt
            o = s - 0.5
            out.append(kerze(i, o, s + 0.5, o - 0.5, s))
        return out

    def test_vor_dem_zeitraum_wird_nicht_gehandelt(self):
        kerzen = {"BTC": self.reihe(30), "ETH": self.reihe(30, start=10.0, schritt=0.1)}
        e = simuliere(kerzen, self.P_KLEIN, RUHIG, 100 * INTERVALL_MS, 200 * INTERVALL_MS)
        self.assertEqual(e.trades, 0)
        self.assertEqual(e.rendite_pct, 0.0)

    def test_steigender_markt_bringt_gewinn_und_offene_position_wird_bewertet(self):
        kerzen = {"BTC": self.reihe(40), "ETH": self.reihe(40, start=10.0, schritt=0.1)}
        e = simuliere(kerzen, self.P_KLEIN, RUHIG, 0, 40 * INTERVALL_MS)
        # Steigt ununterbrochen: Position bleibt offen, kein abgeschlossener Trade,
        # aber der Kontowert am Ende enthält sie zum letzten Schluss.
        self.assertEqual(e.trades, 0)
        self.assertGreater(e.rendite_pct, 0.0)
        self.assertEqual(e.verlauf[0][1], 10000.0)
        self.assertAlmostEqual(e.verlauf[-1][1], 10000.0 * (1 + e.rendite_pct / 100))

    def test_abgeschlossene_trades_werden_gezaehlt(self):
        hoch = self.reihe(20)
        runter = []
        for j in range(10):
            i = 20 + j
            s = 119.0 - 5 * (j + 1)
            runter.append(kerze(i, s + 2, s + 2.5, s - 0.5, s))
        btc = hoch + runter
        eth = [flach(i, 10.0) for i in range(len(btc))]
        e = simuliere({"BTC": btc, "ETH": eth}, self.P_KLEIN, MUTIG, 0, len(btc) * INTERVALL_MS)
        self.assertGreaterEqual(e.trades, 1)
        self.assertEqual(len(e.verlauf), len(btc) + 1)


class RobustWaehlenTests(unittest.TestCase):
    def test_robust_waehlt_nicht_den_ausreisser(self):
        ergebnisse = {p: ergebnis(0.0) for p in RASTER}
        spitze = P(100, 20, 10, 2)
        ergebnisse[spitze] = ergebnis(100.0)
        for nachbar in [P(200, 20, 10, 2), P(100, 40, 10, 2), P(100, 20, 20, 2), P(100, 20, 10, 3)]:
            ergebnisse[nachbar] = ergebnis(-30.0)
        mitte = P(200, 40, 20, 3)
        ergebnisse[mitte] = ergebnis(30.0)
        for nachbar in [P(100, 40, 20, 3), P(200, 20, 20, 3), P(200, 55, 20, 3),
                        P(200, 40, 10, 3), P(200, 40, 20, 2)]:
            ergebnisse[nachbar] = ergebnis(28.0)
        # Die Spitze (100) ist einzeln die beste – gewählt wird trotzdem das Plateau.
        self.assertEqual(robust_waehlen(ergebnisse), mitte)

    def test_mindestens_30_trades(self):
        ergebnisse = {p: ergebnis(1.0, trades=40) for p in RASTER}
        wenig = P(200, 40, 20, 3)
        ergebnisse[wenig] = ergebnis(500.0, trades=10)
        for nachbar in [P(100, 40, 20, 3), P(200, 20, 20, 3), P(200, 55, 20, 3),
                        P(200, 40, 10, 3), P(200, 40, 20, 2)]:
            ergebnisse[nachbar] = ergebnis(5.0, trades=40)
        gewaehlt = robust_waehlen(ergebnisse)
        self.assertNotEqual(gewaehlt, wenig)
        self.assertGreaterEqual(ergebnisse[gewaehlt].trades, 30)

    def test_ohne_30_trades_fehler(self):
        ergebnisse = {p: ergebnis(1.0, trades=5) for p in RASTER}
        with self.assertRaises(ValueError):
            robust_waehlen(ergebnisse)


class WaehleMutigTests(unittest.TestCase):
    def test_waehle_mutig_ohne_hebel_bei_tiefem_absturz(self):
        mutig = Ergebnis(40.0, 30.0, 50, 40.0, 20.0, 3, [])
        hebel = Ergebnis(200.0, 60.0, 50, 40.0, 40.0, 5, [])
        self.assertEqual(waehle_mutig(mutig, hebel), MUTIG)

    def test_waehle_hebel_wenn_absturz_ok_und_punktzahl_nicht_schlechter(self):
        mutig = Ergebnis(40.0, 30.0, 50, 40.0, 20.0, 3, [])
        hebel = Ergebnis(80.0, 50.0, 50, 40.0, 40.0, 5, [])
        self.assertEqual(waehle_mutig(mutig, hebel), MUTIG_HEBEL)

    def test_waehle_mutig_wenn_hebel_punktzahl_schlechter(self):
        mutig = Ergebnis(40.0, 20.0, 50, 40.0, 20.0, 3, [])
        hebel = Ergebnis(60.0, 40.0, 50, 40.0, 40.0, 5, [])
        self.assertEqual(waehle_mutig(mutig, hebel), MUTIG)


class AusduennenTests(unittest.TestCase):
    def test_hoechstens_300_punkte_und_letzter_bleibt(self):
        verlauf = [(i, float(i)) for i in range(5000)]
        duenn = ausduennen(verlauf, 300)
        self.assertLessEqual(len(duenn), 300)
        self.assertEqual(duenn[0], verlauf[0])
        self.assertEqual(duenn[-1], verlauf[-1])

    def test_kurzer_verlauf_bleibt_gleich(self):
        verlauf = [(i, float(i)) for i in range(10)]
        self.assertEqual(ausduennen(verlauf, 300), verlauf)


class KrakenAbbruchTests(unittest.TestCase):
    def test_kraken_fuer_den_rueckblick_bricht_ab(self):
        from regeltrader.rueckblick import _lade_kerzen

        def nur_kraken(coin, start_ms, jetzt_ms):
            return [flach(0, 100.0)], "kraken"

        with self.assertRaises(SystemExit) as fehler:
            _lade_kerzen("BTC", 10 * INTERVALL_MS, hole=nur_kraken)
        self.assertIn("Kraken", str(fehler.exception))


if __name__ == "__main__":
    unittest.main()
