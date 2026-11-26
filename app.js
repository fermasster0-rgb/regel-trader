// Regel-Trader – Dashboard. Kein Framework, keine Bibliothek.
// Alle Inhalte werden mit createElement/textContent gebaut (nie innerHTML mit Daten).
// Am PC: ein Bildschirm ohne Scrollen (CSS-Grid). Am Handy: alles untereinander.
(function () {
  "use strict";

  var START_KAPITAL = 10000;
  var PROBE_TAGE = 56;
  var MIN_TRADES = 5;
  var VERALTET_STUNDEN = 9;
  var NEU_LADEN_MS = 5 * 60 * 1000;
  var ZONE = "Europe/Vienna";
  var SVG_NS = "http://www.w3.org/2000/svg";

  // ?beispiel=1 / urteil / veraltet laden Beispiel-Dateien statt der echten
  var param = new URLSearchParams(location.search).get("beispiel");
  var BEISPIEL = param !== null && param !== "0" && param !== "";
  var ORDNER = !BEISPIEL ? "daten/" : (param === "urteil" ? "daten/beispiel-urteil/" : "daten/beispiel/");
  var ALTER_PRUEFEN = !BEISPIEL || param === "veraltet";

  var KONTEN = [
    { key: "ohne_bremse", name: "Ohne Bremse", kurz: "Ruhig, ohne Nachrichten-Bremse", farbe: "#6FA8FF", cls: "ohne" },
    { key: "mit_bremse", name: "Mit Bremse", kurz: "Ruhig, mit Nachrichten-Bremse", farbe: "#FFAE5E", cls: "mit" },
    { key: "mutig", name: "Mutig", kurz: "3 % Risiko pro Trade", farbe: "#C084FC", cls: "mutig" },
    { key: "btc_halten", name: "Bitcoin halten", kurz: "Vergleich: einfach kaufen und halten", farbe: "#AEB6C9", cls: "btc" }
  ];
  var KONTO = {};
  KONTEN.forEach(function (k) { KONTO[k.key] = k; });

  var URTEILE = {
    bewiesen: { cls: "gut", text: "Bewiesen – hat Geld gemacht" },
    nicht_bewiesen: { cls: "schlecht", text: "Nicht bewiesen – kein Gewinn" },
    zu_wenige_trades: { cls: "neutral", text: "Kein Urteil – zu wenige Trades" }
  };

  // ---------- kleine Bausteine ----------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]);
    return parent;
  }
  function svg(tag, attrs, text) {
    var e = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function punkt(cls) { return el("span", "punkt c-" + cls); }

  // ---------- Zahlen und Zeiten (deutsches Format) ----------
  var MINUS = "−";
  function zahl(n, stellen) {
    return Math.abs(n).toLocaleString("de-DE", { minimumFractionDigits: stellen, maximumFractionDigits: stellen });
  }
  function usd(n, stellen) {
    if (stellen === undefined) stellen = Math.abs(n) >= 1000 ? 0 : 2;
    return (n < 0 ? MINUS : "") + zahl(n, stellen) + " $";
  }
  function usdVz(n) { return (n > 0 ? "+" : "") + usd(n, Math.abs(n) >= 1000 ? 0 : 2); }
  function pct(n, stellen) {
    if (stellen === undefined) stellen = 1;
    var f = Math.pow(10, stellen);
    var g = Math.round(Math.abs(n) * f) / f;
    var vz = n < 0 && g !== 0 ? MINUS : (n > 0 && g !== 0 ? "+" : "");
    return vz + zahl(g, stellen) + " %";
  }
  function pctOhneVz(n) { return zahl(n, 1) + " %"; }
  function klasse(n) { return n > 0.0001 ? "gut" : (n < -0.0001 ? "schlecht" : ""); }

  function fmt(d, opts) { opts.timeZone = ZONE; return d.toLocaleString("de-DE", opts); }
  function uhrzeit(d) { return fmt(d, { hour: "2-digit", minute: "2-digit", hour12: false }); }
  function datumKurz(d) { return fmt(d, { day: "2-digit", month: "2-digit" }); }
  function datumLang(d) { return fmt(d, { day: "2-digit", month: "2-digit", year: "numeric" }); }
  function datumUhr(d) { return datumKurz(d) + ", " + uhrzeit(d); }
  function istHeute(d) { return datumLang(d) === datumLang(new Date()); }
  function dauerText(ms) {
    var h = Math.floor(ms / 3600000);
    if (h < 48) return h + (h === 1 ? " Stunde" : " Stunden");
    return Math.floor(h / 24) + " Tagen";
  }
  // Ende eines Zeitraums: genau Mitternacht heißt "ausgeschlossen" -> einen Tag zurück
  function endeAnzeige(iso) {
    var d = new Date(iso);
    if (d.getUTCHours() === 0 && d.getUTCMinutes() === 0 && d.getUTCSeconds() === 0) d = new Date(d.getTime() - 86400000);
    return d;
  }
  function jahre(von, bis) {
    var a = new Date(von).getUTCFullYear(), b = endeAnzeige(bis).getUTCFullYear();
    return a === b ? String(a) : a + "–" + String(b).slice(2);
  }

  // ---------- Laden ----------
  function holen(pfad) {
    return fetch(pfad + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .catch(function () { return null; });
  }
  function laden(datei) { return holen(ORDNER + datei); }
  function ladenRueckblick() {
    return laden("rueckblick.json").then(function (d) {
      return d || ORDNER === "daten/" ? d : holen("daten/rueckblick.json");
    });
  }

  // ---------- Fenster ----------
  function karte(bereich, titel, rechts) {
    var g = el("section", "glas " + bereich);
    if (titel) {
      var z = el("div", "kartenkopf");
      add(z, el("h2", null, titel));
      if (rechts) add(z, rechts);
      add(g, z);
    }
    return g;
  }
  function icon(art, farbe) {
    var s = svg("svg", { width: 22, height: 22, viewBox: "0 0 24 24", fill: "none", stroke: farbe,
      "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
    add(s, svg("circle", { cx: 12, cy: 12, r: 9 }));
    if (art === "ok") add(s, svg("path", { d: "M8 12.5l2.7 2.7L16 9.5" }));
    else add(s, svg("line", { x1: 12, y1: 7, x2: 12, y2: 13 }), svg("circle", { cx: 12, cy: 16.5, r: 0.6 }));
    return s;
  }
  function banner(cls, farbe, t1, t2) {
    var b = el("div", "banner " + cls);
    var t = el("div", "txt");
    add(t, el("b", null, t1));
    if (t2) add(t, el("span", null, t2));
    add(b, icon("warn", farbe), t);
    return b;
  }

  // ---------- Hilfen zum Zustand ----------
  function volleTage(z) { return typeof z.abgeschlossene_tage === "number" ? z.abgeschlossene_tage : z.tag - 1; }
  function hatUrteil(z) {
    var k = z.konten || {};
    return Object.keys(k).some(function (key) { return !!URTEILE[k[key].urteil]; });
  }
  function probeVorbei(z) { return volleTage(z) >= PROBE_TAGE || hatUrteil(z); }
  function letzterLauf(status, verlauf) {
    if (status && status.letzter_lauf) { var d = new Date(status.letzter_lauf); if (!isNaN(d)) return d; }
    if (verlauf && verlauf.length) return new Date(verlauf[verlauf.length - 1].zeit);
    return null;
  }
  function kontoDaten(z, key) { return key === "btc_halten" ? z.btc_halten : (z.konten || {})[key]; }

  // ---------- 1. Kopf ----------
  function kopf(z, status, verlauf) {
    var k = el("header", "kopf");
    var links = el("div", "kopf-links");
    add(links, el("h1", null, "Regel-Trader"), el("span", "untertitel", "Trendfolge · BTC & ETH · Spielgeld"));
    add(k, links);

    var rechts = el("div", "kopf-rechts");
    if (z && typeof z.tag === "number") {
      var tage = Math.min(volleTage(z), PROBE_TAGE);
      var fort = el("div", "fortschritt");
      add(fort, el("span", "fort-text", probeVorbei(z) ? "Bewährungsprobe vorbei" : "Tag " + z.tag + " von " + PROBE_TAGE));
      var bar = el("div", "bar");
      var fill = el("div", "bar-fill");
      fill.style.width = (tage / PROBE_TAGE * 100) + "%";
      add(bar, fill);
      add(fort, bar);
      add(rechts, fort);
    }
    if (z && z.bremse) add(rechts, bremsPille(z.bremse));
    var letzter = letzterLauf(status, verlauf);
    if (letzter) {
      var lauf = el("div", "lauf");
      add(lauf, el("span", "l", "Letzter Lauf"), el("b", null, istHeute(letzter) ? uhrzeit(letzter) + " Uhr" : datumUhr(letzter)));
      if (status && status.naechster_lauf_ca) {
        var n = new Date(status.naechster_lauf_ca);
        if (!isNaN(n)) add(lauf, el("span", "l", "nächster ca. " + uhrzeit(n)));
      }
      add(rechts, lauf);
    }
    add(k, rechts);
    return k;
  }

  function bremsPille(b) {
    var p = el("div", "bremse");
    var titel, text, cls;
    if (b.aktiv) {
      var bis = b.bis_ms ? new Date(b.bis_ms) : null;
      cls = "aktiv";
      titel = "Bremse aktiv" + (bis ? " bis " + (istHeute(bis) ? uhrzeit(bis) : datumUhr(bis)) : "");
      text = (b.grund || "") + " – keine neuen Käufe, Verkäufe laufen normal.";
    } else if (b.nachrichten_ok === false) {
      cls = "unklar"; titel = "Nachrichten nicht erreichbar"; text = "Der Trader handelt ohne Bremse, bis die Nachrichten wieder erreichbar sind.";
    } else {
      cls = "frei"; titel = "Bremse frei"; text = "Keine Schock-Meldung und kein Termin – das Konto mit Bremse darf kaufen.";
    }
    p.className = "bremse " + cls;
    p.title = text;
    add(p, el("span", "licht"), el("span", null, titel));
    return p;
  }

  function warnungen(status, verlauf) {
    var liste = [];
    var letzter = letzterLauf(status, verlauf);
    if (status && status.ok === false) {
      liste.push(banner("fehler", "#FFB4B4", "Der letzte Lauf ist fehlgeschlagen",
        (status.fehler || "Unbekannter Fehler") + " – gehandelt wurde dabei nicht."));
    }
    if (ALTER_PRUEFEN && letzter) {
      var alter = Date.now() - letzter.getTime();
      if (alter > VERALTET_STUNDEN * 3600000) {
        liste.push(banner("warn", "#FFC48A", "Seit " + dauerText(alter) + " kein Lauf mehr",
          "Letzter Lauf: " + datumUhr(letzter) + ". Die Zahlen sind nicht aktuell."));
      }
    }
    return liste;
  }

  // ---------- 2. Kennzahlen ----------
  function kennzahlen(z) {
    var reihe = el("section", "kpis");
    var eintraege = KONTEN.map(function (k) {
      var d = kontoDaten(z, k.key);
      return d ? { k: k, d: d, wert: Number(d.wert) } : null;
    }).filter(Boolean);
    // "vorne" nur, wenn ein Konto wirklich führt (mind. 1 $ vor dem Zweiten) – bei Gleichstand kein Schild
    var sortiert = eintraege.slice().sort(function (a, b) { return b.wert - a.wert; });
    var bester = sortiert.length > 1 && sortiert[0].wert - sortiert[1].wert >= 1 ? sortiert[0] : null;

    eintraege.forEach(function (e) {
      var k = e.k, d = e.d;
      var c = el("div", "kpi glas k-" + k.cls);
      var kopfz = el("div", "kpi-kopf");
      add(kopfz, punkt(k.cls), el("span", "kpi-name", k.name));
      if (bester && e === bester) add(kopfz, el("span", "vorne", "vorne"));
      add(c, kopfz);

      var p = (e.wert / START_KAPITAL - 1) * 100;
      if (d.pleite) add(c, el("div", "kpi-wert schlecht", "pleite"));
      else add(c, el("div", "kpi-wert " + klasse(Math.round(p * 10) / 10), pct(p)));
      add(c, el("div", "kpi-geld", usd(e.wert)));

      var fuss = el("div", "kpi-fuss");
      if (k.key === "btc_halten") {
        add(fuss, el("span", null, k.kurz));
      } else {
        var u = URTEILE[d.urteil];
        if (u) {
          add(fuss, el("span", "urteil " + u.cls, u.text));
        } else {
          var t = typeof d.abgeschlossene_trades === "number" ? d.abgeschlossene_trades : 0;
          var tz = el("div", "trades-zaehler");
          add(tz, el("span", null, "Trades " + t + " / " + MIN_TRADES));
          var mini = el("div", "mini");
          for (var i = 0; i < MIN_TRADES; i++) add(mini, el("i", i < t ? "an" : null));
          add(tz, mini);
          add(fuss, tz);
          var offen = Object.keys(d.positionen || {});
          add(fuss, el("span", "zustand", offen.length ? "im Markt: " + offen.join(", ") : "wartet auf Signal"));
        }
      }
      add(c, fuss);
      add(reihe, c);
    });
    return reihe;
  }

  // ---------- 3. Diagramm ----------
  function abschnittVerlauf(verlauf) {
    var legende = el("div", "legende");
    KONTEN.forEach(function (k) {
      var l = el("span", "leg");
      add(l, el("i", "strich s-" + k.cls), el("span", null, k.name));
      add(legende, l);
    });
    var g = karte("verlauf", "Kontoverlauf seit Start (in %)", legende);
    var flaeche = el("div", "chart-flaeche");
    flaeche._verlauf = verlauf || [];
    add(g, flaeche);
    return g;
  }

  function schritt(spanne) {
    var roh = spanne / 4, basis = Math.pow(10, Math.floor(Math.log10(roh)));
    var r = roh / basis;
    return (r < 1.5 ? 1 : r < 3.5 ? 2 : r < 7.5 ? 5 : 10) * basis;
  }

  function zeichneDiagramm(flaeche) {
    var verlauf = flaeche._verlauf;
    while (flaeche.firstChild) flaeche.removeChild(flaeche.firstChild);
    var W = Math.max(flaeche.clientWidth, 280), H = Math.max(flaeche.clientHeight, 180);
    var L = 46, R = 12, T = 10, B = 24;
    var s = svg("svg", { "class": "chart", width: W, height: H, viewBox: "0 0 " + W + " " + H,
      role: "img", "aria-label": "Verlauf der Konten in Prozent seit Start" });

    var punkte = verlauf.filter(function (p) { return typeof p.zeit === "number"; });
    function prozent(v) { return (v / START_KAPITAL - 1) * 100; }
    var lo = 0, hi = 0;
    punkte.forEach(function (p) {
      KONTEN.forEach(function (k) { if (typeof p[k.key] === "number") { var v = prozent(p[k.key]); lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    });
    if (hi - lo < 2) { var mitte = (hi + lo) / 2; lo = mitte - 1; hi = mitte + 1; }
    var st = schritt(hi - lo);
    lo = Math.floor(lo / st) * st; hi = Math.ceil(hi / st) * st;

    var t0 = punkte.length ? punkte[0].zeit : 0, t1 = punkte.length ? punkte[punkte.length - 1].zeit : 1;
    function x(t) { return punkte.length < 2 || t1 === t0 ? L + (W - L - R) / 2 : L + (t - t0) / (t1 - t0) * (W - L - R); }
    function y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }

    // waagrechte Linien mit Prozent-Beschriftung
    for (var v = lo; v <= hi + st / 2; v += st) {
      var gy = y(v).toFixed(1), null0 = Math.abs(v) < st / 1000;
      add(s, svg("line", { x1: L, y1: gy, x2: W - R, y2: gy, "class": null0 ? "achse-null" : "gitter" }));
      add(s, svg("text", { x: L - 8, y: Number(gy) + 4, "text-anchor": "end", "class": "achse-text" }, pct(null0 ? 0 : v, st < 1 ? 1 : 0)));
    }
    // Datums-Beschriftung unten
    if (punkte.length > 1) {
      var n = Math.min(6, Math.max(2, Math.floor((W - L - R) / 110)));
      for (var i = 0; i < n; i++) {
        var t = t0 + (t1 - t0) * i / (n - 1);
        var anker = i === 0 ? "start" : (i === n - 1 ? "end" : "middle");
        add(s, svg("text", { x: x(t).toFixed(1), y: H - 6, "text-anchor": anker, "class": "achse-text" }, datumKurz(new Date(t))));
      }
    }

    // Linien: Bitcoin zuerst (hinten), Konten darüber
    [KONTEN[3], KONTEN[2], KONTEN[0], KONTEN[1]].forEach(function (k) {
      var pts = punkte.filter(function (p) { return typeof p[k.key] === "number"; });
      if (!pts.length) return;
      if (pts.length > 1) {
        var d = pts.map(function (p, j) { return (j ? "L" : "M") + x(p.zeit).toFixed(1) + " " + y(prozent(p[k.key])).toFixed(1); }).join(" ");
        add(s, svg("path", { d: d, "class": "linie l-" + k.cls }));
      }
      var last = pts[pts.length - 1];
      add(s, svg("circle", { cx: x(last.zeit).toFixed(1), cy: y(prozent(last[k.key])).toFixed(1), r: 3.5, fill: k.farbe }));
    });
    add(flaeche, s);
    if (punkte.length < 2) add(flaeche, el("div", "chart-hinweis", "Die Kurve entsteht mit den nächsten Läufen (alle 4 Stunden)."));
  }

  // ---------- 4. Offene Positionen ----------
  function abschnittPositionen(z) {
    var g = karte("positionen", "Offene Positionen");
    var liste = el("div", "liste");
    var preise = z.preise || {};
    var n = 0;
    ["ohne_bremse", "mit_bremse", "mutig"].forEach(function (key) {
      var konto = (z.konten || {})[key];
      if (!konto) return;
      Object.keys(konto.positionen || {}).forEach(function (coin) {
        n++;
        var pos = konto.positionen[coin];
        var kurs = Number(preise[coin]);
        var p = (kurs / pos.einstieg - 1) * 100;
        var row = el("div", "pos");
        var oben = el("div", "pos-oben");
        var name = el("span", "pos-name");
        add(name, punkt(KONTO[key].cls), el("b", null, coin), el("span", "dim", KONTO[key].name + (pos.geliehen > 0 ? " · Hebel" : "")));
        add(oben, name, el("span", "pos-pct " + klasse(p), pct(p)));
        add(row, oben);

        var lo = pos.stop;
        var hi = Math.max(kurs, pos.hoechster_schluss || 0, pos.einstieg) + Math.max(pos.einstieg - pos.stop, 0) * 0.5;
        if (hi <= lo) hi = lo + 1;
        function f(v) { return Math.max(0, Math.min(1, (v - lo) / (hi - lo))) * 100; }
        var leiste = el("div", "leiste");
        var ein = el("i", "einstieg"); ein.style.left = f(pos.einstieg) + "%";
        var marke = el("i", "marke"); marke.style.left = f(kurs) + "%";
        add(leiste, ein, marke);
        add(row, leiste);

        var unten = el("div", "pos-unten");
        add(unten, el("span", null, "Limit " + usd(pos.stop)), el("span", null, "Einstieg " + usd(pos.einstieg)), el("span", null, "jetzt " + usd(kurs)));
        add(row, unten);
        add(liste, row);
      });
      Object.keys(konto.vorgemerkt || {}).forEach(function (coin) {
        n++;
        var o = konto.vorgemerkt[coin];
        var row = el("div", "pos vorm");
        var name = el("span", "pos-name");
        add(name, punkt(KONTO[key].cls), el("b", null, coin), el("span", "dim", KONTO[key].name));
        add(row, name, el("div", "dim", (o.art === "verkauf" ? "Verkauf" : "Kauf") + " vorgemerkt zum nächsten Kurs"));
        if (o.grund) row.title = o.grund;
        add(liste, row);
      });
    });
    if (!n) add(liste, el("div", "leer", "Kein Konto ist gerade im Markt. Gekauft wird erst bei einem Ausbruch im Aufwärtstrend."));
    add(g, liste);
    return g;
  }

  // ---------- 5. Letzte Trades ----------
  function abschnittTrades(trades) {
    var alle = (trades || []).slice().sort(function (a, b) { return b.verkauf_zeit - a.verkauf_zeit; });
    var g = karte("trades", "Letzte Trades", alle.length ? el("span", "dim", alle.length + " abgeschlossen") : null);
    var liste = el("div", "liste");
    if (!alle.length) {
      add(liste, el("div", "leer", "Noch kein Trade abgeschlossen."));
    }
    alle.slice(0, 30).forEach(function (t) {
      var row = el("div", "trade");
      var k = KONTO[t.konto] || KONTO.btc_halten;
      var links = el("div", "trade-l");
      var z1 = el("div", "trade-z1");
      add(z1, punkt(k.cls), el("b", null, t.coin), el("span", "dim", k.name));
      add(links, z1, el("div", "dim klein", datumUhr(new Date(t.verkauf_zeit)) + (t.grund_verkauf ? " · " + t.grund_verkauf : "")));
      var rechts = el("div", "trade-r");
      var cls = klasse(t.ergebnis_usd);
      add(rechts, el("b", cls, usdVz(t.ergebnis_usd)), el("span", cls + " klein", pct(t.ergebnis_pct, 1)));
      add(row, links, rechts);
      if (t.grund_kauf) row.title = "Kauf: " + t.grund_kauf + (t.grund_verkauf ? "\nVerkauf: " + t.grund_verkauf : "");
      add(liste, row);
    });
    add(g, liste);
    return g;
  }

  // ---------- 6. Rückblick-Test ----------
  var STRATEGIEN = [
    { key: "ruhig", name: "Ruhig (1 % Risiko)" },
    { key: "mutig", name: "Mutig (3 % Risiko)" },
    { key: "mutig_hebel", name: "Mutig + Hebel" },
    { key: "btc_halten", name: "Bitcoin halten" },
    { key: "halten_50_50", name: "50/50 BTC + ETH halten" }
  ];
  var STUFE_KEY = { "Ruhig": "ruhig", "Mutig": "mutig", "Mutig + Hebel": "mutig_hebel" };
  var LIVE_KONTEN = { ruhig: "Ohne Bremse, Mit Bremse", mutig: "Mutig", mutig_hebel: "Mutig" };

  function abschnittRueckblick(rb) {
    var kal = rb.kalibrierung || {}, pr = rb.pruefung || {};
    var d = new Date(rb.stand);
    var g = karte("rueckblick", "Rückblick-Test: so hätten die Regeln abgeschnitten",
      el("span", "dim", isNaN(d) ? "" : "eingefroren am " + datumLang(d)));
    var gewaehlt = STUFE_KEY[rb.mutig_stufe];
    var jk = kal.von && kal.bis ? jahre(kal.von, kal.bis) : "Kalibrierung";
    var jp = pr.von && pr.bis ? jahre(pr.von, pr.bis) : "Prüfung";

    var tab = el("table", "rb-tabelle");
    var thead = el("thead");
    var r1 = el("tr");
    add(r1, el("th", "links", ""), th2("Festgelegt " + jk, 2, "gruppe kal"), th2("Geprüft " + jp, 2, "gruppe haupt"),
      th2("Trades", 1), th2("Treffer", 1), th2("bester Trade", 1, "opt"));
    var r2 = el("tr", "unter");
    add(r2, el("th", "links", "Strategie"), el("th", "kal", "Rendite"), el("th", "kal", "tiefster Absturz"),
      el("th", "haupt", "Rendite"), el("th", "haupt", "tiefster Absturz"), el("th"), el("th"), el("th", "opt"));
    add(thead, r1, r2);
    add(tab, thead);

    var tbody = el("tbody");
    STRATEGIEN.forEach(function (s) {
      var a = kal[s.key], b = pr[s.key];
      if (!a && !b) return;
      var halten = s.key === "btc_halten" || s.key === "halten_50_50";
      var live = s.key === "ruhig" || s.key === gewaehlt;
      var tr = el("tr", (halten ? "halten" : "") + (live ? " live" : ""));
      var name = el("td", "links");
      add(name, el("span", null, s.name));
      if (live) add(name, el("span", "tag", "läuft live"));
      add(tr, name,
        zelle(a ? pct(a.rendite_pct) : "–", "kal " + (a ? klasse(a.rendite_pct) : "")),
        zelle(a ? MINUS + pctOhneVz(a.tiefster_absturz_pct) : "–", "kal dim"),
        zelle(b ? pct(b.rendite_pct) : "–", "haupt " + (b ? klasse(b.rendite_pct) : "")),
        zelle(b ? MINUS + pctOhneVz(b.tiefster_absturz_pct) : "–", "haupt dim"),
        zelle(!halten && b && typeof b.trades === "number" ? String(b.trades) : "–", "dim"),
        zelle(!halten && b && typeof b.trefferquote_pct === "number" ? pctOhneVz(b.trefferquote_pct) : "–", "dim"),
        zelle(!halten && b && typeof b.groesster_trade_pct === "number" ? pct(b.groesster_trade_pct) : "–", "opt dim"));
      add(tbody, tr);
    });
    add(tab, tbody);
    var rahmen = el("div", "tabelle-rahmen");
    add(rahmen, tab);
    add(g, rahmen);

    var hinweis = el("p", "fussnote");
    add(hinweis, el("b", null, "Geprüft"), document.createTextNode(" = Jahre, die die Regeln nie gesehen haben (die zählen). "),
      el("b", null, "Tiefster Absturz"), document.createTextNode(" = größter Rückgang vom Höchststand."));
    var lebende = [pr.ruhig, pr[gewaehlt]];
    if (pr.btc_halten && lebende.every(function (m) { return m && m.rendite_pct < pr.btc_halten.rendite_pct; })) {
      add(hinweis, document.createTextNode(" Im Prüfzeitraum war einfach Halten besser – die Bewährungsprobe läuft trotzdem."));
    }
    if (rb.parameter && rb.parameter.beschreibung) hinweis.title = "Regeln: " + rb.parameter.beschreibung;
    add(g, hinweis);
    return g;
  }
  function th2(text, span, cls) { var t = el("th", cls || null, text); if (span > 1) t.colSpan = span; return t; }
  function zelle(text, cls) { return el("td", cls || null, text); }

  // ---------- Urteil (nur Handy; am PC steht es in den Kennzahlen) ----------
  function abschnittUrteil(z) {
    if (!hatUrteil(z)) return null;
    var g = karte("urteil-karte", "Urteil nach " + PROBE_TAGE + " Tagen");
    ["ohne_bremse", "mit_bremse", "mutig"].forEach(function (key) {
      var k = (z.konten || {})[key];
      if (!k || !URTEILE[k.urteil]) return;
      var u = URTEILE[k.urteil];
      var row = el("div", "urteil-zeile");
      add(row, punkt(KONTO[key].cls), el("b", null, KONTO[key].name), el("span", "urteil " + u.cls, u.text));
      add(g, row);
    });
    add(g, el("p", "fussnote", "Bewiesen heißt: Kontostand nach allen Gebühren über " + usd(START_KAPITAL, 0) + " und mindestens " + MIN_TRADES + " abgeschlossene Trades."));
    return g;
  }

  // ---------- Seite bauen ----------
  function bauen(daten) {
    var app = document.getElementById("app");
    var neu = document.createDocumentFragment();
    var z = daten.zustand;

    var oben = el("div", "oben");
    add(oben, kopf(z, daten.status, daten.verlauf));
    warnungen(daten.status, daten.verlauf).forEach(function (w) { add(oben, w); });
    add(neu, oben);

    if (z) {
      add(neu, kennzahlen(z));
      add(neu, abschnittVerlauf(daten.verlauf));
      add(neu, abschnittPositionen(z));
      add(neu, abschnittTrades(daten.trades));
    } else {
      var g = karte("start", "Der Trader startet beim nächsten Lauf.");
      add(g, el("p", "fussnote", "Sobald der erste Lauf fertig ist, erscheinen hier die Konten, der Vergleich mit Bitcoin und die Trades."));
      add(neu, g);
    }
    if (daten.rueckblick) add(neu, abschnittRueckblick(daten.rueckblick));
    if (z) add(neu, abschnittUrteil(z));
    add(neu, el("footer", "fuss", BEISPIEL ? "Beispieldaten – nur zum Ansehen" : "Spielgeld, kein echtes Geld · Werte nach allen Gebühren · lädt alle 5 Minuten neu"));

    while (app.firstChild) app.removeChild(app.firstChild);
    app.appendChild(neu);
    diagrammeZeichnen();
  }

  function diagrammeZeichnen() {
    var f = document.querySelector(".chart-flaeche");
    if (f) zeichneDiagramm(f);
  }
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(diagrammeZeichnen, 120);
  });

  function alles() {
    return Promise.all([laden("zustand.json"), laden("verlauf.json"), laden("trades.json"), laden("status.json"), ladenRueckblick()])
      .then(function (r) { bauen({ zustand: r[0], verlauf: r[1], trades: r[2], status: r[3], rueckblick: r[4] }); })
      .catch(function (e) {
        document.getElementById("app").textContent = "Die Seite konnte nicht aufgebaut werden. Bitte später noch einmal laden.";
        if (window.console) console.error(e);
      });
  }

  alles();
  setInterval(alles, NEU_LADEN_MS);
})();
