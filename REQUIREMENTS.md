# Anforderungen – E-M1 Capture

Stand: 2026-11-09. Gesammelt aus den Gesprächen mit dem Nutzer, `BACKLOG.md` (B = OM Capture, M = Handbuch,
U = Nutzeraufgaben), `HANDOVER.md` und `CLAUDE.md`. Jede neue Anforderung bekommt hier eine Nummer;
Agenten arbeiten gegen diese Liste.

**Stand:** ✅ erfüllt und getestet · 🟡 teilweise / gebaut, ungetestet · ⬜ offen · ⛔ nicht möglich (Grund)
**Verbindung:** Mac-USB · Mac-WiFi · iPhone (nur Wi-Fi) · Watch (über das iPhone)
**Priorität:** P1 jetzt · P2 als Nächstes · P3 später (Vorschlag, vom Nutzer zu bestätigen)

## 1. Ziel und Rahmen

| ID | Anforderung | Quelle | Stand |
|---|---|---|---|
| REQ-G01 | Ersatz für OM Capture für die OM-D E-M1 Mark I (Firmware 4.6), als lokale App. | Nutzer, HANDOVER | 🟡 |
| REQ-G02 | **USB und Wi-Fi gleichwertig, möglichst 1:1.** Jede Funktion für beide Verbindungen bauen oder begründen, warum nicht; Abgleich-Tabelle in HANDOVER.md und README pflegen. | Nutzer | 🟡 |
| REQ-G03 | Bedienung auch vom **iPhone** (direkt über Kamera-WLAN, ohne Mac) und von der **Apple Watch** (über das iPhone). | Nutzer | ⬜ |
| REQ-G04 | **Modernes, stilvolles Design**, das der Kamera „neues Leben“ gibt; angelehnt (nicht kopiert) an aktuelle OM-System-Menüs und Super Control Panel, Insta360 und die iOS-Kamera. | Nutzer | ⬜ |
| REQ-G05 | Begriffe wie im Handbuch `EM1_VER4_Eng.pdf`; Oberfläche englisch, alle Texte in einer Übersetzungstabelle, weitere Sprachen folgen. „computer“ statt „Mac“. | Nutzer | ✅ |

## 2. Sicherheit und Regeln (immer gültig)

| ID | Anforderung | Stand |
|---|---|---|
| REQ-S01 | Nie Firmware flashen; Originaldateien in `download/` und `OLY_E_109_*.BIN` nie ändern. | ✅ |
| REQ-S02 | Nichts an der Kamera schreiben, auslösen oder den Modus wechseln ohne Freigabe; in der App nur auf Bedienung durch den Nutzer; App startet ohne `--allow-write` nur lesend. | ✅ |
| REQ-S03 | App nur auf `127.0.0.1`, keine fremden Webseiten (Host/Origin-Prüfung). Für iPhone/Watch-Zugriff auf den Mac nur mit eigenem Schalter und Schlüssel. | ✅ / ⬜ |
| REQ-S04 | Keine persönlichen Daten im Repo (Seriennummer, Pfade, E-Mail, Fotos); Commits mit GitHub-noreply-Adresse. | ✅ |
| REQ-S05 | Agenten sprechen nie mit der Kamera; Kameratests nur in der Hauptsitzung mit Freigabe. | ✅ |

## 3. Funktionen

