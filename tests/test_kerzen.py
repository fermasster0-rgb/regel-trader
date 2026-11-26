import unittest
from urllib.parse import parse_qs, urlparse

from regeltrader.kerzen import INTERVALL_MS, Kerze, KursFehler, hole_kerzen

START = 1_700_000_000_000 - (1_700_000_000_000 % INTERVALL_MS)


def binance_zeile(zeit):
    return [zeit, "1.0", "2.0", "0.5", "1.5", "10", zeit + INTERVALL_MS - 1, "0", 0, "0", "0", "0"]


class TestKerzen(unittest.TestCase):
    def test_laufende_kerze_wird_weggelassen(self):
        jetzt = START + 3 * INTERVALL_MS
        zeiten = [START, START + INTERVALL_MS, jetzt - 3_600_000]

        def fake(url):
            return [binance_zeile(z) for z in zeiten]

        kerzen, quelle = hole_kerzen("BTC", START, jetzt, hole_json=fake)
        self.assertEqual(quelle, "binance")
        self.assertEqual([k.zeit for k in kerzen], zeiten[:2])
        self.assertEqual(kerzen[0], Kerze(START, 1.0, 2.0, 0.5, 1.5))

    def test_blaettert_bis_jetzt(self):
        jetzt = START + 1006 * INTERVALL_MS
        aufrufe = []
        urls = []

        def fake(url):
            urls.append(url)
            q = parse_qs(urlparse(url).query)
            aufrufe.append(int(q["startTime"][0]))
            if len(aufrufe) == 1:
                return [binance_zeile(START + i * INTERVALL_MS) for i in range(1000)]
            return [binance_zeile(START + (1000 + i) * INTERVALL_MS) for i in range(5)]

        kerzen, quelle = hole_kerzen("ETH", START, jetzt, hole_json=fake)
        self.assertEqual(len(kerzen), 1005)
        self.assertEqual(aufrufe[1], START + 999 * INTERVALL_MS + INTERVALL_MS)
        self.assertEqual(len(aufrufe), 2)
        self.assertIn("symbol=ETHUSDT", urls[0])

    def test_kraken_fallback(self):
        jetzt = START + 5 * INTERVALL_MS
        sek = START // 1000
        zeilen = [[sek + i * 14400, "1", "2", "0.5", "1.5", "1.2", "10", 3] for i in range(3)]
        urls = []

        def fake(url):
            urls.append(url)
            if "binance" in url:
                raise OSError("blockiert")
            return {"error": [], "result": {"XXBTZUSD": zeilen, "last": sek}}

        kerzen, quelle = hole_kerzen("BTC", START, jetzt, hole_json=fake)
        self.assertEqual(quelle, "kraken")
        self.assertIn("pair=XBTUSD", urls[-1])
        self.assertNotIn("since", urls[-1])
        self.assertEqual([k.zeit for k in kerzen], [START + i * INTERVALL_MS for i in range(3)])
        self.assertEqual(kerzen[0].schluss, 1.5)

    def test_kraken_neueste_abgeschlossene_kerze_ohne_laufende(self):
        # Kraken liefert die neuesten Kerzen; start liegt weit zurueck, die letzte laeuft noch.
        jetzt = START + 1000 * INTERVALL_MS
        zeiten = [START + (997 + i) * INTERVALL_MS for i in range(4)]  # 997, 998, 999, 1000(laufend)
        zeilen = [[z // 1000, "1", "2", "0.5", "1.5", "1.2", "10", 3] for z in zeiten]
        urls = []

        def fake(url):
            urls.append(url)
            if "binance" in url:
                raise OSError("blockiert")
            return {"error": [], "result": {"XXBTZUSD": zeilen, "last": 0}}

        kerzen, quelle = hole_kerzen("BTC", START, jetzt, hole_json=fake)
        self.assertEqual(quelle, "kraken")
        self.assertNotIn("since", urls[-1])
        self.assertEqual(kerzen[-1].zeit, START + 999 * INTERVALL_MS)
        self.assertEqual(len(kerzen), 3)

    def test_blaettern_bricht_ab_wenn_start_nicht_waechst(self):
        jetzt = START + 5000 * INTERVALL_MS
        aufrufe = []

        def fake(url):
            aufrufe.append(url)
            return [binance_zeile(START - INTERVALL_MS * 2 + i) for i in range(1000)]

        # Alle gelieferten Kerzen liegen vor START -> nichts Brauchbares -> Kraken (hier kaputt)
        with self.assertRaises(KursFehler):
            hole_kerzen("BTC", START, jetzt, hole_json=fake)
        self.assertEqual(len([u for u in aufrufe if "binance" in u]), 1)

    def _kraken_zeilen(self, jetzt, n):
        return [[(jetzt - (n - i) * INTERVALL_MS) // 1000, "1", "2", "0.5", "1.5", "1.2", "10", 3]
                for i in range(n)]

    def test_binance_leer_nimmt_kraken(self):
        jetzt = START + 500 * INTERVALL_MS

        def fake(url):
            if "binance" in url:
                return []
            return {"error": [], "result": {"XXBTZUSD": self._kraken_zeilen(jetzt, 300), "last": 0}}

        kerzen, quelle = hole_kerzen("BTC", START, jetzt, hole_json=fake)
        self.assertEqual(quelle, "kraken")
        self.assertEqual(len(kerzen), 300)

    def test_binance_viel_zu_kurz_nimmt_kraken(self):
        jetzt = START + 1000 * INTERVALL_MS

        def fake(url):
            if "binance" in url:  # nur die letzten 10 von 1000 Kerzen
                return [binance_zeile(START + (990 + i) * INTERVALL_MS) for i in range(10)]
            return {"error": [], "result": {"XXBTZUSD": self._kraken_zeilen(jetzt, 720), "last": 0}}

        kerzen, quelle = hole_kerzen("BTC", START, jetzt, hole_json=fake)
        self.assertEqual(quelle, "kraken")
        self.assertEqual(len(kerzen), 720)

    def test_binance_zu_kurz_und_kraken_aus_wirft_kursfehler(self):
        def fake(url):
            if "binance" in url:
                return []
            raise OSError("aus")

        with self.assertRaises(KursFehler) as ctx:
            hole_kerzen("BTC", START, START + 100 * INTERVALL_MS, hole_json=fake)
        self.assertIn("Binance", str(ctx.exception))

    def test_kraken_leer_wirft_kursfehler(self):
        def fake(url):
            if "binance" in url:
                raise OSError("blockiert")
            return {"error": [], "result": {"XXBTZUSD": [], "last": 0}}

        with self.assertRaises(KursFehler):
            hole_kerzen("BTC", START, START + 100 * INTERVALL_MS, hole_json=fake)

    def test_beide_aus_wirft_kursfehler(self):
        def fake(url):
            raise OSError("aus")

        with self.assertRaises(KursFehler):
            hole_kerzen("BTC", START, START + INTERVALL_MS * 3, hole_json=fake)


if __name__ == "__main__":
    unittest.main()
