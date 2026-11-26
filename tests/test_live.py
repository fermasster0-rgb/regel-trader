import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from regeltrader import live, zustand
from regeltrader.kerzen import INTERVALL_MS
from regeltrader.konto import MUTIG_HEBEL, RUHIG, Konto, Position, Trade
from regeltrader.live import urteil

I = INTERVALL_MS
T0 = 1_780_000_000_000 // I * I  # Eröffnung der gerade laufenden Kerze beim ersten Lauf
JETZT0 = T0 + 10 * 60 * 1000     # 10 Minuten nach Kerzenbeginn

RUECKBLICK = {
    "parameter": {"n_trend": 200, "n_ein": 40, "n_aus": 20, "k_stop": 3.0,
                  "k_trail": 3.0, "n_atr": 14, "beschreibung": "Testregeln"},
    "mutig_stufe": "Mutig + Hebel",
}


def preis(coin, j):
    basis = 100.0 + j * 0.1 + 5 * math.sin(j / 7)
    return basis if coin == "BTC" else basis / 2


def fake_hole_json(jetzt_ms, fehlt=None):
    """Binance-Datenspiegel: Kerzen ab startTime bis einschließlich der laufenden Kerze.
    fehlt: Menge von (coin, zeit), die die Börse nicht liefert."""
    fehlt = fehlt or set()

    def hole(url):
        if "kraken" in url:
            raise OSError("Kraken aus")
        q = parse_qs(urlparse(url).query)
        coin = "BTC" if q["symbol"][0] == "BTCUSDT" else "ETH"
        start = int(q["startTime"][0])
        j0 = -((T0 - start) // I)
        zeilen = []
        j = j0
        while T0 + j * I <= jetzt_ms and len(zeilen) < 1000:
            z = T0 + j * I
            if (coin, z) not in fehlt and z >= start:
                s = preis(coin, j)
                o = preis(coin, j - 1)
                zeilen.append([z, str(o), str(max(o, s) + 0.2), str(min(o, s) - 0.2), str(s)])
            j += 1
        return zeilen
    return hole


def alles_kaputt(url):
    raise OSError("keine Verbindung")


def kein_feed(url):
    raise OSError("Feed aus")


class LiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.wurzel = Path(self._tmp.name)
        self.ordner = self.wurzel / "daten"
        self.ordner.mkdir()
        (self.ordner / "rueckblick.json").write_text(json.dumps(RUECKBLICK), encoding="utf-8")
        self.termine([])

    def tearDown(self):
        self._tmp.cleanup()

    def termine(self, liste):
        (self.wurzel / "termine.json").write_text(json.dumps(liste), encoding="utf-8")

    def lauf(self, jetzt, hole_json=None):
        live.lauf(self.ordner, jetzt, hole_json=hole_json or fake_hole_json(jetzt),
                  hole_text=kein_feed)

    def lies(self, name):
        return json.loads((self.ordner / name).read_text(encoding="utf-8"))

    def roh(self, name):
        return (self.ordner / name).read_bytes()

    def test_erster_lauf_legt_drei_konten_an(self):
        self.lauf(JETZT0)
        z = self.lies("zustand.json")
        self.assertEqual(z["start_ms"], JETZT0)
        self.assertEqual(z["tag"], 1)
        self.assertEqual(set(z["konten"]), {"ohne_bremse", "mit_bremse", "mutig"})
        for schluessel, stufe in (("ohne_bremse", "Ruhig"), ("mit_bremse", "Ruhig"),
                                  ("mutig", "Mutig + Hebel")):
            k = z["konten"][schluessel]
            self.assertEqual(k["stufe"], stufe)
            self.assertEqual(k["bargeld"], 10000.0)
            self.assertEqual(k["wert"], 10000.0)
            self.assertEqual(k["positionen"], {})
            self.assertEqual(k["abgeschlossene_trades"], 0)
            self.assertEqual(k["urteil"], "laeuft")
        # Ohne Handel: letzte Kerze = jüngste abgeschlossene, Preise = deren Schluss.
        self.assertEqual(z["letzte_kerze"], {"BTC": T0 - I, "ETH": T0 - I})
        self.assertAlmostEqual(z["preise"]["BTC"], preis("BTC", -1))
        b = z["btc_halten"]
        start = preis("BTC", -1)
        self.assertAlmostEqual(b["menge"], 10000 / (start * 1.0005 * 1.001))
        # nach allen Gebühren: Kauf- UND Verkaufskosten sind abgezogen
        self.assertEqual(b["wert"], round(b["menge"] * start * 0.9995 * 0.999, 2))
        self.assertLess(b["wert"], 9971)
        self.assertGreater(b["wert"], 9969)
        self.assertEqual(z["abgeschlossene_tage"], 0)
        self.assertEqual(z["parameter"]["n_trend"], 200)
        self.assertFalse(z["bremse"]["aktiv"])
        self.assertFalse(z["bremse"]["nachrichten_ok"])
        verlauf = self.lies("verlauf.json")
        self.assertEqual(len(verlauf), 1)
        self.assertEqual(verlauf[0]["zeit"], JETZT0)
        self.assertEqual(verlauf[0]["mutig"], 10000.0)
        self.assertEqual(verlauf[0]["btc_halten"], round(b["wert"], 2))
        self.assertEqual(self.lies("trades.json"), [])
        s = self.lies("status.json")
        self.assertTrue(s["ok"])
        self.assertIsNone(s["fehler"])
        self.assertEqual(s["quelle"], "binance")
        self.assertEqual(s["letzter_lauf"], live.iso(JETZT0))
        self.assertEqual(s["naechster_lauf_ca"], live.iso(JETZT0 + 4 * 3_600_000))

    def test_zweiter_lauf_ohne_neue_kerze_aendert_nichts(self):
        self.lauf(JETZT0 + 3 * I)  # erster Lauf
        self.lauf(JETZT0 + 4 * I)  # eine Kerze verarbeitet
        z1, t1 = self.lies("zustand.json"), self.roh("trades.json")
        n1 = len(self.lies("verlauf.json"))
        self.lauf(JETZT0 + 4 * I)
        self.lauf(JETZT0 + 4 * I + 60_000)
        z2 = self.lies("zustand.json")
        self.assertEqual(self.roh("trades.json"), t1)
        self.assertEqual(z2["konten"], z1["konten"])
        self.assertEqual(z2["letzte_kerze"], z1["letzte_kerze"])
        self.assertEqual(z2["btc_halten"], z1["btc_halten"])
        self.assertLessEqual(len(self.lies("verlauf.json")), n1 + 2)

    def _aufzeichnen(self):
        aufrufe = []
        echt = live.verarbeite_kerze

        def wrapper(konto, coin, kerzen, ind, i, p, bremse_aktiv, preise):
            aufrufe.append((kerzen[i].zeit, coin, konto.name, bremse_aktiv))
            return echt(konto, coin, kerzen, ind, i, p, bremse_aktiv, preise)
        return aufrufe, mock.patch.object(live, "verarbeite_kerze", side_effect=wrapper)

    def test_verspaeteter_lauf_holt_nach(self):
        self.lauf(JETZT0)
        aufrufe, patch = self._aufzeichnen()
        with patch:
            self.lauf(JETZT0 + 3 * I)
        neu = [T0, T0 + I, T0 + 2 * I]
        self.assertEqual(len(aufrufe), 3 * 2 * 3)
        self.assertEqual(sorted({a[0] for a in aufrufe}), neu)
        self.assertEqual([a[0] for a in aufrufe], sorted(a[0] for a in aufrufe))
        for z in neu:
            coins = [a[1] for a in aufrufe if a[0] == z]
            self.assertEqual(coins, ["BTC"] * 3 + ["ETH"] * 3)
        z = self.lies("zustand.json")
        self.assertEqual(z["letzte_kerze"], {"BTC": T0 + 2 * I, "ETH": T0 + 2 * I})
        self.assertAlmostEqual(z["preise"]["ETH"], preis("ETH", 2))
        self.assertEqual(z["tag"], 2 if 3 * I >= 86_400_000 else 1)
        self.assertEqual(len(self.lies("verlauf.json")), 2)

    def test_nachholen_gleich_wie_puenktlich(self):
        """90 Kerzen in einem Lauf nachgeholt == 90 pünktliche Läufe (mit echten Trades)."""
        rb = json.loads(json.dumps(RUECKBLICK))
        rb["parameter"].update(n_trend=20, n_ein=5, n_aus=3, k_stop=2.0)
        (self.ordner / "rueckblick.json").write_text(json.dumps(rb), encoding="utf-8")
        nachgeholt = self.wurzel / "nachgeholt"
        nachgeholt.mkdir()
        (nachgeholt / "rueckblick.json").write_text(json.dumps(rb), encoding="utf-8")
        n = 90
        self.lauf(JETZT0)
        for schritt in range(1, n + 1):
            self.lauf(JETZT0 + schritt * I)
        ende = JETZT0 + n * I
        live.lauf(nachgeholt, JETZT0, hole_json=fake_hole_json(JETZT0), hole_text=kein_feed)
        live.lauf(nachgeholt, ende, hole_json=fake_hole_json(ende), hole_text=kein_feed)
        z = self.lies("zustand.json")
        z_n = json.loads((nachgeholt / "zustand.json").read_text(encoding="utf-8"))
        self.assertEqual(z_n["konten"], z["konten"])
        self.assertEqual(z_n["ereignisse"], z["ereignisse"])
        self.assertEqual((nachgeholt / "trades.json").read_bytes(), self.roh("trades.json"))
        trades = self.lies("trades.json")
        self.assertGreater(len(trades), 0)
        self.assertEqual({t["konto"] for t in trades}, {"ohne_bremse", "mit_bremse", "mutig"})
        self.assertEqual(len(self.lies("verlauf.json")), n + 1)
        self.assertEqual(len(z["ereignisse"]), 50)

    def test_fehlende_kerze_eines_coins(self):
        self.lauf(JETZT0)
        aufrufe, patch = self._aufzeichnen()
        jetzt = JETZT0 + 2 * I
        with patch:
            self.lauf(jetzt, fake_hole_json(jetzt, fehlt={("ETH", T0)}))
        self.assertEqual([a[1] for a in aufrufe if a[0] == T0], ["BTC"] * 3)
        z = self.lies("zustand.json")
        self.assertEqual(z["letzte_kerze"], {"BTC": T0 + I, "ETH": T0 + I})

    def test_bremse_nur_fuer_mit_bremse(self):
        self.lauf(JETZT0)
        jetzt = JETZT0 + I
        self.termine([{"zeit": live.iso(jetzt + 3_600_000), "name": "US-Zinsentscheid (FOMC)"}])
        aufrufe, patch = self._aufzeichnen()
        with patch:
            self.lauf(jetzt)
        self.assertEqual(len(aufrufe), 6)
        for _, _, name, bremse_aktiv in aufrufe:
            self.assertEqual(bremse_aktiv, name == "Mit Bremse")
        z = self.lies("zustand.json")
        self.assertTrue(z["bremse"]["aktiv"])
        self.assertIn("FOMC", z["bremse"]["grund"])

    def test_kursausfall_schreibt_status(self):
        self.lauf(JETZT0)
        vorher = {n: self.roh(n) for n in ("zustand.json", "verlauf.json", "trades.json")}
        live.lauf(self.ordner, JETZT0 + I, hole_json=alles_kaputt, hole_text=kein_feed)
        for n, inhalt in vorher.items():
            self.assertEqual(self.roh(n), inhalt, n)
        s = self.lies("status.json")
        self.assertFalse(s["ok"])
        self.assertIn("Kurse", s["fehler"])
        self.assertNotIn("\n", s["fehler"])
        self.assertIsNone(s["quelle"])
        self.assertEqual(s["letzter_lauf"], live.iso(JETZT0 + I))

    def test_zu_wenige_kerzen_handelt_nicht(self):
        """Binance aus, Kraken liefert nur 100 Kerzen (< 200 + 50 für die EMA 200)."""
        self.lauf(JETZT0)
        vorher = {n: self.roh(n) for n in ("zustand.json", "verlauf.json", "trades.json")}
        jetzt = JETZT0 + I

        def hole(url):
            if "binance" in url:
                raise OSError("Binance aus")
            sek = [(T0 + j * I) // 1000 for j in range(-99, 1)]
            return {"error": [], "result": {"XXBTZUSD": [[t, "1", "2", "0.5", "1.5", "1", "1", 1]
                                                          for t in sek], "last": 0}}

        live.lauf(self.ordner, jetzt, hole_json=hole, hole_text=kein_feed)
        for n, inhalt in vorher.items():
            self.assertEqual(self.roh(n), inhalt, n)
        s = self.lies("status.json")
        self.assertFalse(s["ok"])
        self.assertIn("Kerzen", s["fehler"])
        self.assertIn("250", s["fehler"])

    def test_zu_wenige_kerzen_beim_ersten_lauf_legt_nichts_an(self):
        rb = json.loads(json.dumps(RUECKBLICK))
        rb["parameter"]["n_trend"] = 990  # braucht 1040 Kerzen, geholt werden höchstens 1000
        (self.ordner / "rueckblick.json").write_text(json.dumps(rb), encoding="utf-8")
        self.lauf(JETZT0)
        self.assertFalse((self.ordner / "zustand.json").exists())
        s = self.lies("status.json")
        self.assertFalse(s["ok"])
        self.assertIn("1040", s["fehler"])

    def test_kursausfall_beim_ersten_lauf_legt_nichts_an(self):
        live.lauf(self.ordner, JETZT0, hole_json=alles_kaputt, hole_text=kein_feed)
        self.assertFalse((self.ordner / "zustand.json").exists())
        self.assertFalse(self.lies("status.json")["ok"])

    def test_kaputter_zustand_schreibt_status(self):
        (self.ordner / "zustand.json").write_text("{kaputt", encoding="utf-8")
        self.lauf(JETZT0)
        self.assertEqual((self.ordner / "zustand.json").read_text(encoding="utf-8"), "{kaputt")
        s = self.lies("status.json")
        self.assertFalse(s["ok"])
        self.assertTrue(s["fehler"])

    def test_wert_offener_positionen_nach_gebuehren(self):
        """Kontostand in zustand.json und verlauf.json zieht die Verkaufskosten offener Positionen ab."""
        rb = json.loads(json.dumps(RUECKBLICK))
        rb["parameter"].update(n_trend=20, n_ein=5, n_aus=3, k_stop=2.0)
        (self.ordner / "rueckblick.json").write_text(json.dumps(rb), encoding="utf-8")
        self.lauf(JETZT0)
        offen = None
        for schritt in range(1, 91):
            self.lauf(JETZT0 + schritt * I)
            z = self.lies("zustand.json")
            offen = next(((s, k) for s, k in z["konten"].items() if k["positionen"]), None)
            if offen:
                break
        self.assertIsNotNone(offen, "in 90 Kerzen keine offene Position")
        s, k = offen
        preise = z["preise"]
        brutto = k["bargeld"] + sum(p["menge"] * preise[c] - p["geliehen"]
                                    for c, p in k["positionen"].items())
        netto = k["bargeld"] + sum(p["menge"] * preise[c] * 0.9995 * 0.999 - p["geliehen"]
                                   for c, p in k["positionen"].items())
        self.assertEqual(k["wert"], round(netto, 2))
        self.assertLess(k["wert"], round(brutto, 2))
        self.assertEqual(self.lies("verlauf.json")[-1][s], k["wert"])

    def test_urteil_erst_nach_56_vollen_tagen(self):
        self.lauf(JETZT0)
        fast = JETZT0 + int(55.9 * live.TAG_MS)
        self.lauf(fast)
        z = self.lies("zustand.json")
        self.assertEqual(z["abgeschlossene_tage"], 55)
        self.assertEqual(z["tag"], 56)
        for k in z["konten"].values():
            self.assertEqual(k["urteil"], "laeuft")
        self.lauf(JETZT0 + 56 * live.TAG_MS)
        z = self.lies("zustand.json")
        self.assertEqual(z["abgeschlossene_tage"], 56)
        self.assertEqual(z["tag"], 57)
        for k in z["konten"].values():
            self.assertIn(k["urteil"], live.ENDGUELTIG)

    def test_main_ruft_lauf_mit_daten(self):
        # main() druckt daten/status.json (für das Actions-Protokoll) – im Test stumm schalten
        with mock.patch.object(live, "lauf") as l,                 contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(live.main(), 0)
        ordner, jetzt = l.call_args[0]
        self.assertEqual(ordner, Path("daten"))
        self.assertIsInstance(jetzt, int)


class UrteilTests(unittest.TestCase):
    def test_urteil(self):
        self.assertEqual(urteil(10500, 7, 56), "bewiesen")
        self.assertEqual(urteil(9800, 7, 56), "nicht_bewiesen")
        self.assertEqual(urteil(12000, 3, 56), "zu_wenige_trades")
        self.assertEqual(urteil(12000, 9, 20), "laeuft")
        self.assertEqual(urteil(10000, 9, 56), "nicht_bewiesen")
        self.assertEqual(urteil(12000, 5, 56), "bewiesen")

    def test_urteil_zaehlt_volle_tage(self):
        # "56" heißt: 56 volle Tage seit dem Start sind vorbei
        self.assertEqual(urteil(10500, 7, 55), "laeuft")
        self.assertEqual(live.abgeschlossene_tage(0, int(55.9 * live.TAG_MS)), 55)
        self.assertEqual(live.abgeschlossene_tage(0, 56 * live.TAG_MS), 56)
        self.assertEqual(live.abgeschlossene_tage(5, 5), 0)

    def test_urteil_bleibt_nach_tag_56(self):
        self.assertEqual(live.konto_urteil("laeuft", 10500, 7, 56), "bewiesen")
        self.assertEqual(live.konto_urteil("bewiesen", 9000, 9, 70), "bewiesen")
        self.assertEqual(live.konto_urteil(None, 9000, 9, 70), "nicht_bewiesen")


class ZustandTests(unittest.TestCase):
    def test_konto_rundreise(self):
        k = Konto(name="Mutig", stufe=MUTIG_HEBEL, bargeld=-1234.5)
        k.positionen["ETH"] = Position("ETH", 1.5, 3000.25, 111, 2900.0, 3100.0, 400.0, "Ausbruch")
        k.trades.append(Trade("BTC", 1, 100.0, 2, 110.0, 0.5, 4.8, 0.096, "Ausbruch", "Trend"))
        k.vorgemerkt["BTC"] = {"art": "kauf", "grund": "Ausbruch", "stop_abstand": 12.5}
        d = json.loads(json.dumps(zustand.konto_als_dict(k)))
        self.assertEqual(d["stufe"], "Mutig + Hebel")
        self.assertEqual(zustand.konto_aus_dict(d), k)

    def test_unbekannte_stufe(self):
        with self.assertRaises(ValueError):
            zustand.stufe_aus_name("Wild")
        self.assertIs(zustand.stufe_aus_name("Ruhig"), RUHIG)

    def test_lade_ohne_datei_und_speichern(self):
        with tempfile.TemporaryDirectory() as tmp:
            ordner = Path(tmp) / "neu"
            self.assertIsNone(zustand.lade(ordner))
            zustand.speichere(ordner, {"start_ms": 5, "text": "Bremse äöü"})
            self.assertEqual(zustand.lade(ordner), {"start_ms": 5, "text": "Bremse äöü"})
            self.assertEqual([p.name for p in ordner.iterdir()], ["zustand.json"])

    def test_trades_liste_prozent_und_konto(self):
        a = Konto(name="Ohne Bremse", stufe=RUHIG)
        a.trades.append(Trade("BTC", 1, 100.0, 5, 110.0, 0.5, 4.8123, 0.12345, "K", "V"))
        b = Konto(name="Mutig", stufe=MUTIG_HEBEL)
        b.trades.append(Trade("ETH", 2, 50.0, 9, 45.0, 1.0, -5.2, -0.1049, "K2", "V2"))
        liste = live.trades_liste({"ohne_bremse": a, "mutig": b})
        self.assertEqual([t["konto"] for t in liste], ["mutig", "ohne_bremse"])
        self.assertEqual(liste[1]["ergebnis_pct"], 12.35)
        self.assertEqual(liste[1]["ergebnis_usd"], 4.81)
        self.assertEqual(liste[0]["ergebnis_pct"], -10.49)
        self.assertEqual(set(liste[0]), {"konto", "coin", "kauf_zeit", "kauf_preis", "verkauf_zeit",
                                         "verkauf_preis", "menge", "ergebnis_usd", "ergebnis_pct",
                                         "grund_kauf", "grund_verkauf"})


if __name__ == "__main__":
    unittest.main()