| ID | Anforderung (Begriff wie im Handbuch) | Quelle | Mac-USB | Mac-WiFi | iPhone | Prio |
|---|---|---|---|---|---|---|
| REQ-F01 | Verbindungswahl mit erkanntem Kameranamen; Kartenverzeichnis über USB beim Verbinden einlesen (erstes Foto schnell). | Nutzer | ✅ | ✅ | ⬜ | P1 |
| REQ-F02 | Live View, Größe wählbar (Wi-Fi), Zoom 1×/2×/4×, Displayed Grid, Overlay, zweiter Monitor. | HANDOVER, B7/B8 | ✅ | ✅ | ⬜ | P1 |
| REQ-F03 | Live-View-Hilfen: Histogram, Highlight&Shadow, Peaking. | Nutzer | ✅ | ✅ | ⬜ | P2 |
| REQ-F04 | 9×9-AF-Raster, Antippen stellt scharf, scharfes Feld grün, Raster immer deckungsgleich mit dem Bild. | Nutzer | ✅ | ✅ | ⬜ | P1 |
| REQ-F05 | AF Area (All / Single / Small / Group Target). | HANDOVER | ✅ | ⛔ kein CGI | ⛔ | – |
| REQ-F06 | Shutter button: Take picture, Press halfway (Fokus halten, dann auslösen). | Nutzer | 🟡 | ✅ | ⬜ | P1 |
| REQ-F07 | Antippen und auslösen (Handbuch S. 27). | M6 | ⬜ | ⬜ | ⬜ | P2 |
| REQ-F08 | LV super control panel aus den Kamerawerten; Blendenliste nach Objektiv; Objektivname in der Kopfzeile. | Nutzer, HANDOVER | 🟡 (Modusrad) | ✅ | ⬜ | P1 |
| REQ-F09 | Nur lesbare Werte anzeigen (Anti-Shock, Silent, Noise Reduct., BULB/TIME Timer, Digital Tele-converter). | M2 | ⬜ unbekannt | ✅ | ⬜ | P3 |
| REQ-F10 | Weitere Einstellungen über USB (Metering, Image Stabilizer, AF Mode, Record mode, Flash, Bracketing …) per USB-Werte-Lauscher erschließen. | Nutzer, M9, U5 | ⬜ | ⛔ teils kein CGI | ⛔ | P2 |
| REQ-F11 | Movie: Start/Stop recording, Recording time, Movie-Modus P/A/S/M, Record mode (movie) anzeigen. | Nutzer | ⬜ | ✅ | ⬜ | P2 |
| REQ-F12 | BULB / LIVE TIME / LIVECOMP mit Laufzeit; Fortschrittsbild bei Live Composite. | HANDOVER, B5 | 🟡 | 🟡 | ⬜ | P3 |
| REQ-F13 | Time lapse shooting und AE BKT (app-gesteuert); kamerainterne Time Lapse/Focus BKT nur prüfen. | HANDOVER, B3/B4, M10 | 🟡 | 🟡 | ⬜ | P3 |
| REQ-F14 | Selbstauslöser in der App (z. B. 3 s / 10 s). | Liste „wenig Aufwand“ | ⬜ | ⬜ | ⬜ | P2 |
| REQ-F15 | Playback: Index display, Calendar display, Einzelbild; JPG als Vorschau, wenn vorhanden; schnelle Vorschauen mit Cache; Liste lädt automatisch. | Nutzer | ✅ | ✅ | ⬜ | P1 |
| REQ-F16 | Neues Bild nach dem Auslösen sofort anzeigen (Rec View). | B2, M5 | ⬜ | ⬜ | ⬜ | P2 |
| REQ-F17 | Speichern: Card only / Card and computer; Dateinamen-Schema beim Speichern; „OM Workspace“ öffnen. | B1, B16 | ✅ | ✅ | ⬜ | P2 |
| REQ-F18 | Share Order anzeigen, alle speichern, Reset Share Order; Filmlänge. | M3 | ⛔ kein PTP-Gegenstück bekannt | ✅ | ⬜ | P3 |
| REQ-F19 | Status: freier Kartenplatz, Akkustand. | M1 | ✅ | ✅ Karte / ⛔ Akku | ⬜ | P2 |
| REQ-F20 | Turn off camera. | M4 | ⬜ | 🟡 ungetestet | ⬜ | P3 |
| REQ-F21 | Positionsdaten aus GPS-Log ins EXIF. | M7 | ⬜ | ⬜ | ⬜ | P3 |
| REQ-F22 | Electronic zoom für Power-Zoom-Objektive. | M8 | ⬜ | ⬜ | ⬜ | P3 |
| REQ-F23 | Level gauge (Wasserwaage) live. | HANDOVER | ⛔ Werte nur bei Sitzungsaufbau | ⬜ RTP-Kopf prüfen | ⬜ | P3 |

## 4. iPhone und Apple Watch

| ID | Anforderung | Stand | Prio |
|---|---|---|---|
| REQ-M01 | Native iPhone-App (SwiftUI), spricht direkt OI.Share 2.60 mit der Kamera im Kamera-WLAN; Funktionen schrittweise wie Mac-WiFi (REQ-F02/04/06/08/11/15). | ⬜ | P2 |
| REQ-M02 | Apple-Watch-App als Begleiter: kleines Livebild über das iPhone, Antippen setzt Fokuspunkt, Auslöser, Selbstauslöser, Digital Crown für Zoom. | ⬜ | P2 |
| REQ-M03 | Voraussetzung: Xcode aktiv, Signieren mit Apple-ID; Tests mit Kamera nur am echten iPhone. | ⬜ | P2 |

## 5. Design und Bedienung

| ID | Anforderung | Stand | Prio |
|---|---|---|---|
| REQ-D01 | Design-System (Farben, Schrift, Abstände, Bewegung) und Prototypen in `design/` vor dem Umbau (Agent `ui-designer`). | ⬜ | P1 |
| REQ-D02 | Live View im Mittelpunkt; Bedienelemente stören das Antippen des AF-Rasters nicht. | ⬜ | P1 |
| REQ-D03 | Dunkles Design zuerst, gute Kontraste, Touch-Flächen ≥ 44 px; gleiche Gestaltung auf Mac, iPhone und Watch. | ⬜ | P1 |
| REQ-D04 | Anpassbares Layout und Super Control Panel. | B9/B10 (teilweise „Customize layout“) | P3 |
| REQ-D05 | Webcam-Ansicht für OBS (sauberes Livebild, feste Größe) mit Anleitung. | U4 | ⬜ | P3 |

