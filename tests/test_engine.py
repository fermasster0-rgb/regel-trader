import copy
import math
import random
import unittest

from regeltrader.engine import verarbeite_kerze
from regeltrader.kerzen import INTERVALL_MS, Kerze
from regeltrader.konto import MUTIG_HEBEL, RUHIG, Konto, Position
from regeltrader.regeln import Parameter, berechne

P_KLEIN = Parameter(n_trend=5, n_ein=3, n_aus=3, k_stop=2.0, k_trail=3.0, n_atr=3)


def kerze(i, o, h, t, s):
    return Kerze(i * INTERVALL_MS, float(o), float(h), float(t), float(s))


def steigende_reihe(anzahl):
    """Schluss 100, 101, 102 ... – jede Kerze bricht über das Hoch davor aus."""
    reihe = []
    for i in range(anzahl):
        s = 100.0 + i
        o = s - 0.5
        reihe.append(kerze(i, o, s + 0.5, o - 0.5, s))
    return reihe


def neues_konto():
    return Konto(name="t", stufe=RUHIG)


def mit_position(stop, hoechster=100.0, einstieg=100.0):
    k = neues_konto()
    k.positionen["BTC"] = Position("BTC", 10.0, einstieg, 0, stop, hoechster, 0.0, "test")
    k.bargeld -= 10.0 * einstieg
    return k


def lauf(konto, kerzen, p, bis, bremse=False, preise=None, coin="BTC"):
    ind = berechne(kerzen, p)
    preise = {} if preise is None else preise
    ereignisse = []
    for i in range(bis + 1):
        ereignisse += verarbeite_kerze(konto, coin, kerzen, ind, i, p, bremse, preise)
    return ereignisse


