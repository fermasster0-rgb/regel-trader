"""Gemeinsame Kerzen-Logik für Rückblick (Backtest) und Live-Betrieb.

verarbeite_kerze liest nur Kerzen und Indikatoren bis Index i. Entscheidungen
fallen am Schluss einer Kerze und werden zum Eröffnungskurs der nächsten
Kerze ausgeführt (Vormerkung im Konto).
"""
from .konto import FINANZIERUNG_TAG, SCHLUPF, kaufen, pruefe_pleite, verkaufen

KERZEN_STUNDEN = 4

GRUND_STOP = "Verlust-Limit erreicht"


def _usd(x):
    """64210.4 -> '64.210 $', 12.345 -> '12,35 $' (deutsche Schreibweise)."""
    text = f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".") + " $"


def _verkauf_satz(trade):
    return f"{trade.coin} verkauft zu {_usd(trade.verkauf_preis)} – {trade.grund_verkauf}"


def verarbeite_kerze(konto, coin, kerzen, ind, i, p, bremse_aktiv, preise):
    """Verarbeitet Kerze i für einen Coin und gibt Ereignis-Sätze zurück.

    `preise` kommt vom Aufrufer (letzter Kurs je Coin) und wird hier für
    `coin` auf den jeweils gültigen Kurs dieser Kerze gesetzt.
    """
    ereignisse = []
    # 1. Pleite-Konto handelt nicht mehr.
    if konto.pleite:
        return ereignisse

    k = kerzen[i]

    # 2. Vorgemerkte Order zum Eröffnungskurs ausführen.
    preise[coin] = k.eroeffnung
    order = konto.vorgemerkt.pop(coin, None)
    if order is not None:
        if order["art"] == "kauf":
            stop = k.eroeffnung * (1 + SCHLUPF) - order["stop_abstand"]
            pos = kaufen(konto, coin, k.eroeffnung, stop, k.zeit, order["grund"], preise)
            if pos is None:
                ereignisse.append(f"{coin}-Kauf fand nicht statt – kein Geld oder kein Platz frei")
            else:
                ereignisse.append(f"{coin} gekauft zu {_usd(pos.einstieg)} – {order['grund']}")
        elif coin in konto.positionen:
            trade = verkaufen(konto, coin, k.eroeffnung, k.zeit, order["grund"])
            ereignisse.append(_verkauf_satz(trade))

    # 3. Verlust-Limit (auch für eine eben erst gekaufte Position).
    pos = konto.positionen.get(coin)
    if pos is not None:
        if k.eroeffnung <= pos.stop:
            trade = verkaufen(konto, coin, k.eroeffnung, k.zeit, GRUND_STOP)
            ereignisse.append(_verkauf_satz(trade))
        elif k.tief <= pos.stop:
            trade = verkaufen(konto, coin, pos.stop, k.zeit, GRUND_STOP)
            ereignisse.append(_verkauf_satz(trade))

    # 4. Finanzierung (4 Stunden) und Pleite-Prüfung zum Schlusskurs.
    # Nur der geliehene Teil DIESES Coins: der Aufrufer ruft uns je Zeitpunkt
    # für BTC und ETH auf, konto.finanzierung() würde alles doppelt abbuchen.
    preise[coin] = k.schluss
    pos = konto.positionen.get(coin)
    if pos is not None and pos.geliehen > 0:
        konto.bargeld -= FINANZIERUNG_TAG * KERZEN_STUNDEN / 24 * pos.geliehen
    if pruefe_pleite(konto, preise, k.zeit):
        ereignisse.append(f"Konto {konto.name} ist pleite – alle Positionen zwangsverkauft")
        return ereignisse

    # 5. Am Schluss: Stop nachziehen, Trendbruch -> Verkauf vormerken.
    pos = konto.positionen.get(coin)
    if pos is not None:
        pos.hoechster_schluss = max(pos.hoechster_schluss, k.schluss)
        if ind.atr[i] is not None:
            pos.stop = max(pos.stop, pos.hoechster_schluss - p.k_trail * ind.atr[i])
        if ind.tief_aus[i] is not None and k.schluss < ind.tief_aus[i]:
            grund = f"Trend gebrochen: Schluss unter dem {p.n_aus}-Kerzen-Tief"
            konto.vorgemerkt[coin] = {"art": "verkauf", "grund": grund, "stop_abstand": 0.0}
            ereignisse.append(f"{coin}-Verkauf vorgemerkt – {grund}")
        return ereignisse

    # 6. Ohne Position: Ausbruch im Aufwärtstrend -> Kauf vormerken.
    if coin in konto.vorgemerkt or bremse_aktiv:
        return ereignisse
    e, a, h = ind.ema[i], ind.atr[i], ind.hoch_ein[i]
    if e is None or a is None or h is None:
        return ereignisse
    if k.schluss > e and k.schluss > h:
        grund = f"Ausbruch über das {p.n_ein}-Kerzen-Hoch im Aufwärtstrend"
        konto.vorgemerkt[coin] = {"art": "kauf", "grund": grund, "stop_abstand": p.k_stop * a}
        ereignisse.append(f"{coin}-Kauf vorgemerkt – {grund}")
    return ereignisse
