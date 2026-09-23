# YouTube to MP3 Downloader

Kategorie auswählen → 100–500 passende YouTube-Links werden automatisch
gefunden → auswählen → als MP3 herunterladen.

| | |
|---|---|
| **Suchen** | Mehrere Suchbegriffe pro Kategorie, Duplikate und Live-Streams fliegen raus |
| **Auswählen** | Alle Treffer in einer Tabelle mit Häkchen, Filter und Sortierung |
| **Laden** | `yt-dlp` + FFmpeg, zwei Fortschrittsbalken, Fehler werden übersprungen statt abzubrechen |

---

## Schnellstart

```powershell
python -m pip install -r requirements.txt   # einmalig
python .\run_gui.py                         # starten
```

Zusätzlich nötig: **Python 3.10+** und **FFmpeg** im System-`PATH`.

---

## Bedienung

**1 · Suchen**
Kategorie im Dropdown wählen, gewünschte Anzahl Links einstellen, *Suchen*.
Das Programm fragt die Suchbegriffe der Kategorie nacheinander ab, bis die
Anzahl erreicht ist.

**2 · Auswählen**
Was nicht gebraucht wird, wird abgewählt:

| Aktion | Wie |
|---|---|
| Einzelnen Titel an/aus | Klick auf das Häkchen |
| Markierte Zeilen an/aus | `Leertaste` oder `Enter` |
| Alle / Keine / Umkehren | Knöpfe unter der Tabelle |
| Suchen in der Liste | Feld *Filter* — *Alle/Keine* wirken dann nur auf die gefilterten Zeilen |
| Sortieren | Klick auf die Spaltenüberschrift |
| Zeilen ganz entfernen | Markieren, dann *Entfernen* |

**3 · Herunterladen**
*Download starten*. Oben läuft die aktuelle Datei, darunter der
Gesamtfortschritt. *Abbrechen* stoppt nach der laufenden Datei.

> **Links aus Datei…** liest eine Textdatei mit einem Link pro Zeile ein
> (z.B. die alte `urls.txt`) und hängt sie an die Liste an.

---

## Einstellungen

Werden automatisch in `config/settings.json` gespeichert.

| Einstellung | Standard | Bedeutung |
|---|---|---|
| Ordner | `mp3\` | Zielordner für die MP3-Dateien |
| Bitrate | 192 | 128 / 192 / 256 / 320 kbps |
| Länge min/max | 60 / 900 s | Filtert Shorts und stundenlange Mixe aus der Suche (0 = aus) |
| Parallel | 2 | Gleichzeitige Downloads (1–8) — mehr als 3 provoziert Drosselung durch YouTube |
| Bereits geladene überspringen | an | Führt `downloaded_archive.txt` im Zielordner, lädt nichts doppelt |

---

## Eigene Kategorien

Knopf **Kategorien…** → anlegen, umbenennen, löschen, Suchbegriffe bearbeiten
(ein Begriff pro Zeile). Alles landet in `config/categories.json` und kann auch
direkt dort bearbeitet werden:

```json
{
  "Techno": ["techno 2025", "hard techno set", "melodic techno"],
  "Arabesque": ["arabesk şarkılar", "müslüm gürses", "damar arabesk"]
}
```

**Faustregel:** 10–15 Suchbegriffe pro Kategorie für 500 Links. Das Ziel wird
gleichmäßig auf die Begriffe verteilt; ist es früher erreicht, werden die
restlichen Begriffe gar nicht mehr abgefragt.

Mitgeliefert sind 14 Kategorien: Pop · Party · Disco · Techno · House ·
Turkish · Arabesque · Arabic · Balkan · Rap/HipHop · 80s/90s · Charts ·
Schlager · Rock.

---

## Wenn etwas nicht klappt

| Symptom | Ursache und Lösung |
|---|---|
| „FFmpeg wurde nicht im PATH gefunden" im Log | FFmpeg installieren, danach Terminal neu starten |
| Viele Fehlschläge, HTTP 429 | *Parallel* auf 1–2 senken |
| Nur stundenlange Mixe in der Liste | Maximale Länge senken, z.B. auf 600 s |
| Weniger Treffer als gewünscht | Mehr Suchbegriffe in der Kategorie, oder Längenfilter lockern |
| Ein Titel fehlt in den MP3s | `logs\failed.log` ansehen — dort steht Video-ID und Grund |
| Nichts wird geladen, obwohl Titel ausgewählt sind | *Bereits geladene überspringen* ist an und die Videos stehen schon im Archiv |
| Warnung „No supported JavaScript runtime" | Wird ausgefiltert. Falls Formate fehlen: `winget install DenoLand.Deno` |

---

## Projektstruktur

```
run_gui.py                 Einstiegspunkt der GUI
youtube_to_mp3.py          altes Script, lädt weiterhin stumpf alle urls.txt-Links
config/
  categories.json          Kategorien und ihre Suchbegriffe
  settings.json            gespeicherte Einstellungen
logs/failed.log            übersprungene Videos mit Grund
ytmp3/
  models.py                Datencontainer (Track, AppSettings, ProgressEvent)
  config.py                Laden und Speichern der JSON-Dateien
  search.py                Suche über ytsearchN:, Dedupe, Längenfilter
  downloader.py            Download + MP3-Konvertierung, Fortschritt, Fehler
  gui/
    app.py                 Hauptfenster, Thread-Anbindung
    results_view.py        Ergebnistabelle mit Häkchen-Spalte
    category_editor.py     Kategorie-Editor
```

Such- und Downloadmodul laufen auch ohne GUI:

```powershell
python -m ytmp3.search Techno 50      # Kategorie oder freier Suchbegriff
python -m ytmp3.downloader urls.txt   # Datei mit Links herunterladen
```

**Für Weiterentwicklung wichtig:** Suche und Download laufen in
Hintergrund-Threads und melden sich über eine `queue.Queue` zurück, die die GUI
alle 100 ms leert. Tkinter-Widgets dürfen ausschließlich aus dem Hauptthread
angefasst werden — sonst gibt es sporadische Abstürze.

---

## Hinweise

Das Programm braucht eine Internetverbindung.

Nutze die Software nur für Inhalte, zu deren Download du berechtigt bist, und
beachte das Urheberrecht sowie die Nutzungsbedingungen der jeweiligen Seite.
