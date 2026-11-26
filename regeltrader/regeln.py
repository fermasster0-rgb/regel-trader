"""Regel-Parameter und Indikator-Berechnung für die Kerzen-Logik."""
from dataclasses import dataclass

from .indikatoren import atr, donchian_hoch, donchian_tief, ema


def _zahl(x):
    return f"{x:g}".replace(".", ",")


@dataclass(frozen=True)
class Parameter:
    n_trend: int
    n_ein: int
    n_aus: int
    k_stop: float
    k_trail: float = 3.0
    n_atr: int = 14

    def beschreibung(self):
        return (
            f"Trend: Durchschnitt der letzten {self.n_trend} Kerzen · "
            f"Kauf: Ausbruch über das {self.n_ein}-Kerzen-Hoch · "
            f"Verkauf: Schluss unter dem {self.n_aus}-Kerzen-Tief · "
            f"Verlust-Limit: {_zahl(self.k_stop)} × übliche Schwankung, "
            f"nachgezogen mit {_zahl(self.k_trail)} × übliche Schwankung"
        )


@dataclass
class Indikatoren:
    ema: list
    atr: list
    hoch_ein: list
    tief_aus: list


def berechne(kerzen, p):
    """Indikatoren über die ganze Liste. Wert an Index i nutzt nur Kerzen <= i
    (Donchian sogar nur < i) – kein Blick in die Zukunft."""
    hoch = [k.hoch for k in kerzen]
    tief = [k.tief for k in kerzen]
    schluss = [k.schluss for k in kerzen]
    return Indikatoren(
        ema=ema(schluss, p.n_trend),
        atr=atr(hoch, tief, schluss, p.n_atr),
        hoch_ein=donchian_hoch(hoch, p.n_ein),
        tief_aus=donchian_tief(tief, p.n_aus),
    )
