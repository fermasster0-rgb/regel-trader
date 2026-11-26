"""Technische Indikatoren (nur Standardbibliothek)."""


def ema(werte, n):
    """Exponentieller Durchschnitt; None bis Index n-2, Start mit SMA der ersten n Werte."""
    ergebnis = [None] * len(werte)
    if n < 1 or len(werte) < n:
        return ergebnis
    wert = sum(werte[:n]) / n
    ergebnis[n - 1] = wert
    k = 2 / (n + 1)
    for i in range(n, len(werte)):
        wert = werte[i] * k + wert * (1 - k)
        ergebnis[i] = wert
    return ergebnis


def atr(hoch, tief, schluss, n=14):
    """Average True Range mit Wilder-Glättung; erster Wert an Index n-1."""
    anzahl = len(schluss)
    ergebnis = [None] * anzahl
    if n < 1 or anzahl < n:
        return ergebnis
    spannen = [hoch[0] - tief[0]]
    for i in range(1, anzahl):
        spannen.append(max(hoch[i] - tief[i],
                           abs(hoch[i] - schluss[i - 1]),
                           abs(tief[i] - schluss[i - 1])))
    wert = sum(spannen[:n]) / n
    ergebnis[n - 1] = wert
    for i in range(n, anzahl):
        wert = (wert * (n - 1) + spannen[i]) / n
        ergebnis[i] = wert
    return ergebnis


def donchian_hoch(hoch, n):
    """Höchster Wert der Kerzen i-n bis i-1 (ohne Kerze i)."""
    return [max(hoch[i - n:i]) if i >= n else None for i in range(len(hoch))]


def donchian_tief(tief, n):
    """Tiefster Wert der Kerzen i-n bis i-1 (ohne Kerze i)."""
    return [min(tief[i - n:i]) if i >= n else None for i in range(len(tief))]
