"""Zustand des Live-Laufs: JSON-Dateien atomar lesen/schreiben, Konten (de)serialisieren."""
import json
import os
from dataclasses import asdict
from pathlib import Path

from .konto import MUTIG, MUTIG_HEBEL, RUHIG, Konto, Position, Trade

DATEI = "zustand.json"
STUFEN = {s.name: s for s in (RUHIG, MUTIG, MUTIG_HEBEL)}


def stufe_aus_name(name):
    try:
        return STUFEN[name]
    except KeyError:
        raise ValueError(f"Unbekannte Risiko-Stufe: {name!r}") from None


def schreibe_json(pfad, daten):
    """Erst in eine Nachbar-Datei schreiben, dann ersetzen: nie eine halbe Datei."""
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, pfad)


class ZustandFehler(Exception):
    pass


def lies_json(pfad):
    pfad = Path(pfad)
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as fehler:
        raise ZustandFehler(f"Datei {pfad.name} ist beschädigt (kein gültiges JSON: {fehler})") from fehler


def lade(ordner):
    """Zustand oder None, wenn es noch keinen gibt (kaputte Datei -> Fehler)."""
    pfad = Path(ordner) / DATEI
    if not pfad.exists():
        return None
    return lies_json(pfad)


def speichere(ordner, zustand):
    schreibe_json(Path(ordner) / DATEI, zustand)


def konto_als_dict(konto):
    return {
        "name": konto.name,
        "stufe": konto.stufe.name,
        "bargeld": konto.bargeld,
        "pleite": konto.pleite,
        "positionen": {c: asdict(p) for c, p in konto.positionen.items()},
        "vorgemerkt": {c: dict(o) for c, o in konto.vorgemerkt.items()},
        "trades": [asdict(t) for t in konto.trades],
    }


def konto_aus_dict(d):
    return Konto(
        name=d["name"],
        stufe=stufe_aus_name(d["stufe"]),
        bargeld=float(d["bargeld"]),
        positionen={c: Position(**p) for c, p in d.get("positionen", {}).items()},
        trades=[Trade(**t) for t in d.get("trades", [])],
        pleite=bool(d.get("pleite", False)),
        vorgemerkt={c: dict(o) for c, o in d.get("vorgemerkt", {}).items()},
    )
