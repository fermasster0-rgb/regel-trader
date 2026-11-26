// Regel-Trader – Glas-Dashboard. Kein Framework, keine Bibliothek.
// Alle Inhalte werden mit createElement/textContent gebaut (nie innerHTML mit Daten).
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
    { key: "ohne_bremse", name: "Ohne Bremse", farbe: "#6FA8FF", cls: "ohne" },
    { key: "mit_bremse", name: "Mit Bremse", farbe: "#FFAE5E", cls: "mit" },
    { key: "mutig", name: "Mutig", farbe: "#C084FC", cls: "mutig" },
    { key: "btc_halten", name: "Bitcoin halten", farbe: "#AEB6C9", cls: "btc" }
  ];
  var KONTO_NAME = { ohne_bremse: "Ohne Bremse", mit_bremse: "Mit Bremse", mutig: "Mutig", btc_halten: "Bitcoin halten" };
  var KONTO_CLS = { ohne_bremse: "ohne", mit_bremse: "mit", mutig: "mutig", btc_halten: "btc" };

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
  function svg(tag, attrs) {
    var e = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // ---------- Zahlen und Zeiten (deutsches Format) ----------
  var MINUS = "−";
  function zahl(n, stellen) {
    return Math.abs(n).toLocaleString("de-DE", { minimumFractionDigits: stellen, maximumFractionDigits: stellen });
  }
  function usd(n, stellen) {
    if (stellen === undefined) stellen = Math.abs(n) >= 1000 ? 0 : 2;
    return (n < 0 ? MINUS : "") + zahl(n, stellen) + " $";
  }
  function usdVz(n) { // mit Vorzeichen
    var s = usd(n, Math.abs(n) >= 1000 ? 0 : 2);
    return (n > 0 ? "+" : "") + s;
  }
  function pct(n, stellen) {
    if (stellen === undefined) stellen = 1;
    var gerundet = Math.round(Math.abs(n) * Math.pow(10, stellen)) / Math.pow(10, stellen);
    var vz = n < 0 && gerundet !== 0 ? MINUS : (n > 0 && gerundet !== 0 ? "+" : "");
    return vz + zahl(gerundet, stellen) + " %";
  }
  function pctOhneVz(n) { return zahl(n, 1) + " %"; }
  function vorzeichenKlasse(n) { return n > 0 ? "gut" : (n < 0 ? "schlecht" : ""); }

  function fmt(d, opts) {
    opts.timeZone = ZONE;
    return d.toLocaleString("de-DE", opts);
  }
  function uhrzeit(d) { return fmt(d, { hour: "2-digit", minute: "2-digit", hour12: false }); }
  function datumKurz(d) { return fmt(d, { day: "2-digit", month: "2-digit" }); }
  function datumLang(d) { return fmt(d, { day: "2-digit", month: "2-digit", year: "numeric" }); }
  function tagKey(d) { return fmt(d, { day: "2-digit", month: "2-digit", year: "numeric" }); }
  function datumUhr(d) { return datumKurz(d) + ", " + uhrzeit(d); }
  function dauerText(ms) {
    var h = Math.floor(ms / 3600000);
    if (h < 48) return h + (h === 1 ? " Stunde" : " Stunden");
    var t = Math.floor(h / 24);
    return t + " Tagen";
  }
  // Ende eines Zeitraums: steht dort genau Mitternacht, ist das Ende ausgeschlossen -> einen Tag zurück
  function endeAnzeige(iso) {
    var d = new Date(iso);
    if (d.getUTCHours() === 0 && d.getUTCMinutes() === 0 && d.getUTCSeconds() === 0) d = new Date(d.getTime() - 86400000);
    return d;
  }

  // ---------- Laden ----------
  function laden(datei) {
    return fetch(ORDNER + datei + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .catch(function () { return null; });
  }
  function ladenRueckblick() {
    // Der Rückblick liegt immer in daten/, auch im Beispiel-Modus (falls dort keiner liegt)
    return laden("rueckblick.json").then(function (d) {
      if (d || ORDNER === "daten/") return d;
      return fetch("daten/rueckblick.json?t=" + Date.now(), { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .catch(function () { return null; });
    });
  }

  // ---------- Fenster ----------
  function glas(extra) { return el("section", "glas" + (extra ? " " + extra : "")); }
  function titelzeile(titel, rechts) {
    var z = el("div", "titelzeile");
    add(z, el("h2", "titel", titel));
    if (rechts) add(z, rechts);
    return z;
  }
  function warnIcon(farbe) {
    var s = svg("svg", { width: 28, height: 28, viewBox: "0 0 24 24", fill: "none", stroke: farbe,
      "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
    add(s, svg("circle", { cx: 12, cy: 12, r: 9 }), svg("line", { x1: 12, y1: 7, x2: 12, y2: 13 }),
      svg("circle", { cx: 12, cy: 16.5, r: 0.6 }));
    return s;
  }
  function hinweisFenster(klasse, farbe, t1, t2) {
    var g = glas("hinweis " + klasse);
    var txt = el("div", "txt");
    add(txt, el("div", "t1", t1));
    if (t2) add(txt, el("div", "t2", t2));
    add(g, warnIcon(farbe), txt);
    return g;
  }

  // ---------- 1. Kopf ----------
  function kopf(zustand, status, verlauf) {
    var k = el("header", "kopf");
    var links = el("div", "links");
    var letzter = letzterLauf(status, verlauf);
    var zeile = "Spielgeld";
    if (letzter) zeile += " · zuletzt aktualisiert " + uhrzeit(letzter);
    add(links, el("div", "zeile", zeile), el("h1", null, "Regel-Trader"));
    add(k, links);
    if (zustand && typeof zustand.tag === "number") {
      add(k, el("div", "chip", probeVorbei(zustand) ? "Probezeit vorbei" : "Tag " + zustand.tag + " / " + PROBE_TAGE));
    }
    return k;
  }
  // Volle Tage seit dem Start; "tag" zählt ab 1 (Tag 1 = erster Tag)
  function volleTage(zustand) {
    return typeof zustand.abgeschlossene_tage === "number" ? zustand.abgeschlossene_tage : zustand.tag - 1;
  }
  function hatUrteil(zustand) {
    var konten = zustand.konten || {};
    return Object.keys(konten).some(function (k) { return !!URTEILE[konten[k].urteil]; });
  }
  // Vorbei, sobald 56 volle Tage um sind – oder sobald ein endgültiges Urteil steht
  function probeVorbei(zustand) { return volleTage(zustand) >= PROBE_TAGE || hatUrteil(zustand); }
  function letzterLauf(status, verlauf) {
    if (status && status.letzter_lauf) { var d = new Date(status.letzter_lauf); if (!isNaN(d)) return d; }
    if (verlauf && verlauf.length) return new Date(verlauf[verlauf.length - 1].zeit);
    return null;
  }
  function warnungen(status, verlauf) {
    var liste = [];
    var letzter = letzterLauf(status, verlauf);
    if (status && status.ok === false) {
      liste.push(hinweisFenster("fehler", "#FFB4B4", "Der letzte Lauf ist fehlgeschlagen",
        (status.fehler || "Unbekannter Fehler") + " – gehandelt wurde dabei nicht."));
    }
    if (ALTER_PRUEFEN && letzter) {
      var alter = Date.now() - letzter.getTime();
      if (alter > VERALTET_STUNDEN * 3600000) {
        liste.push(hinweisFenster("warn", "#FFC48A", "Der Trader ist seit " + dauerText(alter) + " nicht mehr gelaufen",
          "Letzter Lauf: " + datumUhr(letzter) + ". Die Zahlen unten sind nicht aktuell."));
      }
    }
    return liste;
  }

  // ---------- 2. Wer liegt vorne? ----------
  function stand(zustand) {
    var res = [];
    KONTEN.forEach(function (k) {
      var d = k.key === "btc_halten" ? zustand.btc_halten : (zustand.konten || {})[k.key];
      if (!d) return;
      res.push({ k: k, wert: Number(d.wert), pleite: !!d.pleite,
        trades: typeof d.abgeschlossene_trades === "number" ? d.abgeschlossene_trades : null });
    });
    res.sort(function (a, b) { return b.wert - a.wert; });
    return res;
  }

  function diagramm(verlauf) {
    var W = 324, H = 150, PX = 4, PY = 12;
    var s = svg("svg", { "class": "chart", viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Verlauf der vier Konten seit Start" });
    var t0 = verlauf[0].zeit, t1 = verlauf[verlauf.length - 1].zeit;
    var lo = START_KAPITAL, hi = START_KAPITAL;
    verlauf.forEach(function (p) {
      KONTEN.forEach(function (k) { var v = p[k.key]; if (typeof v === "number") { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    });
    var rand = Math.max((hi - lo) * 0.12, 20);
    lo -= rand; hi += rand;
    function x(t) { return verlauf.length < 2 || t1 === t0 ? W / 2 : PX + (t - t0) / (t1 - t0) * (W - 2 * PX - 6); }
    function y(v) { return PY + (hi - v) / (hi - lo) * (H - 2 * PY); }

    add(s, svg("line", { x1: 0, y1: y(START_KAPITAL), x2: W, y2: y(START_KAPITAL),
      stroke: "rgba(255,255,255,0.18)", "stroke-dasharray": "3 5" }));
    var lbl = svg("text", { x: 2, y: y(START_KAPITAL) - 4, fill: "rgba(255,255,255,0.5)", "font-size": 9, "font-family": "Inter, sans-serif" });
    lbl.textContent = "Start " + usd(START_KAPITAL, 0).replace(" ", " ");
    add(s, lbl);

    // Reihenfolge: Bitcoin zuerst (hinten), die Konten darüber
    var zeichen = [KONTEN[3], KONTEN[2], KONTEN[0], KONTEN[1]];
    zeichen.forEach(function (k) {
      var pts = verlauf.filter(function (p) { return typeof p[k.key] === "number"; });
      if (!pts.length) return;
      if (pts.length > 1) {
        var d = pts.map(function (p, i) { return (i ? "L" : "M") + x(p.zeit).toFixed(1) + " " + y(p[k.key]).toFixed(1); }).join(" ");
        var attrs = { d: d, fill: "none", stroke: k.farbe, "stroke-width": k.key === "btc_halten" ? 2 : 3,
          "stroke-linejoin": "round", "stroke-linecap": "round" };
        if (k.key === "btc_halten") attrs["stroke-dasharray"] = "5 4";
        add(s, svg("path", attrs));
      }
      var last = pts[pts.length - 1];
      add(s, svg("circle", { cx: x(last.zeit).toFixed(1), cy: y(last[k.key]).toFixed(1), r: 4, fill: k.farbe }));
    });
    return { svg: s, von: new Date(t0), bis: new Date(t1) };
  }

  function kachel(eintrag, erster) {
    var k = eintrag.k;
    var c = el("div", "kachel k-" + k.cls + (erster ? " erster" : ""));
    var n = el("div", "n");
    add(n, el("span", "punkt c-" + k.cls), el("span", null, k.name));
    add(c, n);
    if (eintrag.pleite) {
      add(c, el("div", "p schlecht", "pleite"), el("div", "d", usd(eintrag.wert)));
    } else {
      var p = (eintrag.wert / START_KAPITAL - 1) * 100;
      add(c, el("div", "p " + vorzeichenKlasse(Math.round(p * 10) / 10), pct(p)), el("div", "d", usd(eintrag.wert)));
    }
    if (eintrag.trades !== null) add(c, el("div", "v", "abgeschlossene Trades: " + eintrag.trades + " / mind. " + MIN_TRADES));
    if (erster) add(c, el("div", "v", "liegt vorne"));
    return c;
  }

  function abschnittVorne(zustand, verlauf) {
    var g = glas();
    add(g, titelzeile("Wer liegt vorne?", el("div", "klein", "seit Start")));
    if (verlauf && verlauf.length) {
      var dg = diagramm(verlauf);
      add(g, dg.svg);
      var achse = el("div", "zl");
      add(achse, el("span", "klein", datumKurz(dg.von)), el("span", "klein", "jetzt"));
      add(g, achse);
    }
    var kacheln = el("div", "kacheln");
    stand(zustand).forEach(function (e, i) { add(kacheln, kachel(e, i === 0)); });
    add(g, kacheln);
    add(g, el("div", "klein", "Alle Konten starten mit " + usd(START_KAPITAL, 0) + " Spielgeld. Die Werte sind nach allen Gebühren – so viel bliebe, wenn jetzt alles verkauft würde."));
    return g;
  }

  // ---------- 3. Offene Positionen ----------
  function positionsBlock(kontoKey, pos, preise) {
    var b = el("div", "pos");
    var kurs = Number(preise[pos.coin]);
    var p = (kurs / pos.einstieg - 1) * 100;
    var kn = el("div", "kontoname");
    add(kn, el("span", "punkt c-" + KONTO_CLS[kontoKey]), el("span", null, KONTO_NAME[kontoKey]));
    var kopfz = el("div", "titelzeile");
    add(kopfz, kn, el("div", "pille " + (p >= 0 ? "gut" : "schlecht"), pct(p)));
    add(b, kopfz);

    var z = el("div", "zl");
    var links = el("div");
    add(links, el("b", null, pos.coin), el("span", "a", "  Einstieg " + usd(pos.einstieg)));
    if (pos.geliehen > 0) add(links, el("span", "a", " · mit Hebel"));
    add(z, links, el("div", null, "jetzt " + usd(kurs)));
    z.lastChild.style.fontWeight = "600";
    add(b, z);

    var lo = pos.stop;
    var hi = Math.max(kurs, pos.hoechster_schluss || 0, pos.einstieg) + Math.max(pos.einstieg - pos.stop, 0) * 0.5;
    if (hi <= lo) hi = lo + 1;
    function f(v) { return Math.max(0, Math.min(1, (v - lo) / (hi - lo))) * 100; }
    var leiste = el("div", "leiste");
    var ein = el("div", "einstieg"); ein.style.left = f(pos.einstieg) + "%";
    var marke = el("div", "marke"); marke.style.left = f(kurs) + "%";
    add(leiste, ein, marke);
    add(b, leiste);

    var unten = el("div", "zl");
    var bisLimit = (kurs / pos.stop - 1) * 100;
    add(unten, el("span", "klein", "Verlust-Limit " + usd(pos.stop)),
      el("span", "klein", "noch " + pctOhneVz(Math.max(bisLimit, 0)) + " bis zum Limit"));
    add(b, unten);
    return b;
  }

  function abschnittPositionen(zustand) {
    var g = glas();
    add(g, titelzeile("Offene Positionen"));
    var preise = zustand.preise || {};
    var n = 0;
    ["ohne_bremse", "mit_bremse", "mutig"].forEach(function (key) {
      var konto = (zustand.konten || {})[key];
      if (!konto) return;
      Object.keys(konto.positionen || {}).forEach(function (coin) {
        n++;
        add(g, positionsBlock(key, konto.positionen[coin], preise));
      });
      Object.keys(konto.vorgemerkt || {}).forEach(function (coin) {
        var o = konto.vorgemerkt[coin];
        n++;
        var b = el("div", "pos");
        var kn = el("div", "kontoname");
        add(kn, el("span", "punkt c-" + KONTO_CLS[key]), el("span", null, KONTO_NAME[key]));
        add(b, kn);
        var art = o.art === "verkauf" ? "Verkauf" : "Kauf";
        var v = el("div", "vorm");
        add(v, el("b", null, coin + ": "), document.createTextNode(art + " vorgemerkt zum nächsten Kurs"));
        if (o.grund) add(v, el("div", "klein", o.grund));
        add(b, v);
        add(g, b);
      });
    });
    if (!n) add(g, el("div", "leer", "Zurzeit hat kein Konto eine Position offen."));
    else add(g, el("div", "klein", "Weißer Strich: jetziger Kurs · dünner Strich: Einstieg · links ist das Verlust-Limit."));
    return g;
  }

  // ---------- 4. Nachrichten-Bremse ----------
  function abschnittBremse(zustand) {
    var b = zustand.bremse;
    if (!b) return null;
    if (b.aktiv) {
      var bis = b.bis_ms ? new Date(b.bis_ms) : null;
      var t = "Nachrichten-Bremse aktiv";
      if (bis) t += " bis " + uhrzeit(bis) + (tagKey(bis) !== tagKey(new Date()) ? " (" + datumKurz(bis) + ")" : "");
      var teile = [];
      if (b.grund) teile.push("Grund: " + b.grund);
      if (b.quelle && !/\.json/i.test(String(b.quelle))) teile.push("Quelle: " + String(b.quelle).replace(/\s*https?:\/\/\S+/g, ""));
      teile.push("Keine neuen Käufe – verkauft wird weiter normal.");
      if (b.nachrichten_ok === false) teile.push("Nachrichten gerade nicht erreichbar.");
      return hinweisFenster("warn", "#FFC48A", t, teile.join(" · "));
    }
    var g = glas("hinweis");
    var ok = b.nachrichten_ok !== false;
    var s = svg("svg", { width: 28, height: 28, viewBox: "0 0 24 24", fill: "none", stroke: ok ? "#A7F3C0" : "#FFC48A",
      "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
    if (ok) add(s, svg("circle", { cx: 12, cy: 12, r: 9 }), svg("path", { d: "M8 12.5l2.7 2.7L16 9.5" }));
    else add(s, svg("circle", { cx: 12, cy: 12, r: 9 }), svg("line", { x1: 12, y1: 7, x2: 12, y2: 13 }), svg("circle", { cx: 12, cy: 16.5, r: 0.6 }));
    var txt = el("div", "txt");
    add(txt, el("div", "t1", ok ? "Nachrichten-Bremse: frei" : "Nachrichten nicht erreichbar"),
      el("div", "klein", ok ? "Keine Schock-Meldung, kein Termin – der Trader darf kaufen."
        : "Der Trader handelt ohne Bremse, bis die Nachrichten wieder erreichbar sind."));
    add(g, s, txt);
    return g;
  }

  // ---------- 5. Rückblick-Test ----------
  var STRATEGIEN = [
    { key: "ruhig", name: "Ruhig" },
    { key: "mutig", name: "Mutig" },
    { key: "mutig_hebel", name: "Mutig + Hebel" },
    { key: "btc_halten", name: "Bitcoin halten" },
    { key: "halten_50_50", name: "50/50 halten" }
  ];
  var STUFE_KEY = { "Ruhig": "ruhig", "Mutig": "mutig", "Mutig + Hebel": "mutig_hebel" };

  function wertBlock(titel, zeitraum, m, istHalten) {
    var w = el("div");
    add(w, el("div", "zeitraum", titel + " · " + zeitraum));
    var r = el("div", "werte");
    function feld(label, text, cls) {
      var d = el("div");
      add(d, el("span", "l", label), el("span", "z" + (cls ? " " + cls : ""), text));
      return d;
    }
    add(r, feld("Rendite", pct(m.rendite_pct), vorzeichenKlasse(m.rendite_pct)),
      feld("tiefster Absturz", pctOhneVz(m.tiefster_absturz_pct)),
      feld("größter Einzeltrade", istHalten ? "–" : pct(m.groesster_trade_pct)));
    if (!istHalten) {
      add(r, feld("Trades", typeof m.trades === "number" ? m.trades.toLocaleString("de-DE") : "–"),
        feld("Trefferquote", typeof m.trefferquote_pct === "number" ? pctOhneVz(m.trefferquote_pct) : "–"),
        feld("Trades über +10 %", typeof m.trades_ueber_10 === "number" ? m.trades_ueber_10.toLocaleString("de-DE") : "–"));
    }
    add(w, r);
    return w;
  }

  function abschnittRueckblick(rb) {
    var g = glas();
    add(g, titelzeile("Rückblick-Test"));
    var d = new Date(rb.stand);
    if (!isNaN(d)) add(g, el("div", "klein", "Stand: " + datumLang(d) + " · so hätten die Regeln in der Vergangenheit abgeschnitten"));
    if (rb.parameter && rb.parameter.beschreibung) add(g, el("div", "text", "Gewählte Regeln: " + rb.parameter.beschreibung));
    var kal = rb.kalibrierung || {}, pr = rb.pruefung || {};
    var zrKal = kal.von && kal.bis ? datumLang(new Date(kal.von)) + " – " + datumLang(endeAnzeige(kal.bis)) : "";
    var zrPr = pr.von && pr.bis ? datumLang(new Date(pr.von)) + " – " + datumLang(endeAnzeige(pr.bis)) : "";
    var gewaehlt = STUFE_KEY[rb.mutig_stufe];
    STRATEGIEN.forEach(function (s) {
      if (!kal[s.key] && !pr[s.key]) return;
      var halten = s.key === "btc_halten" || s.key === "halten_50_50";
      var box = el("div", "sgr" + (s.key === gewaehlt ? " gewaehlt" : ""));
      var h = el("h3");
      add(h, el("span", null, s.name));
      if (s.key === gewaehlt) add(h, el("span", "pille", "Mutig-Konto"));
      add(box, h);
      if (kal[s.key]) add(box, wertBlock("Kalibrierung", zrKal, kal[s.key], halten));
      if (pr[s.key]) add(box, wertBlock("Prüfung", zrPr, pr[s.key], halten));
      add(g, box);
    });
    add(g, el("div", "klein", "Kalibrierung: darauf wurden die Regeln eingestellt. Prüfung: ungesehene Zeit danach – die zählt."));
    if (rb.mutig_stufe) {
      add(g, el("div", "text", "Das Mutig-Konto läuft als „" + rb.mutig_stufe + "“." + (rb.mutig_grund ? " " + rb.mutig_grund : "")));
    }
    // Hinweis nur, wenn ALLE live laufenden Regeln (Ruhig und die gewählte Mutig-Stufe) schlechter waren als Halten
    var lebende = [pr.ruhig, pr[gewaehlt]];
    if (pr.btc_halten && lebende.every(function (m) { return m && m.rendite_pct < pr.btc_halten.rendite_pct; })) {
      add(g, el("div", "text", "Im Prüfzeitraum war einfach Halten besser. Die Bewährungsprobe läuft trotzdem, sie kostet nichts."));
    }
    return g;
  }

  // ---------- 6. Letzte Trades ----------
  function abschnittTrades(trades) {
    var g = glas();
    add(g, titelzeile("Letzte Trades"));
    var liste = (trades || []).slice().sort(function (a, b) { return b.verkauf_zeit - a.verkauf_zeit; }).slice(0, 10);
    if (!liste.length) {
      add(g, el("div", "leer", "Noch kein Trade abgeschlossen."));
      return g;
    }
    liste.forEach(function (t) {
      var row = el("div", "trade");
      var l = el("div", "l");
      var k = el("div", "k");
      add(k, el("span", "punkt c-" + (KONTO_CLS[t.konto] || "btc")), el("span", null, t.coin),
        el("span", "klein", KONTO_NAME[t.konto] || t.konto));
      add(l, k);
      if (t.grund_kauf) add(l, el("div", "g", "Kauf: " + t.grund_kauf));
      if (t.grund_verkauf) add(l, el("div", "g", "Verkauf: " + t.grund_verkauf));
      add(l, el("div", "g", "Verkauft: " + datumUhr(new Date(t.verkauf_zeit))));
      var r = el("div", "r");
      var cls = vorzeichenKlasse(t.ergebnis_usd);
      add(r, el("b", cls, usdVz(t.ergebnis_usd)), el("span", cls, pct(t.ergebnis_pct, 1)),
        el("span", "ul", "Ergebnis des Trades"));
      add(row, l, r);
      add(g, row);
    });
    return g;
  }

  // ---------- 7. Urteil ----------
  var URTEILE = {
    bewiesen: ["🟢", "Bewiesen: hat Geld gemacht"],
    nicht_bewiesen: ["🔴", "Nicht bewiesen: kein Gewinn"],
    zu_wenige_trades: ["⚪", "Noch kein Urteil – zu wenige Trades"]
  };
  function abschnittUrteil(zustand) {
    var konten = zustand.konten || {};
    if (!hatUrteil(zustand)) return null; // erst wenn ein endgültiges Urteil steht (nach 56 vollen Tagen)
    var g = glas();
    add(g, titelzeile("Urteil", el("div", "klein", "nach " + PROBE_TAGE + " Tagen")));
    ["ohne_bremse", "mit_bremse", "mutig"].forEach(function (key) {
      var k = konten[key];
      if (!k || !URTEILE[k.urteil]) return;
      var u = URTEILE[k.urteil];
      var row = el("div", "urteil");
      var tx = el("div", "u");
      add(tx, el("span", null, KONTO_NAME[key] + ": " + u[1]),
        el("small", null, usd(k.wert) + " · " + k.abgeschlossene_trades + (k.abgeschlossene_trades === 1 ? " Trade" : " Trades") + " abgeschlossen"));
      add(row, el("span", "em", u[0]), tx);
      add(g, row);
    });
    if (zustand.btc_halten) add(g, el("div", "klein", "Zum Vergleich: Bitcoin halten steht bei " + usd(zustand.btc_halten.wert) + "."));
    add(g, el("div", "klein", "Bewiesen heißt: Kontostand nach allen Gebühren über " + usd(START_KAPITAL, 0) + " und mindestens " + MIN_TRADES + " abgeschlossene Trades."));
    return g;
  }

  // ---------- Seite bauen ----------
  function bauen(daten) {
    var app = document.getElementById("app");
    var neu = document.createDocumentFragment();
    var z = daten.zustand;
    add(neu, kopf(z, daten.status, daten.verlauf));
    warnungen(daten.status, daten.verlauf).forEach(function (w) { add(neu, w); });

    if (z) {
      add(neu, abschnittVorne(z, daten.verlauf));
      add(neu, abschnittPositionen(z));
      add(neu, abschnittBremse(z));
    } else {
      var g = glas();
      add(g, el("div", "titel", "Der Trader startet beim nächsten Lauf."),
        el("div", "text", "Sobald der erste Lauf fertig ist, erscheinen hier die Konten, der Vergleich mit Bitcoin und die Trades."));
      add(neu, g);
    }
    if (daten.rueckblick) add(neu, abschnittRueckblick(daten.rueckblick));
    if (z) {
      add(neu, abschnittTrades(daten.trades));
      add(neu, abschnittUrteil(z));
    }
    add(neu, el("div", "fuss", BEISPIEL ? "Beispieldaten – nur zum Ansehen" : "Spielgeld, kein echtes Geld · lädt alle 5 Minuten neu"));
    while (app.firstChild) app.removeChild(app.firstChild);
    app.appendChild(neu);
  }

  function alles() {
    return Promise.all([laden("zustand.json"), laden("verlauf.json"), laden("trades.json"), laden("status.json"), ladenRueckblick()])
      .then(function (r) {
        bauen({ zustand: r[0], verlauf: r[1], trades: r[2], status: r[3], rueckblick: r[4] });
      })
      .catch(function (e) {
        var app = document.getElementById("app");
        app.textContent = "Die Seite konnte nicht aufgebaut werden. Bitte später noch einmal laden.";
        if (window.console) console.error(e);
      });
  }

  alles();
  setInterval(alles, NEU_LADEN_MS);
})();