## 6. Bildbearbeitung (am Computer)

| ID | Anforderung | Stand | Prio |
|---|---|---|---|
| REQ-I01 | Software-HSL nach PEN-F-Vorbild (12 Sektoren, H/S/L −7…+7, Profile). | 🟡 gebaut und an ORF getestet | P2 |
| REQ-I02 | Claudra 800 (Portra-800-Look): In-Kamera-Rezept + `claudra800_orf.py` (Daylight/Tungsten). | U1 ⬜ | P3 |
| REQ-I03 | CineStill 800T mit Halation, Bloom, Korn, Vorher/Nachher. | U3 ⬜ | P3 |
| REQ-I04 | Look beim Speichern auf den Computer automatisch als zusätzliches JPG anwenden. | ⬜ | P3 |
| REQ-I05 | Selfie-Automatik: Gesicht erkennen, scharf stellen, auslösen, Belichtung im Gesicht messen (Ziel 155–170/255, < 1 % Clipping), nachregeln. | U2 ⬜ | P3 |

## 7. Forschung

| ID | Anforderung | Stand | Prio |
|---|---|---|---|
| REQ-R01 | USB-Werte-Lauscher an der Kamera laufen lassen und Menüpunkte zuordnen (`tools/usb_props.py`). | 🟡 gebaut, zurückgestellt | P2 |
| REQ-R02 | Firmware-Vergleich E-M1 / PEN-F / E-P7: ist ein HSL-Patch denkbar? Nur Untersuchung, nie flashen. | ⬜ Dateien geladen | P3 |
| REQ-R03 | Funktionen von OLYMPUS Capture 1.1 mit der E-M1 als Vorlage für USB. | 🟡 recherchiert | P3 |

## 8. Qualität und Auslieferung

| ID | Anforderung | Stand |
|---|---|---|
| REQ-Q01 | Tests ohne Kamera für jede Funktion (`python -B -m unittest discover -s tests`). | ✅ |
| REQ-Q02 | Privates Repo HolmHaensel/omcap, Releases mit CHANGELOG; Merge nach `main` und Push erst nach Test und Freigabe durch den Nutzer. | ✅ |
| REQ-Q03 | Kurze Anleitung (README): Requirements, Installation, Wi-Fi- und USB-Nutzung, beste Wi-Fi-Einstellungen. | ✅ |
| REQ-Q04 | Arbeit mit Agenten (feste Modelle, siehe HANDOVER), sparsam mit Tokens. | ✅ |

## Version 0.2 (Umfang, 2026-11-09)

Thema: stabil und alltagstauglich mit USB und Wi-Fi. Größeres (Design-System, iPhone/Watch, Antippen-und-auslösen, Film-Looks) ab 0.3.

| In 0.2 | REQ | Stand |
|---|---|---|
| Kartenplatz, Akku, nur lesbare Werte | F19, F09 | ✅ |
| Share Order, Filmlänge | F18 | ✅ (Wi-Fi) |
| Turn off camera | F20 | 🟡 Test im Paket |
| Live-View-Hilfen | F03 | ✅ |
| USB: AF-Raster, Objektiv, schnelles erstes Foto, Liste automatisch | F01, F04, F08, F15 | ✅ |
| Software-HSL | I01 | ✅ |
| Englische Code-Kommentare | Q (Community) | in Arbeit |
| **Neu:** Selbstauslöser | F14 | ⬜ |
| **Neu:** letztes Bild sofort zeigen | F16 | ⬜ |
| **Neu:** Webcam-Ansicht für OBS | D05 | ⬜ |
| USB-Werte-Lauscher (Werkzeug, Lauf später) | R01 | 🟡 |

## Version 0.3 (Umfang, 2026-11-09)

| In 0.3 | REQ | Stand |
|---|---|---|
| Angetipptes AF-Feld sofort markieren | F04 | 🟡 gebaut (`focus-speed`) |
| Webcam-Knopf (öffnet Ansicht, kopiert OBS-Link) | D05 | ⬜ |
| Speicherort in der App wählbar, Dateinamen-Schema | F17 | ⬜ |
| HSL in der App: Einzelansicht, „On the computer“, optional beim Speichern | I01, I04 | ⬜ |
| Kartenplatz über Wi-Fi (`errorcode 1001`) | F19 | ⬜ |

Danach (0.4+): Design-System, iPhone/Watch, Antippen und auslösen, Film-Looks, USB-Werte-Lauscher.
