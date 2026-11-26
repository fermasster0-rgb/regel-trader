"""Kostenlose Nachrichten-Bremse: keine NEUEN Käufe bei Schock-Meldungen oder US-Terminen.
Die Bremse verkauft nie."""
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

STUNDE_MS = 3_600_000
SCHOCK_FENSTER_MS = 6 * STUNDE_MS
SCHOCK_SPERRE_MS = 24 * STUNDE_MS
TERMIN_VOR_MS = 12 * STUNDE_MS
TERMIN_NACH_MS = 4 * STUNDE_MS

FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/feed",
}

# Ereignis-Wendungen statt nackter Hauptwörter: nur der TITEL wird geprüft, ganze Wörter,
# Groß/klein egal, Leerraum vereinheitlicht. Bewusst NICHT drin (zu viele Fehlalarme mit
# Rückblicken und guten Nachrichten): "hack", "exploit", "ban", "banned", "bankrupt",
# "lawsuit against" – z. B. "Lift Its ICO Ban", "Binance Hack (2019)", "Bankrupt exchange repays".
_BETRAG = r"\$[\d.,]+ ?(?:[mbk]|mn|bn|million|billion)?"
STICHWORTE = [
    r"hacked",
    r"exploited",
    r"drained",
    r"(?:halts?|halted|suspends?|suspended|pauses?|paused|freezes|froze) withdrawals",
    r"withdrawals (?:halted|suspended|paused|frozen)",
    r"(?:files?|filed|filing) for bankruptcy",
    r"insolvent",
    r"insolvency",
    r"depeg(?:s|ged)?",
    r"(?:loses|lost) (?:its )?peg",
    r"sec (?:sues|sued)",
    r"bans? (?:crypto|bitcoin|stablecoins?)",
    r"delist(?:s|ed|ing)?",
    r"gehackt",
    r"insolvenz",
    r"pleite",
    r"verbietet (?:krypto|bitcoin)",
    # Hauptwort nur mit Betrag oder Opfer-Verb davor: "suffers $1.5B hack", "hit by an exploit"
    _BETRAG + r" (?:hack|exploit|heist)",
    r"(?:suffers?|suffered|hit by)(?: an?)?(?: " + _BETRAG + r")? (?:hack|exploit|heist)",
]
# (?<!\w)…(?!\w) statt \b: ganze Wörter, auch wenn eine Wendung mit "$" beginnt
_MUSTER = re.compile(r"(?<!\w)(?:" + "|".join(STICHWORTE) + r")(?!\w)", re.IGNORECASE)


def ist_schock(titel):
    """True, wenn der Titel eine Schock-Wendung enthält (Leerraum wird vereinheitlicht)."""
    return bool(_MUSTER.search(" ".join(str(titel).split())))


def standard_hole_text(url):
    anfrage = urllib.request.Request(url, headers={"User-Agent": "regel-trader"})
    with urllib.request.urlopen(anfrage, timeout=20) as antwort:
        return antwort.read().decode("utf-8", errors="replace")


def _lokal(tag):
    return tag.rsplit("}", 1)[-1]


def _kind_text(elem, *namen):
    for kind in elem:
        if _lokal(kind.tag) in namen and kind.text and kind.text.strip():
            return kind.text.strip()
    return ""


def _zeit_ms(text):
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _link(elem):
    for kind in elem:
        if _lokal(kind.tag) == "link":
            if kind.get("href"):
                return kind.get("href")
            if kind.text and kind.text.strip():
                return kind.text.strip()
    return ""


def _parse(text, quelle):
    wurzel = ET.fromstring(text)
    meldungen = []
    for elem in wurzel.iter():
        if _lokal(elem.tag) not in ("item", "entry"):
            continue
        titel = _kind_text(elem, "title")
        zeit = _zeit_ms(_kind_text(elem, "pubDate", "updated", "published"))
        if not titel or zeit is None:
            continue
        meldungen.append({
            "titel": titel, "quelle": quelle, "zeit_ms": zeit, "link": _link(elem),
        })
    return meldungen


def lies_meldungen(hole_text=standard_hole_text):
    """Alle Meldungen aller erreichbaren Feeds; zweiter Wert: mind. ein Feed erreichbar.
    Erreichbar heißt: abgerufen, lesbar UND mindestens eine Meldung mit Titel und Zeit."""
    alle, ok = [], False
    for name, url in FEEDS.items():
        try:
            meldungen = _parse(hole_text(url), name)
        except Exception:
            continue
        if meldungen:
            alle.extend(meldungen)
            ok = True
    return alle, ok


@dataclass
class BremsStatus:
    aktiv: bool
    bis_ms: "int | None"
    grund: str
    quelle: str
    nachrichten_ok: bool

    def als_dict(self):
        return asdict(self)

    @classmethod
    def aus_dict(cls, d):
        return cls(bool(d["aktiv"]), d.get("bis_ms"), d.get("grund", ""),
                   d.get("quelle", ""), bool(d.get("nachrichten_ok", True)))


def bremse_pruefen(jetzt_ms, meldungen, termine, nachrichten_ok, vorher):
    sperren = []  # (bis_ms, grund, quelle)
    for m in meldungen:
        alter = jetzt_ms - m["zeit_ms"]
        if 0 <= alter <= SCHOCK_FENSTER_MS:
            if ist_schock(m["titel"]):  # nur der Titel, nie die Beschreibung
                sperren.append((m["zeit_ms"] + SCHOCK_SPERRE_MS,
                                f"Schock-Meldung: {m['titel']}",
                                f"{m['quelle']} {m.get('link', '')}".strip()))
    for t in termine:
        z = _zeit_ms(t["zeit"])
        if z is not None and z - TERMIN_VOR_MS <= jetzt_ms <= z + TERMIN_NACH_MS:
            sperren.append((z + TERMIN_NACH_MS, f"Termin: {t['name']}",
                            t.get("quelle", "termine.json")))
    if vorher is not None and vorher.aktiv and vorher.bis_ms and vorher.bis_ms > jetzt_ms:
        sperren.append((vorher.bis_ms, vorher.grund, vorher.quelle))
    if not sperren:
        return BremsStatus(False, None, "", "", nachrichten_ok)
    bis, grund, quelle = max(sperren, key=lambda s: s[0])
    return BremsStatus(True, bis, grund, quelle, nachrichten_ok)
