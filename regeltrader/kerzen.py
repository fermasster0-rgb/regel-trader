"""Kerzen (4-Stunden) holen: Binance-Datenspiegel, bei Fehler Kraken."""
import json
import urllib.request
from dataclasses import dataclass

INTERVALL_MS = 14_400_000
BINANCE_URL = (
    "https://data-api.binance.vision/api/v3/klines"
    "?symbol={paar}&interval=4h&startTime={start}&limit=1000"
)
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC?pair={paar}&interval=240"
BINANCE_PAARE = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
KRAKEN_PAARE = {"BTC": "XBTUSD", "ETH": "ETHUSD"}
# Liefert Binance weniger als die Hälfte der Kerzen im verlangten Zeitraum, gilt das als
# Ausfall und Kraken springt ein (Kraken selbst muss nur mindestens eine Kerze liefern).
MIN_ANTEIL_BINANCE = 0.5


class KursFehler(Exception):
    pass


@dataclass(frozen=True)
class Kerze:
    zeit: int  # Eröffnungszeit, ms UTC
    eroeffnung: float
    hoch: float
    tief: float
    schluss: float


def standard_hole_json(url):
    anfrage = urllib.request.Request(url, headers={"User-Agent": "regel-trader"})
    with urllib.request.urlopen(anfrage, timeout=20) as antwort:
        return json.loads(antwort.read().decode("utf-8"))


def _binance(coin, start_ms, jetzt_ms, hole_json):
    paar = BINANCE_PAARE[coin]
    kerzen = []
    start = start_ms
    while start + INTERVALL_MS <= jetzt_ms:
        zeilen = hole_json(BINANCE_URL.format(paar=paar, start=start))
        for z in zeilen:
            kerzen.append(Kerze(int(z[0]), float(z[1]), float(z[2]), float(z[3]), float(z[4])))
        if len(zeilen) < 1000:
            break
        neuer_start = int(zeilen[-1][0]) + INTERVALL_MS
        if neuer_start <= start:
            break
        start = neuer_start
    return kerzen


def _kraken(coin, hole_json):
    antwort = hole_json(KRAKEN_URL.format(paar=KRAKEN_PAARE[coin]))
    if antwort.get("error"):
        raise KursFehler(f"Kraken: {antwort['error']}")
    schluessel = next(k for k in antwort["result"] if k != "last")
    return [
        Kerze(int(z[0]) * 1000, float(z[1]), float(z[2]), float(z[3]), float(z[4]))
        for z in antwort["result"][schluessel]
    ]


def _bereinigen(kerzen, start_ms, jetzt_ms):
    einzigartig = {k.zeit: k for k in kerzen if k.zeit >= start_ms and k.zeit + INTERVALL_MS <= jetzt_ms}
    return [einzigartig[z] for z in sorted(einzigartig)]


def _binance_pruefen(kerzen, start_ms, jetzt_ms):
    """Leere oder viel zu kurze Binance-Antwort zählt als Fehler (dann Kraken)."""
    erwartet = max(0, (jetzt_ms - start_ms) // INTERVALL_MS)
    if not kerzen or len(kerzen) < erwartet * MIN_ANTEIL_BINANCE:
        raise KursFehler(f"nur {len(kerzen)} von etwa {erwartet} Kerzen geliefert")
    return kerzen


def hole_kerzen(coin, start_ms, jetzt_ms, hole_json=standard_hole_json):
    """Nur abgeschlossene Kerzen, aufsteigend, ohne Duplikate, plus Quelle."""
    try:
        kerzen = _bereinigen(_binance(coin, start_ms, jetzt_ms, hole_json), start_ms, jetzt_ms)
        return _binance_pruefen(kerzen, start_ms, jetzt_ms), "binance"
    except Exception as fehler_b:
        try:
            kerzen = _bereinigen(_kraken(coin, hole_json), start_ms, jetzt_ms)
            if not kerzen:
                raise KursFehler("keine Kerzen geliefert")
            return kerzen, "kraken"
        except Exception as fehler_k:
            raise KursFehler(f"Binance: {fehler_b}; Kraken: {fehler_k}") from fehler_k
