"""Rückblick-Test: Regeln auf 2021–2023 festlegen, einmal auf 2024–heute prüfen.

Aufruf: py -3 -m regeltrader.rueckblick  (schreibt daten/rueckblick.json)
Der Test läuft EINMAL beim Bauen. Das Ergebnis bleibt danach fest.
"""
import itertools
import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone

from .engine import verarbeite_kerze
from .kerzen import INTERVALL_MS, Kerze, hole_kerzen
from .konto import GEBUEHR, MUTIG, MUTIG_HEBEL, RUHIG, SCHLUPF, Konto, kontowert
from .regeln import Parameter, berechne

STARTKAPITAL = 10000.0
COINS = ("BTC", "ETH")
MIN_TRADES = 30
MAX_HEBEL_ABSTURZ = 50.0

WERTE = {
    "n_trend": (100, 200),
    "n_ein": (20, 40, 55),
    "n_aus": (10, 20),
    "k_stop": (2.0, 3.0),
}
RASTER = [
    Parameter(n_trend=t, n_ein=e, n_aus=a, k_stop=k)
    for t, e, a, k in itertools.product(*WERTE.values())
]


@dataclass
class Ergebnis:
    rendite_pct: float
    tiefster_absturz_pct: float
    trades: int
    trefferquote_pct: float
    groesster_trade_pct: float
    trades_ueber_10: int
    verlauf: list  # [(zeit_ms, kontowert)], erster Punkt = Startkapital


def tiefster_absturz(werte):
    """Größter Rückgang vom bisherigen Höchststand, in Prozent."""
    hoechst = None
    absturz = 0.0
    for w in werte:
        if hoechst is None or w > hoechst:
            hoechst = w
        if hoechst > 0:
            absturz = max(absturz, (hoechst - w) / hoechst * 100)
    return absturz


def punktzahl(e):
    return e.rendite_pct / max(e.tiefster_absturz_pct, 1.0)


def _zeitstempel(kerzen, von_ms, bis_ms):
    """Gemeinsame Zeitstempel aller Coins im Zeitraum [von, bis), aufsteigend."""
    gemeinsam = None
    for liste in kerzen.values():
        zeiten = {k.zeit for k in liste}
        gemeinsam = zeiten if gemeinsam is None else gemeinsam & zeiten
    return sorted(z for z in (gemeinsam or ()) if von_ms <= z < bis_ms)


def _ergebnis(verlauf, trades):
    werte = [w for _, w in verlauf]
    prozente = [t.ergebnis_pct * 100 for t in trades]  # Trade.ergebnis_pct ist ein Anteil
    return Ergebnis(
        rendite_pct=(werte[-1] / STARTKAPITAL - 1) * 100,
        tiefster_absturz_pct=tiefster_absturz(werte),
        trades=len(trades),
        trefferquote_pct=(sum(1 for t in trades if t.ergebnis_usd > 0) / len(trades) * 100
                          if trades else 0.0),
        groesster_trade_pct=max(prozente) if prozente else 0.0,
        trades_ueber_10=sum(1 for x in prozente if x > 10),
        verlauf=verlauf,
    )


def simuliere(kerzen, p, stufe, von_ms, bis_ms):
    """Ein Konto handelt BTC und ETH gemeinsam in [von, bis).

    Indikatoren über die volle Reihe (die Engine liest nur Index <= i).
    Kontowert nach jedem Zeitstempel; offene Positionen am Ende zum letzten Schluss.
    """
    zeiten = _zeitstempel(kerzen, von_ms, bis_ms)
    konto = Konto(name=stufe.name, stufe=stufe, bargeld=STARTKAPITAL)
    if not zeiten:
        return _ergebnis([(von_ms, STARTKAPITAL)], [])
    indikatoren = {c: berechne(liste, p) for c, liste in kerzen.items()}
    index = {c: {k.zeit: i for i, k in enumerate(liste)} for c, liste in kerzen.items()}
    preise = {}
    for c, liste in kerzen.items():
        i0 = index[c][zeiten[0]]
        preise[c] = liste[i0 - 1].schluss if i0 > 0 else liste[0].schluss
    verlauf = [(zeiten[0], STARTKAPITAL)]
    for z in zeiten:
        for c in COINS:
            if c in kerzen:
                verarbeite_kerze(konto, c, kerzen[c], indikatoren[c], index[c][z], p, False, preise)
        verlauf.append((z + INTERVALL_MS, kontowert(konto, preise)))
    return _ergebnis(verlauf, konto.trades)


