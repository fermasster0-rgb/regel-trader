import json
import unittest
from datetime import datetime, timezone

from regeltrader import bremse
from regeltrader.bremse import BremsStatus, bremse_pruefen, lies_meldungen

H = 3_600_000


def ms(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def meldung(titel, zeit_ms):
    return {"titel": titel, "quelle": "Test", "zeit_ms": zeit_ms, "link": "http://x"}


JETZT = ms("2026-12-01T12:00:00Z")
SCHOCK = "Exchange hacked, $200M drained"


class BremseTests(unittest.TestCase):
    def test_schock_meldung_bremst_24h(self):
        z = JETZT - H
        s = bremse_pruefen(JETZT, [meldung(SCHOCK, z)], [], True, None)
        self.assertTrue(s.aktiv)
        self.assertEqual(s.bis_ms, z + 24 * H)
        self.assertIn(SCHOCK, s.grund)
        self.assertIn("Test", s.quelle)
        self.assertIn("http://x", s.quelle)

    def test_alte_meldung_bremst_nicht(self):
        s = bremse_pruefen(JETZT, [meldung(SCHOCK, JETZT - 7 * H)], [], True, None)
        self.assertFalse(s.aktiv)

    def test_wortgrenzen(self):
        s = bremse_pruefen(JETZT, [meldung("Bandwidth upgrade", JETZT - H)], [], True, None)
        self.assertFalse(s.aktiv)

    def _bremst(self, titel, text=""):
        m = meldung(titel, JETZT - H)
        if text:
            m["text"] = text
        return bremse_pruefen(JETZT, [m], [], True, None).aktiv

    def test_ereignis_formen_bremsen(self):
        treffer = [
            "Exchange XYZ hacked for $40M",
            "DeFi protocol exploited, funds lost",
            "Bridge drained overnight",
            "Major exchange halts withdrawals",
            "Lender suspends withdrawals amid turmoil",
            "Platform PAUSES   withdrawals",
            "Exchange freezes withdrawals",
            "Withdrawals halted at big exchange",
            "Withdrawals suspended after outage",
            "Withdrawals paused for 12 hours",
            "Withdrawals frozen for customers",
            "Crypto lender files for bankruptcy",
            "Crypto lender filed for bankruptcy",
            "Exchange is insolvent, CEO says",
            "Insolvency fears grow",
            "Stablecoin depegs",
            "USDX depegged after run",
            "Stablecoin briefly depeg",
            "Stablecoin loses its peg",
            "Stablecoin loses peg to dollar",
            "SEC sues major exchange",
            "Country bans crypto trading",
            "Government ban bitcoin mining",
            "Regulator bans stablecoins",
            "Exchange delists token",
            "Exchange delisted coin",
            "Exchange delisting several tokens",
            "Börse gehackt",
            "Krypto-Firma insolvent",
            "Insolvenz beantragt",
            "Börse ist pleite",
            "Land verbietet Krypto",
            "Land verbietet Bitcoin",
            "Bybit suffers $1.5B hack",
            "Exchange hit by $40 million exploit",
            "Protocol hit by an exploit",
            "$600M heist at bridge",
        ]
        for titel in treffer:
            with self.subTest(titel=titel):
                self.assertTrue(self._bremst(titel))

    def test_keine_fehlalarme(self):
        frei = [
            "South Korea to Lift Its ICO Ban",
            "Bandwidth upgrade for Ethereum",
            "ETHGlobal hackathon winners announced",
            "Looking back at the Binance Hack of 2019",
            "Mt. Gox hack anniversary: what we learned",
            "Exploit bounty program launched",
            "Bankrupt exchange repays creditors in full",
            "Lawsuit against exchange dismissed",
            "Bitcoin hits new high",
            "UK regulator plans tighter DeFi rules, citing $6.3B Binance hack: Report",
            "Coldcard Bitcoin Exploit, Revisited: How a Hidden Flaw Survived Years of Audits",
            "1Password hacker stole customer names",
        ]
        for titel in frei:
            with self.subTest(titel=titel):
                self.assertFalse(self._bremst(titel))

    def test_nur_titel_zaehlt(self):
        # Ein Treffer nur in der Beschreibung bremst nicht.
        self.assertFalse(self._bremst("Senate debates new Bill", "exchange hacked, withdrawals halted"))

    def test_termin_fenster(self):
        t = [{"zeit": "2026-12-10T13:30:00Z", "name": "US-Inflationszahlen (CPI)"}]
        self.assertTrue(bremse_pruefen(ms("2026-12-10T02:00:00Z"), [], t, True, None).aktiv)
        s = bremse_pruefen(ms("2026-12-10T18:00:00Z"), [], t, True, None)
        self.assertFalse(s.aktiv)
        s = bremse_pruefen(ms("2026-12-10T17:00:00Z"), [], t, True, None)
        self.assertTrue(s.aktiv)
        self.assertEqual(s.bis_ms, ms("2026-12-10T17:30:00Z"))

    def test_feeds_aus_keine_bremse(self):
        s = bremse_pruefen(JETZT, [], [], False, None)
        self.assertFalse(s.aktiv)
        self.assertFalse(s.nachrichten_ok)

    def test_vorherige_sperre_laeuft_weiter(self):
        v = BremsStatus(True, JETZT + 5 * H, "alt", "Q", True)
        s = bremse_pruefen(JETZT, [], [], True, v)
        self.assertTrue(s.aktiv)
        self.assertEqual(s.bis_ms, JETZT + 5 * H)
        abgelaufen = BremsStatus(True, JETZT - H, "alt", "Q", True)
        self.assertFalse(bremse_pruefen(JETZT, [], [], True, abgelaufen).aktiv)

    def test_laengste_sperre_gewinnt(self):
        v = BremsStatus(True, JETZT + 2 * H, "alt", "Q", True)
        s = bremse_pruefen(JETZT, [meldung(SCHOCK, JETZT - H)], [], True, v)
        self.assertEqual(s.bis_ms, JETZT - H + 24 * H)

    def test_dict_rundreise(self):
        s = BremsStatus(True, 5, "g", "q", True)
        self.assertEqual(BremsStatus.aus_dict(s.als_dict()), s)

    def test_lies_meldungen_rss_und_atom(self):
        rss = """<rss><channel><item><title>Bank insolvent</title>
        <link>http://a</link><pubDate>Tue, 01 Dec 2026 11:00:00 GMT</pubDate></item>
        <item><title>Ohne Datum</title></item></channel></rss>"""
        atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom Titel</title>
        <link href="http://b"/><updated>2026-12-01T10:00:00Z</updated></entry></feed>"""

        def hole(url):
            if "coindesk" in url:
                return rss
            if "decrypt" in url:
                return atom
            raise OSError("aus")

        m, ok = lies_meldungen(hole)
        self.assertTrue(ok)
        titel = {x["titel"]: x for x in m}
        self.assertEqual(titel["Bank insolvent"]["zeit_ms"], ms("2026-12-01T11:00:00Z"))
        self.assertEqual(titel["Atom Titel"]["link"], "http://b")
        self.assertNotIn("Ohne Datum", titel)

    def test_feed_ohne_meldungen_zaehlt_nicht_als_erreichbar(self):
        leer = "<rss><channel><title>leer</title></channel></rss>"
        nur_ohne_datum = "<rss><channel><item><title>Ohne Datum</title></item></channel></rss>"

        def hole(url):
            if "coindesk" in url:
                return leer
            if "decrypt" in url:
                return nur_ohne_datum
            if "theblock" in url:
                return "<html>Fehlerseite</html>"
            raise OSError("aus")

        self.assertEqual(lies_meldungen(hole), ([], False))

    def test_lies_meldungen_alle_feeds_aus(self):
        def hole(url):
            raise OSError("aus")
        self.assertEqual(lies_meldungen(hole), ([], False))

    def test_termine_json_gueltig(self):
        with open("termine.json", encoding="utf-8") as f:
            t = json.load(f)
        self.assertTrue(len(t) >= 5)
        for e in t:
            self.assertTrue(e["zeit"].endswith("Z"))
            self.assertTrue(e["quelle"].startswith("https://"))
            ms(e["zeit"])


if __name__ == "__main__":
    unittest.main()
