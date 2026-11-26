"""Konto-Modell: Risiko-Stufen, Positionsgroesse, Kosten, Hebel, Pleite."""
from dataclasses import dataclass, field

GEBUEHR = 0.001
SCHLUPF = 0.0005
FINANZIERUNG_TAG = 0.0003


@dataclass(frozen=True)
class Stufe:
    name: str
    risiko: float
    max_coin: float
    max_gesamt: float
    hebel: float


RUHIG = Stufe("Ruhig", 0.01, 0.45, 0.90, 1)
MUTIG = Stufe("Mutig", 0.03, 0.90, 1.00, 1)
MUTIG_HEBEL = Stufe("Mutig + Hebel", 0.03, 1.80, 2.00, 2)


@dataclass
class Position:
    coin: str
    menge: float
    einstieg: float
    einstieg_zeit: int
    stop: float
    hoechster_schluss: float
    geliehen: float
    grund_kauf: str = ""


@dataclass
class Trade:
    coin: str
    kauf_zeit: int
    kauf_preis: float
    verkauf_zeit: int
    verkauf_preis: float
    menge: float
    ergebnis_usd: float
    ergebnis_pct: float
    grund_kauf: str
    grund_verkauf: str


@dataclass
class Konto:
    name: str
    stufe: Stufe
    bargeld: float = 10000.0
    positionen: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)
    pleite: bool = False
    vorgemerkt: dict = field(default_factory=dict)


def kontowert(konto, preise):
    return konto.bargeld + sum(
        p.menge * preise.get(p.coin, p.einstieg) - p.geliehen
        for p in konto.positionen.values()
    )


def verkaufserloes(menge, preis):
    """Was ein Verkauf zum Kurs preis nach Schlupf und Gebühr einbrächte."""
    return menge * preis * (1 - SCHLUPF) * (1 - GEBUEHR)


def nettowert(konto, preise):
    """Kontostand "nach allen Gebühren": offene Positionen so bewertet, als würden sie jetzt
    verkauft (genau wie verkaufen() rechnet). Gilt für Urteil, Dashboard und Verlauf;
    die Positionsgröße und die Pleite-Prüfung rechnen weiter mit kontowert()."""
    return konto.bargeld + sum(
        verkaufserloes(p.menge, preise.get(p.coin, p.einstieg)) - p.geliehen
        for p in konto.positionen.values()
    )


def positionsgroesse(konto, coin, preis, stop, preise):
    if preis <= 0 or stop >= preis:
        return 0.0
    wert = kontowert(konto, preise)
    if wert <= 0:
        return 0.0
    s = konto.stufe
    investiert = sum(
        p.menge * preise.get(p.coin, p.einstieg) for p in konto.positionen.values()
    )
    menge = min(
        s.risiko * wert / (preis - stop),
        s.max_coin * wert / preis,
        (s.max_gesamt * wert - investiert) / preis,
    )
    return max(0.0, menge)


def kaufen(konto, coin, preis_roh, stop, zeit, grund, preise):
    if konto.pleite or coin in konto.positionen:
        return None
    fill = preis_roh * (1 + SCHLUPF)
    menge = positionsgroesse(konto, coin, preis_roh, stop, preise)
    if menge <= 0:
        return None
    kosten_pro_stueck = fill * (1 + GEBUEHR)
    if konto.stufe.hebel <= 1:
        menge = min(menge, max(0.0, konto.bargeld) / kosten_pro_stueck)
        if menge <= 0:
            return None
    gesamt = menge * kosten_pro_stueck
    geliehen = max(0.0, gesamt - konto.bargeld) if konto.stufe.hebel > 1 else 0.0
    konto.bargeld = konto.bargeld - gesamt + geliehen
    pos = Position(coin, menge, fill, zeit, stop, fill, geliehen, grund)
    konto.positionen[coin] = pos
    return pos


def verkaufen(konto, coin, preis_roh, zeit, grund):
    pos = konto.positionen.pop(coin)
    fill = preis_roh * (1 - SCHLUPF)
    erloes = pos.menge * fill
    gebuehr_verkauf = erloes * GEBUEHR
    gebuehr_kauf = pos.menge * pos.einstieg * GEBUEHR
    konto.bargeld += erloes - gebuehr_verkauf - pos.geliehen
    usd = erloes - pos.menge * pos.einstieg - gebuehr_verkauf - gebuehr_kauf
    pct = usd / (pos.menge * pos.einstieg)
    trade = Trade(coin, pos.einstieg_zeit, pos.einstieg, zeit, fill, pos.menge,
                  usd, pct, pos.grund_kauf, grund)
    konto.trades.append(trade)
    return trade


def finanzierung(konto, stunden):
    geliehen = sum(p.geliehen for p in konto.positionen.values())
    konto.bargeld -= FINANZIERUNG_TAG * stunden / 24 * geliehen


def pruefe_pleite(konto, preise, zeit):
    if konto.pleite:
        return True
    if kontowert(konto, preise) > 0:
        return False
    for coin in list(konto.positionen):
        verkaufen(konto, coin, preise.get(coin, konto.positionen[coin].einstieg),
                  zeit, "Pleite: Zwangsverkauf")
    konto.vorgemerkt.clear()
    konto.pleite = True
    return True