def halten(kerzen, gewichte, von_ms, bis_ms):
    """Kaufen zum ersten Eröffnungskurs im Zeitraum (mit Schlupf und Gebühr), dann liegen lassen."""
    zeiten = _zeitstempel({c: kerzen[c] for c in gewichte}, von_ms, bis_ms)
    if not zeiten:
        return _ergebnis([(von_ms, STARTKAPITAL)], [])
    nach_zeit = {c: {k.zeit: k for k in kerzen[c]} for c in gewichte}
    menge = {
        c: STARTKAPITAL * g / (nach_zeit[c][zeiten[0]].eroeffnung * (1 + SCHLUPF) * (1 + GEBUEHR))
        for c, g in gewichte.items()
    }
    verlauf = [(zeiten[0], STARTKAPITAL)]
    for z in zeiten:
        verlauf.append((z + INTERVALL_MS, sum(m * nach_zeit[c][z].schluss for c, m in menge.items())))
    return _ergebnis(verlauf, [])


def _nachbarn(p, kandidaten):
    """Kombinationen, die sich in genau einem Wert um genau eine Rasterstufe unterscheiden."""
    out = []
    for q in kandidaten:
        unterschiede = [f for f in WERTE if getattr(p, f) != getattr(q, f)]
        if len(unterschiede) != 1 or (p.k_trail, p.n_atr) != (q.k_trail, q.n_atr):
            continue
        f = unterschiede[0]
        liste = WERTE[f]
        if abs(liste.index(getattr(p, f)) - liste.index(getattr(q, f))) == 1:
            out.append(q)
    return out


def robust_waehlen(ergebnisse):
    """Höchste Mittelwert-Punktzahl aus sich selbst und den Raster-Nachbarn.

    Wählbar sind nur Kombinationen mit mindestens 30 Trades. Die Nachbarn zählen
    alle mit (auch solche mit weniger Trades), denn sie zeigen, ob die Gegend stabil ist.
    """
    wertung = {}
    for p, e in ergebnisse.items():
        if e.trades < MIN_TRADES:
            continue
        gruppe = [p] + _nachbarn(p, ergebnisse)
        wertung[p] = sum(punktzahl(ergebnisse[q]) for q in gruppe) / len(gruppe)
    if not wertung:
        raise ValueError(f"Keine Kombination hat mindestens {MIN_TRADES} Trades.")
    reihenfolge = list(ergebnisse)
    return max(wertung, key=lambda p: (wertung[p], punktzahl(ergebnisse[p]), -reihenfolge.index(p)))


def waehle_mutig(e_mutig, e_hebel):
    """Hebel nur bei Absturz <= 50 % und Punktzahl nicht schlechter als ohne Hebel."""
    if e_hebel.tiefster_absturz_pct <= MAX_HEBEL_ABSTURZ and punktzahl(e_hebel) >= punktzahl(e_mutig):
        return MUTIG_HEBEL
    return MUTIG


def _komma(x, stellen=1):
    return f"{x:.{stellen}f}".replace(".", ",")


def mutig_grund(e_mutig, e_hebel, stufe):
    a_h, a_m = e_hebel.tiefster_absturz_pct, e_mutig.tiefster_absturz_pct
    v_h, v_m = punktzahl(e_hebel), punktzahl(e_mutig)
    if stufe == MUTIG_HEBEL:
        return (f"Mit Hebel, weil der tiefste Absturz 2021–2023 bei {_komma(a_h)} % lag "
                f"(höchstens 50 % erlaubt) und das Verhältnis Rendite ÷ Absturz mit "
                f"{_komma(v_h, 2)} nicht schlechter war als ohne Hebel ({_komma(v_m, 2)}).")
    if a_h > MAX_HEBEL_ABSTURZ:
        return (f"Ohne Hebel, weil der Hebel 2021–2023 einen tiefsten Absturz von "
                f"{_komma(a_h)} % gehabt hätte – erlaubt sind höchstens 50 %.")
    return (f"Ohne Hebel, weil das Verhältnis Rendite ÷ Absturz mit Hebel 2021–2023 "
            f"schlechter war ({_komma(v_h, 2)} gegen {_komma(v_m, 2)} ohne Hebel).")