class EngineTests(unittest.TestCase):
    def test_ausbruch_kauft_zur_naechsten_eroeffnung(self):
        kerzen = steigende_reihe(8)
        k = neues_konto()
        ind = berechne(kerzen, P_KLEIN)
        preise = {}
        for i in range(5):
            verarbeite_kerze(k, "BTC", kerzen, ind, i, P_KLEIN, False, preise)
        # Kerze 4 ist die erste mit allen Indikatoren -> Kauf nur vorgemerkt
        self.assertNotIn("BTC", k.positionen)
        self.assertEqual(k.vorgemerkt["BTC"]["art"], "kauf")
        abstand = k.vorgemerkt["BTC"]["stop_abstand"]
        self.assertAlmostEqual(abstand, 2.0 * ind.atr[4])
        ereignisse = verarbeite_kerze(k, "BTC", kerzen, ind, 5, P_KLEIN, False, preise)
        pos = k.positionen["BTC"]
        fill = kerzen[5].eroeffnung * 1.0005
        self.assertAlmostEqual(pos.einstieg, fill)
        self.assertEqual(pos.einstieg_zeit, kerzen[5].zeit)
        self.assertAlmostEqual(pos.stop, fill - abstand)
        self.assertIn("Ausbruch über das 3-Kerzen-Hoch", pos.grund_kauf)
        self.assertNotIn("BTC", k.vorgemerkt)
        self.assertTrue(any("BTC gekauft" in e for e in ereignisse))

    def test_stop_innerhalb_der_kerze(self):
        k = mit_position(stop=95.0)
        kerzen = [kerze(0, 100, 101, 94, 98)]
        ereignisse = lauf(k, kerzen, P_KLEIN, 0)
        self.assertNotIn("BTC", k.positionen)
        self.assertEqual(len(k.trades), 1)
        self.assertAlmostEqual(k.trades[0].verkauf_preis, 95 * 0.9995)
        self.assertEqual(k.trades[0].grund_verkauf, "Verlust-Limit erreicht")
        self.assertTrue(any("BTC verkauft" in e for e in ereignisse))

    def test_kursluecke_unter_stop(self):
        k = mit_position(stop=95.0)
        kerzen = [kerze(0, 90, 92, 88, 91)]
        lauf(k, kerzen, P_KLEIN, 0)
        self.assertEqual(len(k.trades), 1)
        self.assertAlmostEqual(k.trades[0].verkauf_preis, 90 * 0.9995)
        self.assertEqual(k.trades[0].grund_verkauf, "Verlust-Limit erreicht")

    def test_stop_wird_nur_nach_oben_gezogen(self):
        kerzen = [kerze(i, 100, 101, 99, 100) for i in range(5)]
        kerzen.append(kerze(5, 104, 110.5, 103.5, 110))   # steigt -> Stop rauf
        kerzen.append(kerze(6, 108, 108.5, 104, 105))     # fällt -> Stop bleibt
        ind = berechne(kerzen, P_KLEIN)
        k = mit_position(stop=90.0)
        preise = {}
        for i in range(5):
            # Aufwärmen ohne Stop-Treffer (Tief 99 > 90)
            verarbeite_kerze(k, "BTC", kerzen, ind, i, P_KLEIN, False, preise)
        verarbeite_kerze(k, "BTC", kerzen, ind, 5, P_KLEIN, False, preise)
        s1 = k.positionen["BTC"].stop
        self.assertAlmostEqual(s1, 110 - 3.0 * ind.atr[5])
        self.assertGreater(s1, 90.0)
        # Kandidat bei Kerze 6 liegt tiefer als s1 -> Test ist nicht trivial
        self.assertLess(110 - 3.0 * ind.atr[6], s1)
        verarbeite_kerze(k, "BTC", kerzen, ind, 6, P_KLEIN, False, preise)
        self.assertIn("BTC", k.positionen)
        self.assertEqual(k.positionen["BTC"].stop, s1)
        self.assertEqual(k.positionen["BTC"].hoechster_schluss, 110)

    def test_bremse_verhindert_nur_kauf(self):
        k = neues_konto()
        ereignisse = lauf(k, steigende_reihe(8), P_KLEIN, 7, bremse=True)
        self.assertEqual(k.vorgemerkt, {})
        self.assertEqual(k.positionen, {})
        self.assertEqual(ereignisse, [])
        k2 = mit_position(stop=95.0)
        lauf(k2, [kerze(0, 100, 101, 94, 98)], P_KLEIN, 0, bremse=True)
        self.assertEqual(len(k2.trades), 1)
        self.assertEqual(k2.trades[0].grund_verkauf, "Verlust-Limit erreicht")

    def test_stop_in_der_einstiegskerze(self):
        k = neues_konto()
        k.vorgemerkt["BTC"] = {"art": "kauf", "grund": "test", "stop_abstand": 5.0}
        kerzen = [kerze(0, 100, 101, 90, 92)]
        lauf(k, kerzen, P_KLEIN, 0)
        self.assertEqual(len(k.trades), 1)
        self.assertAlmostEqual(k.trades[0].kauf_preis, 100 * 1.0005)
        self.assertAlmostEqual(k.trades[0].verkauf_preis, (100 * 1.0005 - 5.0) * 0.9995)

    def test_trend_bruch_verkauft_zur_naechsten_eroeffnung(self):
        kerzen = [kerze(i, 100, 101, 99, 100) for i in range(5)]
        kerzen.append(kerze(5, 99, 99.5, 97, 98))   # Schluss 98 < 3-Kerzen-Tief 99
        kerzen.append(kerze(6, 97, 98, 96.5, 97.5))
        k = mit_position(stop=50.0)
        ind = berechne(kerzen, P_KLEIN)
        preise = {}
        for i in range(6):
            verarbeite_kerze(k, "BTC", kerzen, ind, i, P_KLEIN, False, preise)
        self.assertIn("BTC", k.positionen)
        self.assertEqual(k.vorgemerkt["BTC"]["art"], "verkauf")
        verarbeite_kerze(k, "BTC", kerzen, ind, 6, P_KLEIN, False, preise)
        self.assertNotIn("BTC", k.positionen)
        self.assertAlmostEqual(k.trades[0].verkauf_preis, 97 * 0.9995)
        self.assertEqual(k.trades[0].verkauf_zeit, kerzen[6].zeit)
        self.assertEqual(k.trades[0].grund_verkauf,
                         "Trend gebrochen: Schluss unter dem 3-Kerzen-Tief")

    def test_unmoeglicher_kauf_verwirft_vormerkung(self):
        k = neues_konto()
        k.bargeld = 0.0
        k.vorgemerkt["BTC"] = {"art": "kauf", "grund": "test", "stop_abstand": 5.0}
        ereignisse = lauf(k, [kerze(0, 100, 101, 99, 100)], P_KLEIN, 0)
        self.assertEqual(k.positionen, {})
        self.assertNotIn("BTC", k.vorgemerkt)
        self.assertTrue(any("nicht" in e for e in ereignisse))

    def test_verkauf_ohne_position_wird_verworfen(self):
        k = neues_konto()
        k.vorgemerkt["BTC"] = {"art": "verkauf", "grund": "x", "stop_abstand": 0.0}
        lauf(k, [kerze(0, 100, 101, 99, 100)], P_KLEIN, 0)
        self.assertEqual(k.vorgemerkt, {})
        self.assertEqual(k.trades, [])

    def test_kein_blick_in_die_zukunft(self):
        # Verrauschte, schwankende Reihe (fester Zufalls-Startwert)
        r = random.Random(7)
        a, s = [], 100.0
        for i in range(140):
            o = s + r.uniform(-2, 2)
            s = o + 2.4 * math.sin(i / 6) + r.uniform(-3, 3)
            a.append(kerze(i, o, max(o, s) + r.uniform(0, 2), min(o, s) - r.uniform(0, 2), s))
        # Zwei Regel-Sätze: einer endet per Trendbruch, einer per Verlust-Limit
        saetze = [Parameter(n_trend=10, n_ein=5, n_aus=3, k_stop=2.0, k_trail=3.0, n_atr=5),
                  Parameter(n_trend=10, n_ein=5, n_aus=8, k_stop=1.5, k_trail=2.0, n_atr=5)]
        gruende = set()
        for p in saetze:
            with self.subTest(p=p):
                gruende |= self._pruefe_ohne_zukunft(a, p)
        self.assertIn("Verlust-Limit erreicht", gruende)
        self.assertIn("Trend gebrochen: Schluss unter dem 3-Kerzen-Tief", gruende)

    def _pruefe_ohne_zukunft(self, a, p):
        def schnappschuesse(kerzen, bis):
            k = neues_konto()
            ind = berechne(kerzen, p)  # Indikatoren je Liste neu berechnet
            preise = {}
            bilder = []
            for i in range(bis + 1):
                ev = verarbeite_kerze(k, "BTC", kerzen, ind, i, p, False, preise)
                bilder.append((ev, copy.deepcopy(k.trades), copy.deepcopy(k.vorgemerkt),
                               copy.deepcopy(k.positionen), k.bargeld, k.pleite))
            return bilder

        bild_a = schnappschuesse(a, len(a) - 1)
        trades = bild_a[-1][1]
        self.assertGreaterEqual(len(trades), 3, "Testreihe muss handeln")
        # Für jedes t: B = A, aber alle Kerzen nach t drastisch verändert
        # (Absturz bzw. Explosion, wilde Spannen). Bis einschließlich t muss
        # alles gleich bleiben – sonst hat die Logik in die Zukunft geschaut.
        varianten = [(0.2, 3.0, 0.1), (5.0, 8.0, 4.0)]
        for t in range(len(a) - 1):
            for f_kurs, f_hoch, f_tief in varianten:
                b = a[:t + 1] + [
                    kerze(i, c.eroeffnung * f_kurs, c.hoch * f_hoch,
                          c.tief * f_tief, c.schluss * f_kurs)
                    for i, c in enumerate(a[t + 1:], start=t + 1)
                ]
                bild_b = schnappschuesse(b, t)
                for i in range(t + 1):
                    self.assertEqual(bild_a[i], bild_b[i],
                                     f"Abweichung bei Kerze {i} (Zukunft ab {t + 1} geändert)")
        # Gegenprobe: die Änderung wirkt sich nach t wirklich aus
        b = a[:81] + [kerze(i, c.eroeffnung * 0.2, c.hoch * 3, c.tief * 0.1, c.schluss * 0.2)
                      for i, c in enumerate(a[81:], start=81)]
        self.assertNotEqual(bild_a[-1], schnappschuesse(b, len(b) - 1)[-1])
        return {tr.grund_verkauf for tr in trades}

    def test_pleite_konto_handelt_nicht(self):
        k = neues_konto()
        k.pleite = True
        k.vorgemerkt["BTC"] = {"art": "kauf", "grund": "test", "stop_abstand": 5.0}
        vorher = copy.deepcopy(k)
        ereignisse = lauf(k, steigende_reihe(8), P_KLEIN, 7)
        self.assertEqual(ereignisse, [])
        self.assertEqual(k, vorher)

    def test_finanzierung_einmal_pro_kerze_bei_zwei_coins(self):
        k = Konto(name="t", stufe=MUTIG_HEBEL, bargeld=1000.0)
        k.positionen["BTC"] = Position("BTC", 100.0, 100.0, 0, 50.0, 100.0, 6000.0, "t")
        k.positionen["ETH"] = Position("ETH", 50.0, 100.0, 0, 50.0, 100.0, 3000.0, "t")
        btc = [kerze(0, 100, 101, 99, 100)]
        eth = [kerze(0, 100, 101, 99, 100)]
        preise = {"BTC": 100.0, "ETH": 100.0}
        vorher = k.bargeld
        verarbeite_kerze(k, "BTC", btc, berechne(btc, P_KLEIN), 0, P_KLEIN, False, preise)
        verarbeite_kerze(k, "ETH", eth, berechne(eth, P_KLEIN), 0, P_KLEIN, False, preise)
        self.assertAlmostEqual(vorher - k.bargeld, 0.0003 * 4 / 24 * (6000.0 + 3000.0))

    def test_pleite_in_der_kerze_stoppt_den_rest(self):
        # ETH (vom Aufrufer bepreist) reißt das Konto ins Minus, während BTC
        # gerade ausbricht – Schritt 6 darf keinen Kauf mehr vormerken.
        k = Konto(name="t", stufe=MUTIG_HEBEL, bargeld=0.0)
        k.positionen["ETH"] = Position("ETH", 180.0, 100.0, 0, 1.0, 100.0, 8000.0, "t")
        k.vorgemerkt["ETH"] = {"art": "verkauf", "grund": "x", "stop_abstand": 0.0}
        kerzen = steigende_reihe(8)
        ind = berechne(kerzen, P_KLEIN)
        self.assertIsNotNone(ind.hoch_ein[4])
        preise = {"ETH": 40.0}
        ereignisse = verarbeite_kerze(k, "BTC", kerzen, ind, 4, P_KLEIN, False, preise)
        self.assertTrue(k.pleite)
        self.assertTrue(any("pleite" in e for e in ereignisse))
        self.assertFalse(any("vorgemerkt" in e for e in ereignisse))
        self.assertEqual(k.vorgemerkt, {})
        self.assertEqual(k.positionen, {})
        self.assertEqual(k.trades[-1].grund_verkauf, "Pleite: Zwangsverkauf")

    def test_beschreibung(self):
        text = Parameter(n_trend=200, n_ein=40, n_aus=20, k_stop=2.0).beschreibung()
        for teil in ("200", "40", "20", "2"):
            self.assertIn(teil, text)


if __name__ == "__main__":
    unittest.main()
