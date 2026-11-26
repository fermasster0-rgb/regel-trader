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
    { key: "ohne_bremse", name: "Ohne Bremse", kurz: "Ruhig · 1 % Risiko", farbe: "#4C9BFF", cls: "ohne", icon: "trend" },
    { key: "mit_bremse", name: "Mit Bremse", kurz: "Ruhig · Nachrichten-Bremse", farbe: "#FFA654", cls: "mit", icon: "schild" },
    { key: "mutig", name: "Mutig", kurz: "3 % Risiko", farbe: "#B57BFF", cls: "mutig", icon: "blitz" },
    { key: "btc_halten", name: "Bitcoin halten", kurz: "Vergleich: kaufen und halten", farbe: "#A0AEC0", cls: "btc", icon: "btc" }
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

  var ICON_PFADE = {
    trend: ["M3 17l6-6 4 4 8-8", "M15 7h6v6"],
    schild: ["M12 3l7 3v5.5c0 4.6-3 7.7-7 9.5-4-1.8-7-4.9-7-9.5V6z", "M9 12l2 2 4-4"],
    blitz: ["M13 2L4.5 13.5H11L10 22l8.5-11.5H12z"],
    uhr: ["M12 7v5l3 2"],
    liste: ["M8 6h12", "M8 12h12", "M8 18h12", "M4 6h.01", "M4 12h.01", "M4 18h.01"],
    tausch: ["M7 7h11l-3-3", "M17 17H6l3 3"]
  };
  function icon(name, groesse) {
    var s = svg("svg", { width: groesse || 18, height: groesse || 18, viewBox: "0 0 24 24", fill: "none", stroke: "#fff",
      "stroke-width": 2.2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
    if (name === "btc") {
      add(s, svg("text", { x: 12, y: 17, "text-anchor": "middle", fill: "#fff", stroke: "none",
        "font-size": 15, "font-weight": 800, "font-family": "Plus Jakarta Sans, sans-serif" }, "₿"));
      return s;
    }
    if (name === "uhr") add(s, svg("circle", { cx: 12, cy: 12, r: 9 }));
    (ICON_PFADE[name] || []).forEach(function (d) { add(s, svg("path", { d: d })); });
    return s;
  }

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
  function wann(d) { return istHeute(d) ? uhrzeit(d) + " Uhr" : datumUhr(d); }
  function dauerText(ms) {
    var h = Math.floor(ms / 3600000);
    if (h < 48) return h + (h === 1 ? " Stunde" : " Stunden");
    return Math.floor(h / 24) + " Tagen";
  }
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

  // ---------- Karten ----------
  function karte(bereich, titel, unter, rechts) {
    var g = el("section", "karte " + bereich);
    if (titel) {
      var z = el("div", "kartenkopf");
      var t = el("div", "kartentitel");
      add(t, el("h2", null, titel));
      if (unter) add(t, unter);
      add(z, t);
      if (rechts) add(z, rechts);
      add(g, z);
    }
    return g;
  }
  function unterzeile(text, cls) { return el("div", "unterzeile" + (cls ? " " + cls : ""), text); }
  function banner(cls, t1, t2) {
    var b = el("div", "banner " + cls);
    add(b, el("b", null, t1));
    if (t2) add(b, el("span", null, t2));
    return b;
  }

  // ---------- Zustand ----------
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

  // ---------- Kopf ----------
  function kopf(status, verlauf) {
    var k = el("header", "kopf");
    var links = el("div", "kopf-links");
    add(links, el("div", "pfad", "Spielgeld / Dashboard"), el("h1", null, "Regel-Trader"));
    add(k, links);
    var letzter = letzterLauf(status, verlauf);
    var rechts = el("div", "kopf-rechts");
    add(rechts, el("span", null, "Trendfolge · BTC & ETH"));
    if (letzter) add(rechts, el("span", "kopf-lauf", "aktualisiert " + wann(letzter)));
    add(k, rechts);
    return k;
  }
  function warnungen(status, verlauf) {
    var liste = [];
    var letzter = letzterLauf(status, verlauf);
    if (status && status.ok === false) {
      liste.push(banner("fehler", "Der letzte Lauf ist fehlgeschlagen.", (status.fehler || "Unbekannter Fehler") + " – gehandelt wurde dabei nicht."));
    }
    if (ALTER_PRUEFEN && letzter) {
      var alter = Date.now() - letzter.getTime();
      if (alter > VERALTET_STUNDEN * 3600000) {
        liste.push(banner("warn", "Seit " + dauerText(alter) + " kein Lauf mehr.", "Letzter Lauf: " + datumUhr(letzter) + " – die Zahlen sind nicht aktuell."));
      }
    }
    return liste;
  }

  // ---------- Kennzahlen ----------
  function kennzahlen(z) {
    var reihe = el("section", "kpis");
    var eintraege = KONTEN.map(function (k) {
      var d = kontoDaten(z, k.key);
      return d ? { k: k, d: d, wert: Number(d.wert) } : null;
    }).filter(Boolean);
    var sortiert = eintraege.slice().sort(function (a, b) { return b.wert - a.wert; });
    var bester = sortiert.length > 1 && sortiert[0].wert - sortiert[1].wert >= 1 ? sortiert[0] : null;

    eintraege.forEach(function (e) {
      var k = e.k, d = e.d;
      var c = el("div", "karte kpi");
      var text = el("div", "kpi-text");
      var name = el("div", "kpi-name", k.name);
      if (bester && e === bester) add(name, el("span", "vorne", "führt"));
      add(text, name);
      var zeile = el("div", "kpi-zeile");
      var p = (e.wert / START_KAPITAL - 1) * 100;
      if (d.pleite) {
        add(zeile, el("span", "kpi-wert", usd(e.wert)), el("span", "kpi-pct schlecht", "pleite"));
      } else {
        add(zeile, el("span", "kpi-wert", usd(e.wert)), el("span", "kpi-pct " + klasse(Math.round(p * 10) / 10), pct(p)));
      }
      add(text, zeile);

      var fuss = el("div", "kpi-fuss");
      if (k.key === "btc_halten") {
        add(fuss, el("span", null, k.kurz));
      } else {
        var u = URTEILE[d.urteil];
        if (u) {
          add(fuss, el("span", "urteil " + u.cls, u.text));
        } else {
          var t = typeof d.abgeschlossene_trades === "number" ? d.abgeschlossene_trades : 0;
          var offen = Object.keys(d.positionen || {});
          add(fuss, el("span", null, "Trades " + t + "/" + MIN_TRADES), el("span", "trenner", "·"),
            el("span", offen.length ? "im-markt" : null, offen.length ? "im Markt: " + offen.join(", ") : "wartet auf Signal"));
        }
      }
      add(text, fuss);
      var kachel = el("div", "kpi-icon i-" + k.cls);
      add(kachel, icon(k.icon, 20));
      add(c, text, kachel);
      add(reihe, c);
    });
    return reihe;
  }

  // ---------- Status: Bewährungsprobe als Ring ----------
  function statusKarte(z, status) {
    var vorbei = probeVorbei(z);
    var g = karte("status", "Bewährungsprobe", unterzeile(vorbei ? "56 Tage vorbei – Urteil steht" : "Urteil nach 56 vollen Tagen"));
    var inhalt = el("div", "status-inhalt");

    var spalte = el("div", "status-spalte");
    var b = z.bremse || {};
    var bremse = el("div", "infobox");
    add(bremse, el("span", "l", "Nachrichten-Bremse"));
    var bw = el("b", "bremse " + (b.aktiv ? "aktiv" : (b.nachrichten_ok === false ? "unklar" : "frei")));
    add(bw, el("i"), document.createTextNode(b.aktiv ? "aktiv" + (b.bis_ms ? " bis " + wann(new Date(b.bis_ms)) : "")
      : (b.nachrichten_ok === false ? "Nachrichten aus" : "frei")));
    add(bremse, bw);
    bremse.title = b.aktiv ? (b.grund || "") + " – keine neuen Käufe, Verkäufe laufen normal."
      : "Keine Schock-Meldung und kein Termin – das Konto mit Bremse darf kaufen.";
    var naechster = el("div", "infobox");
    add(naechster, el("span", "l", "Nächster Lauf"));
    var n = status && status.naechster_lauf_ca ? new Date(status.naechster_lauf_ca) : null;
    add(naechster, el("b", null, n && !isNaN(n) ? "ca. " + wann(n) : "alle 4 Stunden"));
    add(spalte, bremse, naechster);

    var tage = Math.max(0, Math.min(volleTage(z), PROBE_TAGE));
    var ring = el("div", "ring");
    var R = 54, U = 2 * Math.PI * R;
    var s = svg("svg", { viewBox: "0 0 140 140", "class": "ring-svg", role: "img",
      "aria-label": "Tag " + z.tag + " von " + PROBE_TAGE });
    var defs = svg("defs");
    var lg = svg("linearGradient", { id: "ringfarbe", x1: "0", y1: "0", x2: "1", y2: "1" });
    add(lg, svg("stop", { offset: "0", "stop-color": "#05CD99" }), svg("stop", { offset: "1", "stop-color": "#0075FF" }));
    add(defs, lg);
    add(s, defs,
      svg("circle", { cx: 70, cy: 70, r: R, fill: "none", stroke: "rgba(255,255,255,.08)", "stroke-width": 10 }),
      svg("circle", { cx: 70, cy: 70, r: R, fill: "none", stroke: "url(#ringfarbe)", "stroke-width": 10, "stroke-linecap": "round",
        "stroke-dasharray": Math.max(tage / PROBE_TAGE * U, 0.01).toFixed(1) + " " + U.toFixed(1), transform: "rotate(-90 70 70)" }));
    add(ring, s);
    var mitte = el("div", "ring-mitte");
    add(mitte, el("span", "l", "Tag"), el("b", null, vorbei ? String(PROBE_TAGE) : String(z.tag)), el("span", "l", "von " + PROBE_TAGE));
    add(ring, mitte);
    add(inhalt, spalte, ring);
    add(g, inhalt);
    return g;
  }

  // ---------- Verlauf ----------
  function abschnittVerlauf(verlauf) {
    var legende = el("div", "legende");
    KONTEN.forEach(function (k) {
      var l = el("span", "leg");
      add(l, el("i", "strich s-" + k.cls), el("span", null, k.name));
      add(legende, l);
    });
    var g = karte("verlauf", "Kontoverlauf", unterzeile("Veränderung seit Start in Prozent, nach allen Gebühren"), legende);
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
  // monotone Kurve (keine Überschwinger) durch die Punkte
  function glatt(p) {
    if (p.length < 3) return p.map(function (q, i) { return (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1); }).join(" ");
    var n = p.length, dx = [], m = [], t = [], i;
    for (i = 0; i < n - 1; i++) { dx[i] = p[i + 1][0] - p[i][0]; m[i] = dx[i] ? (p[i + 1][1] - p[i][1]) / dx[i] : 0; }
    t[0] = m[0]; t[n - 1] = m[n - 2];
    for (i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
    for (i = 0; i < n - 1; i++) {
      if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
      var a = t[i] / m[i], b = t[i + 1] / m[i], s2 = a * a + b * b;
      if (s2 > 9) { var tau = 3 / Math.sqrt(s2); t[i] = tau * a * m[i]; t[i + 1] = tau * b * m[i]; }
    }
    var d = "M" + p[0][0].toFixed(1) + " " + p[0][1].toFixed(1);
    for (i = 0; i < n - 1; i++) {
      d += " C" + (p[i][0] + dx[i] / 3).toFixed(1) + " " + (p[i][1] + t[i] * dx[i] / 3).toFixed(1) + " " +
        (p[i + 1][0] - dx[i] / 3).toFixed(1) + " " + (p[i + 1][1] - t[i + 1] * dx[i] / 3).toFixed(1) + " " +
        p[i + 1][0].toFixed(1) + " " + p[i + 1][1].toFixed(1);
    }
    return d;
  }

  function zeichneDiagramm(flaeche) {
    var verlauf = flaeche._verlauf;
    while (flaeche.firstChild) flaeche.removeChild(flaeche.firstChild);
    var W = Math.max(flaeche.clientWidth, 280), H = Math.max(flaeche.clientHeight, 160);
    var L = 46, R = 10, T = 8, B = 24;
    var s = svg("svg", { "class": "chart", width: W, height: H, viewBox: "0 0 " + W + " " + H,
      role: "img", "aria-label": "Verlauf der Konten in Prozent seit Start" });
    var defs = svg("defs");
    KONTEN.forEach(function (k) {
      var lg = svg("linearGradient", { id: "fl-" + k.cls, x1: "0", y1: "0", x2: "0", y2: "1" });
      add(lg, svg("stop", { offset: "0", "stop-color": k.farbe, "stop-opacity": k.key === "btc_halten" ? 0 : 0.28 }),
        svg("stop", { offset: "1", "stop-color": k.farbe, "stop-opacity": 0 }));
      add(defs, lg);
    });
    add(s, defs);

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

    for (var v = lo; v <= hi + st / 2; v += st) {
      var gy = y(v).toFixed(1), null0 = Math.abs(v) < st / 1000;
      add(s, svg("line", { x1: L, y1: gy, x2: W - R, y2: gy, "class": null0 ? "achse-null" : "gitter" }));
      add(s, svg("text", { x: L - 10, y: Number(gy) + 4, "text-anchor": "end", "class": "achse-text" }, pct(null0 ? 0 : v, st < 1 ? 1 : 0)));
    }
    if (punkte.length > 1) {
      var n = Math.min(7, Math.max(2, Math.floor((W - L - R) / 100)));
      for (var i = 0; i < n; i++) {
        var t = t0 + (t1 - t0) * i / (n - 1);
        add(s, svg("text", { x: x(t).toFixed(1), y: H - 6, "text-anchor": i === 0 ? "start" : (i === n - 1 ? "end" : "middle"),
          "class": "achse-text" }, datumKurz(new Date(t))));
      }
    }

    var unten = y(lo);
    [KONTEN[3], KONTEN[2], KONTEN[0], KONTEN[1]].forEach(function (k) {
      var pts = punkte.filter(function (p) { return typeof p[k.key] === "number"; })
        .map(function (p) { return [x(p.zeit), y(prozent(p[k.key]))]; });
      if (!pts.length) return;
      if (pts.length > 1) {
        var d = glatt(pts);
        if (k.key !== "btc_halten") {
          add(s, svg("path", { d: d + " L" + pts[pts.length - 1][0].toFixed(1) + " " + unten.toFixed(1) +
            " L" + pts[0][0].toFixed(1) + " " + unten.toFixed(1) + " Z", fill: "url(#fl-" + k.cls + ")" }));
        }
        add(s, svg("path", { d: d, "class": "linie l-" + k.cls }));
      }
      var last = pts[pts.length - 1];
      add(s, svg("circle", { cx: last[0].toFixed(1), cy: last[1].toFixed(1), r: 4, fill: k.farbe, stroke: "#0B1437", "stroke-width": 2 }));
    });
    add(flaeche, s);
    if (punkte.length < 2) add(flaeche, el("div", "chart-hinweis", "Die Kurve entsteht mit den nächsten Läufen – alle 4 Stunden kommt ein Punkt dazu."));
  }

  // ---------- Offene Positionen ----------
  function abschnittPositionen(z) {
    var preise = z.preise || {};
    var eintraege = [];
    ["ohne_bremse", "mit_bremse", "mutig"].forEach(function (key) {
      var konto = (z.konten || {})[key];
      if (!konto) return;
      Object.keys(konto.positionen || {}).forEach(function (coin) { eintraege.push({ art: "pos", key: key, coin: coin, pos: konto.positionen[coin] }); });
      Object.keys(konto.vorgemerkt || {}).forEach(function (coin) { eintraege.push({ art: "vorm", key: key, coin: coin, o: konto.vorgemerkt[coin] }); });
    });
    var g = karte("positionen", "Offene Positionen",
      unterzeile(eintraege.length ? eintraege.length + (eintraege.length === 1 ? " Eintrag" : " Einträge") : "gerade nichts im Markt"));
    var liste = el("div", "liste");
    eintraege.forEach(function (e) {
      var k = KONTO[e.key];
      if (e.art === "vorm") {
        var v = el("div", "pos vorm");
        var kopfz = el("div", "pos-oben");
        var nm = el("span", "pos-name");
        add(nm, punkt(k.cls), el("b", null, e.coin), el("span", "dim", k.name));
        add(kopfz, nm, el("span", "dim klein", (e.o.art === "verkauf" ? "Verkauf" : "Kauf") + " vorgemerkt"));
        add(v, kopfz);
        if (e.o.grund) v.title = e.o.grund;
        add(liste, v);
        return;
      }
      var pos = e.pos, kurs = Number(preise[e.coin]);
      var p = (kurs / pos.einstieg - 1) * 100;
      var row = el("div", "pos");
      var oben = el("div", "pos-oben");
      var name = el("span", "pos-name");
      add(name, punkt(k.cls), el("b", null, e.coin), el("span", "dim", k.name + (pos.geliehen > 0 ? " · Hebel" : "")));
      add(oben, name, el("b", klasse(p), pct(p)));
      add(row, oben);
      var lo = pos.stop;
      var hi = Math.max(kurs, pos.hoechster_schluss || 0, pos.einstieg) + Math.max(pos.einstieg - pos.stop, 0) * 0.5;
      if (hi <= lo) hi = lo + 1;
      function f(v) { return Math.max(0, Math.min(1, (v - lo) / (hi - lo))) * 100; }
      var leiste = el("div", "leiste");
      var fuell = el("i", "fuell"); fuell.style.width = f(kurs) + "%";
      var ein = el("i", "einstieg"); ein.style.left = f(pos.einstieg) + "%";
      add(leiste, fuell, ein);
      add(row, leiste);
      var unten = el("div", "pos-unten");
      add(unten, el("span", null, "Limit " + usd(pos.stop)), el("span", null, "Einstieg " + usd(pos.einstieg)), el("span", null, "jetzt " + usd(kurs)));
      add(row, unten);
      add(liste, row);
    });
    if (!eintraege.length) {
      var leer = el("div", "leer");
      add(leer, icon("uhr", 28), el("span", null, "Kein Konto ist gerade im Markt. Gekauft wird erst, wenn BTC oder ETH im Aufwärtstrend über das Hoch der letzten ~7 Tage ausbricht."));
      add(liste, leer);
    }
    add(g, liste);
    return g;
  }

  // ---------- Letzte Trades ----------
  function abschnittTrades(trades) {
    var alle = (trades || []).slice().sort(function (a, b) { return b.verkauf_zeit - a.verkauf_zeit; });
    var gewinner = alle.filter(function (t) { return t.ergebnis_usd > 0; }).length;
    var g = karte("trades", "Letzte Trades",
      unterzeile(alle.length ? alle.length + " abgeschlossen · " + gewinner + " im Plus" : "noch keiner abgeschlossen", alle.length ? null : ""));
    var liste = el("div", "liste zeitleiste");
    if (!alle.length) {
      var leer = el("div", "leer");
      add(leer, icon("tausch", 28), el("span", null, "Sobald ein Konto eine Position verkauft, steht der Trade hier – mit Gewinn oder Verlust und dem Grund."));
      add(liste, leer);
    }
    alle.slice(0, 40).forEach(function (t) {
      var k = KONTO[t.konto] || KONTO.btc_halten;
      var row = el("div", "trade");
      add(row, el("span", "knoten c-" + k.cls));
      var mitte = el("div", "trade-l");
      var z1 = el("div", "trade-z1");
      add(z1, el("b", null, t.coin + " · " + k.name));
      add(mitte, z1, el("div", "dim klein", datumUhr(new Date(t.verkauf_zeit)) + (t.grund_verkauf ? " · " + t.grund_verkauf : "")));
      var rechts = el("div", "trade-r");
      var cls = klasse(t.ergebnis_usd);
      add(rechts, el("b", cls, usdVz(t.ergebnis_usd)), el("span", cls + " klein", pct(t.ergebnis_pct, 1)));
      add(row, mitte, rechts);
      if (t.grund_kauf) row.title = "Kauf: " + t.grund_kauf + (t.grund_verkauf ? "\nVerkauf: " + t.grund_verkauf : "");
      add(liste, row);
    });
    add(g, liste);
    return g;
  }

  // ---------- Rückblick-Test ----------
  var STRATEGIEN = [
    { key: "ruhig", name: "Ruhig · 1 % Risiko" },
    { key: "mutig", name: "Mutig · 3 % Risiko" },
    { key: "mutig_hebel", name: "Mutig + Hebel" },
    { key: "btc_halten", name: "Bitcoin halten" },
    { key: "halten_50_50", name: "50/50 BTC + ETH halten" }
  ];
  var STUFE_KEY = { "Ruhig": "ruhig", "Mutig": "mutig", "Mutig + Hebel": "mutig_hebel" };

  function abschnittRueckblick(rb) {
    var kal = rb.kalibrierung || {}, pr = rb.pruefung || {};
    var d = new Date(rb.stand);
    var gewaehlt = STUFE_KEY[rb.mutig_stufe];
    var g = karte("rueckblick", "Rückblick-Test",
      unterzeile("So hätten die Regeln in den letzten Jahren abgeschnitten" + (isNaN(d) ? "" : " · eingefroren am " + datumLang(d))));
    var jk = kal.von && kal.bis ? jahre(kal.von, kal.bis) : "";
    var jp = pr.von && pr.bis ? jahre(pr.von, pr.bis) : "";

    var tab = el("table", "rb-tabelle");
    var thead = el("thead");
    var r1 = el("tr");
    add(r1, el("th", "links", "Strategie"), th("Festgelegt " + jk, "kal"), th("Absturz", "kal"),
      th("Geprüft " + jp, "haupt"), th("Absturz", "haupt"), th("Trades", ""), th("Treffer", ""), th("bester Trade", "opt"));
    add(thead, r1);
    add(tab, thead);
    var tbody = el("tbody");
    STRATEGIEN.forEach(function (s) {
      var a = kal[s.key], b = pr[s.key];
      if (!a && !b) return;
      var halten = s.key === "btc_halten" || s.key === "halten_50_50";
      var live = s.key === "ruhig" || s.key === gewaehlt;
      var tr = el("tr", halten ? "halten" : null);
      var name = el("td", "links");
      add(name, el("span", null, s.name));
      if (live) add(name, el("span", "tag", "live"));
      var balken = el("td", "haupt");
      if (b) {
        var bw = el("div", "wert-balken");
        add(bw, el("span", klasse(b.rendite_pct), pct(b.rendite_pct)));
        var bar = el("i", "balken" + (b.rendite_pct < 0 ? " neg" : ""));
        bar.style.width = Math.min(100, Math.abs(b.rendite_pct) / 1.4) + "%";
        add(bw, bar);
        add(balken, bw);
      } else balken.textContent = "–";
      add(tr, name,
        td(a ? pct(a.rendite_pct) : "–", "kal " + (a ? klasse(a.rendite_pct) : "")),
        td(a ? MINUS + pctOhneVz(a.tiefster_absturz_pct) : "–", "kal dim"),
        balken,
        td(b ? MINUS + pctOhneVz(b.tiefster_absturz_pct) : "–", "haupt-r dim"),
        td(!halten && b && typeof b.trades === "number" ? String(b.trades) : "–", "dim"),
        td(!halten && b && typeof b.trefferquote_pct === "number" ? pctOhneVz(b.trefferquote_pct) : "–", "dim"),
        td(!halten && b && typeof b.groesster_trade_pct === "number" ? pct(b.groesster_trade_pct) : "–", "opt dim"));
      add(tbody, tr);
    });
    add(tab, tbody);
    var rahmen = el("div", "tabelle-rahmen");
    add(rahmen, tab);
    add(g, rahmen);

    var hinweis = el("p", "fussnote");
    add(hinweis, el("b", null, "Geprüft"), document.createTextNode(" = Jahre, die die Regeln nie gesehen haben (die zählen) · "),
      el("b", null, "Absturz"), document.createTextNode(" = größter Rückgang vom Höchststand"));
    var lebende = [pr.ruhig, pr[gewaehlt]];
    if (pr.btc_halten && lebende.every(function (m) { return m && m.rendite_pct < pr.btc_halten.rendite_pct; })) {
      add(hinweis, document.createTextNode(" · Im Prüfzeitraum war einfach Halten besser – die Bewährungsprobe läuft trotzdem."));
    }
    if (rb.parameter && rb.parameter.beschreibung) hinweis.title = "Regeln: " + rb.parameter.beschreibung;
    add(g, hinweis);
    return g;
  }
  function th(text, cls) { return el("th", cls || null, text); }
  function td(text, cls) { return el("td", cls || null, text); }

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
    add(oben, kopf(daten.status, daten.verlauf));
    warnungen(daten.status, daten.verlauf).forEach(function (w) { add(oben, w); });
    add(neu, oben);

    if (z) {
      add(neu, kennzahlen(z));
      add(neu, abschnittVerlauf(daten.verlauf));
      add(neu, statusKarte(z, daten.status));
      add(neu, abschnittPositionen(z));
      add(neu, abschnittTrades(daten.trades));
    } else {
      var g = karte("start", "Der Trader startet beim nächsten Lauf.");
      add(g, el("p", "fussnote", "Sobald der erste Lauf fertig ist, erscheinen hier die Konten, der Vergleich mit Bitcoin und die Trades."));
      add(neu, g);
    }
    if (daten.rueckblick) add(neu, abschnittRueckblick(daten.rueckblick));
    if (z) add(neu, abschnittUrteil(z));
    add(neu, el("footer", "fuss", BEISPIEL ? "Beispieldaten – nur zum Ansehen" : "Spielgeld, kein echtes Geld · lädt alle 5 Minuten neu"));

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
