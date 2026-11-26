"""Live-Lauf (GitHub Actions alle 4 Stunden): Kerzen holen, drei Konten handeln, Dateien schreiben.

Aufruf: python -m regeltrader.live  (liest und schreibt daten/)
Jeder Fehler landet in daten/status.json; der Lauf endet immer mit Exit-Code 0.
"""
import json
import sys
import time
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

from . import zustand as zs
from .bremse import BremsStatus, bremse_pruefen, lies_meldungen, standard_hole_text
from .engine import verarbeite_kerze
from .kerzen import INTERVALL_MS, KursFehler, hole_kerzen, standard_hole_json
from .konto import GEBUEHR, RUHIG, SCHLUPF, Konto, nettowert, verkaufserloes
from .regeln import Parameter, berechne

COINS = ("BTC", "ETH")
STARTKAPITAL = 10000.0
KERZEN_HOLEN = 1000          # Vorlauf für die EMA 200 (Kraken liefert höchstens 720)
TAG_MS = 86_400_000
LAUF_ABSTAND_MS = 4 * 3_600_000
PROBE_TAGE = 56
MIN_TRADES = 5
MAX_EREIGNISSE = 50
VORLAUF_EXTRA = 50           # Kerzen über den längsten Indikator hinaus
KONTEN = (("ohne_bremse", "Ohne Bremse"), ("mit_bremse", "Mit Bremse"), ("mutig", "Mutig"))
ENDGUELTIG = {"bewiesen", "nicht_bewiesen", "zu_wenige_trades"}
WURZEL = Path(__file__).resolve().parent.parent


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def abgeschlossene_tage(start_ms, jetzt_ms):
    """Volle Tage seit dem Start (0 am ersten Tag)."""
    return max(0, (jetzt_ms - start_ms) // TAG_MS)


def urteil(kontowert, abgeschlossene_trades, tage):
    """tage = VOLLE Tage seit dem Start: das Urteil fällt, sobald 56 volle Tage vorbei sind."""
    if tage < PROBE_TAGE:
        return "laeuft"
    if abgeschlossene_trades < MIN_TRADES:
        return "zu_wenige_trades"
    return "bewiesen" if kontowert > STARTKAPITAL else "nicht_bewiesen"


def konto_urteil(vorher, kontowert, abgeschlossene_trades, tage):
    """Das Urteil fällt nach 56 vollen Tagen und bleibt danach stehen (der Trader läuft weiter)."""
    if vorher in ENDGUELTIG:
        return vorher
    return urteil(kontowert, abgeschlossene_trades, tage)


def trades_liste(konten):
    """Alle abgeschlossenen Trades aller Konten, neueste zuerst; ergebnis_pct in Prozent."""
    zeilen = []
    for schluessel, konto in konten.items():
        for t in konto.trades:
            zeilen.append({
                "konto": schluessel,
                "coin": t.coin,
                "kauf_zeit": t.kauf_zeit,
                "kauf_preis": round(t.kauf_preis, 2),
                "verkauf_zeit": t.verkauf_zeit,
                "verkauf_preis": round(t.verkauf_preis, 2),
                "menge": t.menge,
                "ergebnis_usd": round(t.ergebnis_usd, 2),
                "ergebnis_pct": round(t.ergebnis_pct * 100, 2),
                "grund_kauf": t.grund_kauf,
                "grund_verkauf": t.grund_verkauf,
            })
    zeilen.sort(key=lambda z: (z["verkauf_zeit"], z["kauf_zeit"]), reverse=True)
    return zeilen


def _erste_datei(*pfade):
    return next((p for p in pfade if p.exists()), None)


def _termine(ordner, termine_pfad):
    pfad = Path(termine_pfad) if termine_pfad else _erste_datei(
        ordner.parent / "termine.json", WURZEL / "termine.json")
    return zs.lies_json(pfad) if pfad else []


def _rueckblick(ordner):
    pfad = _erste_datei(ordner / "rueckblick.json", WURZEL / "daten" / "rueckblick.json")
    if pfad is None:
        raise zs.ZustandFehler("rueckblick.json fehlt – ohne Rückblick-Ergebnis kein Start")
    return zs.lies_json(pfad)


def _parameter(d):
    return Parameter(**{f.name: d[f.name] for f in fields(Parameter) if f.name in d})


def mindest_kerzen(parameter):
    """So viele Kerzen braucht jeder Coin, damit alle Indikatoren eingeschwungen sind."""
    p = _parameter(parameter)
    return max(p.n_trend, p.n_ein, p.n_aus, p.n_atr) + VORLAUF_EXTRA


def _kerzen_holen(jetzt_ms, hole_json, mindestens):
    kerzen, quellen = {}, {}
    for coin in COINS:
        liste, quelle = hole_kerzen(coin, jetzt_ms - KERZEN_HOLEN * INTERVALL_MS, jetzt_ms,
                                    hole_json=hole_json)
        if len(liste) < mindestens:
            raise KursFehler(f"zu wenige {coin}-Kerzen erhalten ({len(liste)}, "
                             f"nötig sind mindestens {mindestens})")
        kerzen[coin], quellen[coin] = liste, quelle
    return kerzen, quellen


def _neu(ordner, jetzt_ms, kerzen):
    rb = _rueckblick(ordner)
    stufe_mutig = zs.stufe_aus_name(rb["mutig_stufe"])
    _parameter(rb["parameter"])  # früh prüfen, ob die Parameter vollständig sind
    konten = {
        "ohne_bremse": Konto("Ohne Bremse", RUHIG, STARTKAPITAL),
        "mit_bremse": Konto("Mit Bremse", RUHIG, STARTKAPITAL),
        "mutig": Konto("Mutig", stufe_mutig, STARTKAPITAL),
    }
    preise = {c: kerzen[c][-1].schluss for c in COINS}
    start_preis = preise["BTC"]
    return {
        "start_ms": jetzt_ms,
        "letzte_kerze": {c: kerzen[c][-1].zeit for c in COINS},
        "preise": preise,
        "parameter": dict(rb["parameter"]),
        "konten": konten,
        "btc_halten": {
            "menge": STARTKAPITAL / (start_preis * (1 + SCHLUPF) * (1 + GEBUEHR)),
            "start_preis": start_preis,
        },
        "bremse": None,
        "ereignisse": [],
        "urteile": {},
    }


def _aus_datei(alt):
    return {
        "start_ms": alt["start_ms"],
        "letzte_kerze": dict(alt["letzte_kerze"]),
        "preise": dict(alt["preise"]),
        "parameter": alt["parameter"],
        "konten": {s: zs.konto_aus_dict(alt["konten"][s]) for s, _ in KONTEN},
        "btc_halten": {"menge": alt["btc_halten"]["menge"],
                       "start_preis": alt["btc_halten"]["start_preis"]},
        "bremse": BremsStatus.aus_dict(alt["bremse"]) if alt.get("bremse") else None,
        "ereignisse": list(alt.get("ereignisse", [])),
        "urteile": {s: alt["konten"][s].get("urteil") for s, _ in KONTEN},
    }


def _handeln(z, kerzen, bremse_aktiv):
    """Alle neuen Kerzen (zeit > letzte_kerze je Coin) der Reihe nach, BTC vor ETH."""
    p = _parameter(z["parameter"])
    letzte, preise, konten = z["letzte_kerze"], z["preise"], z["konten"]
    ind = {c: berechne(kerzen[c], p) for c in COINS}
    index = {c: {k.zeit: i for i, k in enumerate(kerzen[c])} for c in COINS}
    zeiten = sorted({k.zeit for c in COINS for k in kerzen[c] if k.zeit > letzte[c]})
    neu = []
    for t in zeiten:
        for c in COINS:
            i = index[c].get(t)
            if i is None or t <= letzte[c]:
                continue
            for s, _ in KONTEN:
                bremse = bremse_aktiv and s == "mit_bremse"
                for satz in verarbeite_kerze(konten[s], c, kerzen[c], ind[c], i, p, bremse, preise):
                    neu.append({"zeit": t, "konto": s, "text": satz})
            preise[c] = kerzen[c][i].schluss
            letzte[c] = t
    return neu


def _ausgabe(z, jetzt_ms, bremse):
    tage = abgeschlossene_tage(z["start_ms"], jetzt_ms)
    tag = tage + 1  # zur Anzeige "Tag X / 56" (der erste Tag ist Tag 1)
    preise = z["preise"]
    konten = {}
    for s, _ in KONTEN:
        k = z["konten"][s]
        wert = nettowert(k, preise)  # nach allen Gebühren, wie bei einem Verkauf jetzt
        d = zs.konto_als_dict(k)
        d["wert"] = round(wert, 2)
        d["abgeschlossene_trades"] = len(k.trades)
        d["urteil"] = konto_urteil(z["urteile"].get(s), wert, len(k.trades), tage)
        konten[s] = d
    b = z["btc_halten"]
    return {
        "start_ms": z["start_ms"],
        "tag": tag,
        "abgeschlossene_tage": tage,
        "letzte_kerze": z["letzte_kerze"],
        "preise": preise,
        "parameter": z["parameter"],
        "konten": konten,
        "btc_halten": {"menge": b["menge"], "start_preis": b["start_preis"],
                       "wert": round(verkaufserloes(b["menge"], preise["BTC"]), 2)},
        "bremse": bremse.als_dict(),
        "ereignisse": z["ereignisse"][:MAX_EREIGNISSE],
    }


def _lauf(ordner, jetzt_ms, hole_json, hole_text, termine_pfad):
    alt = zs.lade(ordner)
    erster = alt is None
    parameter = _rueckblick(ordner)["parameter"] if erster else alt["parameter"]
    kerzen, quellen = _kerzen_holen(jetzt_ms, hole_json, mindest_kerzen(parameter))
    z = _neu(ordner, jetzt_ms, kerzen) if erster else _aus_datei(alt)

    meldungen, nachrichten_ok = lies_meldungen(hole_text=hole_text)
    bremse = bremse_pruefen(jetzt_ms, meldungen, _termine(ordner, termine_pfad),
                            nachrichten_ok, z["bremse"])

    if not erster:  # beim ersten Lauf wird nur die Startmarke gesetzt, nicht gehandelt
        neu = _handeln(z, kerzen, bremse.aktiv)
        z["ereignisse"] = list(reversed(neu)) + z["ereignisse"]

    ausgabe = _ausgabe(z, jetzt_ms, bremse)
    punkt = {"zeit": jetzt_ms}
    punkt.update({s: ausgabe["konten"][s]["wert"] for s, _ in KONTEN})
    punkt["btc_halten"] = ausgabe["btc_halten"]["wert"]
    pfad_verlauf = ordner / "verlauf.json"
    verlauf = [] if erster or not pfad_verlauf.exists() else zs.lies_json(pfad_verlauf)
    if verlauf and verlauf[-1].get("zeit") == jetzt_ms:
        verlauf[-1] = punkt
    else:
        verlauf.append(punkt)

    # Zustand zuletzt: er ist der Merkpunkt. Scheitert vorher etwas, wird beim
    # nächsten Lauf dieselbe Kerze noch einmal (gleich) gerechnet – nie doppelt gehandelt.
    zs.schreibe_json(ordner / "trades.json", trades_liste(z["konten"]))
    zs.schreibe_json(pfad_verlauf, verlauf)
    zs.speichere(ordner, ausgabe)
    return "binance" if all(q == "binance" for q in quellen.values()) else "kraken"


def _fehlertext(fehler):
    if isinstance(fehler, KursFehler):
        text = f"Kurse nicht abrufbar, in diesem Lauf wurde nicht gehandelt ({fehler})"
    elif isinstance(fehler, zs.ZustandFehler):
        text = f"{fehler} – nichts verändert, nicht gehandelt"
    else:
        text = (f"Unerwarteter Fehler ({type(fehler).__name__}: {fehler}) – "
                "nichts verändert, nicht gehandelt")
    return " ".join(text.split())[:500]


def lauf(ordner, jetzt_ms, hole_json=standard_hole_json, hole_text=standard_hole_text,
         termine_pfad=None):
    ordner = Path(ordner)
    status = {"letzter_lauf": iso(jetzt_ms), "ok": True, "fehler": None, "quelle": None,
              "naechster_lauf_ca": iso(jetzt_ms + LAUF_ABSTAND_MS)}
    try:
        status["quelle"] = _lauf(ordner, jetzt_ms, hole_json, hole_text, termine_pfad)
    except Exception as fehler:
        status["ok"] = False
        status["fehler"] = _fehlertext(fehler)
    try:
        zs.schreibe_json(ordner / "status.json", status)
    except Exception as fehler:  # nicht einmal der Status ließ sich schreiben
        print(f"status.json nicht schreibbar: {fehler!r}", file=sys.stderr)


def main():
    lauf(Path("daten"), int(time.time() * 1000))
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print((Path("daten") / "status.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