def ausduennen(verlauf, max_punkte=300):
    """Höchstens max_punkte Punkte; erster und letzter Punkt bleiben erhalten."""
    if len(verlauf) <= max_punkte:
        return list(verlauf)
    schritt = (len(verlauf) - 1) / (max_punkte - 1)
    indizes = sorted({round(j * schritt) for j in range(max_punkte)})
    return [verlauf[i] for i in indizes]


# ---------------------------------------------------------------- Hauptlauf

def _ms(jahr, monat, tag):
    return int(datetime(jahr, monat, tag, tzinfo=timezone.utc).timestamp() * 1000)


DATEN_START = _ms(2020, 9, 1)
KAL_VON, KAL_BIS = _ms(2021, 1, 1), _ms(2024, 1, 1)
PRUEF_VON = _ms(2024, 1, 1)
WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lade_kerzen(coin, jetzt_ms, hole=hole_kerzen):
    """Kerzen ab DATEN_START; vorhandener Cache wird nur um neue Kerzen ergänzt."""
    pfad = os.path.join(WURZEL, "cache", f"{coin}_4h.json")
    vorhanden = []
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as f:
            vorhanden = [Kerze(*z) for z in json.load(f)]
        if not vorhanden or vorhanden[0].zeit > DATEN_START:
            vorhanden = []
    start = vorhanden[-1].zeit + INTERVALL_MS if vorhanden else DATEN_START
    neu, quelle = hole(coin, start, jetzt_ms)
    if quelle != "binance":
        raise SystemExit(
            f"Abbruch: Für {coin} kamen die Kurse von {quelle} statt vom Binance-Datenspiegel. "
            "Kraken liefert nur etwa die letzten 720 Kerzen (rund 4 Monate) – ein stillschweigend "
            "verkürzter Rückblick wäre unehrlich. Bitte später noch einmal starten."
        )
    alle = {k.zeit: k for k in vorhanden + neu if k.zeit + INTERVALL_MS <= jetzt_ms}
    kerzen = [alle[z] for z in sorted(alle)]
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump([[k.zeit, k.eroeffnung, k.hoch, k.tief, k.schluss] for k in kerzen], f)
    return kerzen


def _luecken(liste, von_ms, bis_ms):
    zeiten = {k.zeit for k in liste}
    erwartet = range(von_ms, bis_ms - INTERVALL_MS + 1, INTERVALL_MS)
    return sum(1 for z in erwartet if z not in zeiten)


def _zusammenfassung(e):
    d = {f.name: getattr(e, f.name) for f in fields(e) if f.name != "verlauf"}
    for k, v in d.items():
        if isinstance(v, float):
            d[k] = round(v, 2)
    return d


def _verlauf_json(e):
    return [[z, round(w, 2)] for z, w in ausduennen(e.verlauf, 300)]


def _zeitraum(kerzen, p, von_ms, bis_ms):
    erg = {
        "ruhig": simuliere(kerzen, p, RUHIG, von_ms, bis_ms),
        "mutig": simuliere(kerzen, p, MUTIG, von_ms, bis_ms),
        "mutig_hebel": simuliere(kerzen, p, MUTIG_HEBEL, von_ms, bis_ms),
        "btc_halten": halten(kerzen, {"BTC": 1.0}, von_ms, bis_ms),
        "halten_50_50": halten(kerzen, {"BTC": 0.5, "ETH": 0.5}, von_ms, bis_ms),
    }
    return erg


def _zeitraum_json(erg, von_ms, bis_ms):
    d = {"von": _iso(von_ms), "bis": _iso(bis_ms)}
    d.update({name: _zusammenfassung(e) for name, e in erg.items()})
    d["verlauf"] = {"ruhig": _verlauf_json(erg["ruhig"]), "btc_halten": _verlauf_json(erg["btc_halten"])}
    return d


NAMEN = [("ruhig", "Ruhig"), ("mutig", "Mutig"), ("mutig_hebel", "Mutig + Hebel"),
         ("btc_halten", "Bitcoin halten"), ("halten_50_50", "50/50 halten")]


def _vorzeichen(x):
    return ("+" if x >= 0 else "−") + _komma(abs(x)) + " %"


def _text(stand_iso, p, stufe, grund, kal, pruef, bis_iso):
    zeilen = [
        "Rückblick-Test Regel-Trader (gerechnet bis " + stand_iso + ")",
        "Gewählte Regeln (aus 2021–2023, robust gewählt): " + p.beschreibung(),
        f"Mutig-Konto live: {stufe.name}. {grund}",
    ]
    for titel, erg in (("Kalibrierung 2021-01-01 bis 2023-12-31", kal),
                       (f"Prüfung 2024-01-01 bis {bis_iso[:10]} (nie zum Einstellen benutzt)", pruef)):
        zeilen.append("")
        zeilen.append(titel + ":")
        for schluessel, name in NAMEN:
            e = erg[schluessel]
            zeile = (f"  {name:<15} Rendite {_vorzeichen(e.rendite_pct):>10} · "
                     f"tiefster Absturz {_komma(e.tiefster_absturz_pct)} %")
            if schluessel not in ("btc_halten", "halten_50_50"):
                zeile += (f" · {e.trades} Trades, Treffer {_komma(e.trefferquote_pct, 0)} %, "
                          f"größter Trade {_vorzeichen(e.groesster_trade_pct)}, "
                          f"{e.trades_ueber_10}× über +10 %")
            zeilen.append(zeile)
    return "\n".join(zeilen)


def main():
    jetzt_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    stand = _iso(jetzt_ms)
    print("Lade Kerzen (Binance-Datenspiegel, Cache in cache/) …", flush=True)
    kerzen = {c: _lade_kerzen(c, jetzt_ms) for c in COINS}
    for c, liste in kerzen.items():
        print(f"  {c}: {len(liste)} Kerzen von {_iso(liste[0].zeit)} bis {_iso(liste[-1].zeit)}, "
              f"Lücken ab 2021: {_luecken(liste, KAL_VON, jetzt_ms)}", flush=True)

    print("Kalibrierung 2021–2023 mit Ruhig, 24 Kombinationen …", flush=True)
    raster = {p: simuliere(kerzen, p, RUHIG, KAL_VON, KAL_BIS) for p in RASTER}
    p = robust_waehlen(raster)

    kal = _zeitraum(kerzen, p, KAL_VON, KAL_BIS)
    pruef = _zeitraum(kerzen, p, PRUEF_VON, jetzt_ms)
    stufe = waehle_mutig(kal["mutig"], kal["mutig_hebel"])
    grund = mutig_grund(kal["mutig"], kal["mutig_hebel"], stufe)

    kal_json = _zeitraum_json(kal, KAL_VON, KAL_BIS)
    kal_json["raster"] = [
        dict(asdict(q), punktzahl=round(punktzahl(e), 3), **{
            k: v for k, v in _zusammenfassung(e).items()
            if k in ("rendite_pct", "tiefster_absturz_pct", "trades")})
        for q, e in raster.items()
    ]
    ausgabe = {
        "stand": stand,
        "parameter": dict(asdict(p), beschreibung=p.beschreibung()),
        "mutig_stufe": stufe.name,
        "mutig_grund": grund,
        "kalibrierung": kal_json,
        "pruefung": _zeitraum_json(pruef, PRUEF_VON, jetzt_ms),
    }
    ziel = os.path.join(WURZEL, "daten", "rueckblick.json")
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump(ausgabe, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print()
    print(_text(stand, p, stufe, grund, kal, pruef, stand))
    print()
    print("Geschrieben: daten/rueckblick.json")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
