# PDF Archive MVP für Windows

Lokaler PDF-Archivierungsassistent für Windows. Das Programm erkennt Barcodes, liest Text per PDF-Extraktion oder OCR, klassifiziert Dokumente mit einem lokalen Ollama-Modell und speichert die Analyse als JSON-Sidecar. Danach kann die Post-Processing-Stufe diese Metadaten prüfen, PDF-Metadaten schreiben und das Dokument final archivieren.

Der aktuelle Standardprozess ist bewusst halbautomatisch: Die Software schlägt Datum, Archivcode, Barcode, Dokumenttyp, Kategorie und Dateiname vor, der Benutzer bestätigt oder korrigiert die Werte, erst danach wird das Dokument final archiviert.

Die Architektur braucht keine Datenbank. Der wichtigste Vertrag zwischen Analyse, Review und Post-Processing ist eine Datei neben dem PDF:

```text
Dokument.pdf
Dokument.pdf.json
```

## Kundenstart

Nach dem Herunterladen oder Klonen des Projektordners:

1. `Install.cmd` per Doppelklick starten.
2. PDF-Dateien in den Ordner `Input` legen.
3. `Start.cmd` per Doppelklick starten.
4. Im Review-Fenster die erkannten Daten prüfen.
5. Mit `Übernehmen` das Dokument final speichern.

`Start.cmd` macht immer beides:

1. neue PDFs aus `Input` analysieren und als PDF+JSON-Sidecar-Paare in die Review-Warteschlange legen;
2. direkt danach das Review-Fenster öffnen.

## Installation

`Install.cmd` startet `tools/install_windows.ps1` und versucht automatisch:

- Python 3.12 zu finden oder über `winget` zu installieren;
- die virtuelle Umgebung `.venv` zu erstellen;
- Python-Abhängigkeiten aus `requirements.txt` zu installieren;
- Tesseract OCR zu prüfen oder über `winget` zu installieren;
- Ollama zu prüfen oder über `winget` zu installieren;
- das lokale Modell `gemma3:4b` zu laden;
- die Ordner `Input` und `Archive` anzulegen.

Wenn `winget` durch Windows- oder Firmenrichtlinien blockiert ist, zeigt das Skript die manuellen Schritte an. Danach `Install.cmd` erneut starten.

### Hinweis für Windows ARM64

Auf Windows ARM64, zum Beispiel in Parallels auf Apple Silicon, verwendet das Setup absichtlich **x64 Python** statt nativem ARM64 Python. Einige benötigte PDF-Pakete liefern für Windows ARM64 keine fertigen Binärpakete. Mit ARM64 Python würde `pip` versuchen, Pakete wie `PyMuPDF` lokal mit Visual Studio zu kompilieren.

Wenn die Installation vorher mit `PyMuPDF` oder `Preparing metadata (pyproject.toml)` fehlgeschlagen ist:

```powershell
git pull
Install.cmd
```

Das Setup erkennt eine vorhandene ungeeignete `.venv` und erstellt sie mit x64 Python neu.

## Nutzung

PDF-Dateien werden in diesen Ordner gelegt:

```text
Input/
```

Optional können Dokumente nach Herkunft getrennt werden:

```text
Input/
  Paper/
    scan_mit_barcode.pdf
  Digital/
    digitale_rechnung.pdf
```

- `Input/Paper`: Papierdokumente mit physischem Original. Der Code128-Barcode oben rechts ist Pflicht und wird als `ArchiveCode` verwendet.
- `Input/Digital`: rein digitale Dokumente. Ein Barcode ist nicht nötig; die Software vergibt automatisch einen Code wie `D-2026-000001`.
- Direkt in `Input`: automatische Erkennung. Mit Barcode wird das Dokument als `paper_scan` behandelt, ohne Barcode als `digital`.

Danach:

```text
Start.cmd
```

Im Fenster werden pro Dokument angezeigt:

- Dokumentdatum;
- Barcode;
- Archivcode;
- Dokumenttyp;
- Kategorie;
- neue Kategorie, falls keine bestehende Kategorie passt;
- Absender;
- Titel;
- Kurztext für den Dateinamen;
- Review-Gründe;
- Textauszug.

Alle Felder können manuell geändert werden. Nach `Übernehmen` passiert die finale Archivierung:

- PDF-Dateiname wird neu gebildet;
- PDF-Metadaten werden geschrieben;
- finaler JSON-Sidecar `*.pdf.json` wird neben dem PDF erstellt;
- finaler XML-Sidecar `*.pdf.xml` wird erstellt, wenn `create_xml: true` gesetzt ist;
- PDF wird nach `Archive/JAHR/Kategorie` verschoben;
- der Review-Sidecar wird als erledigte JSON-Auditkopie unter `Archive/_Queue/completed` abgelegt.

## Ordnerstruktur

Beispiel:

```text
pdf-archive/
  Install.cmd
  Start.cmd
  Input/
    Paper/
      scan_001.pdf
    Digital/
      invoice_email.pdf
  Archive/
    _archive_code_counters.json
    _Queue/
      pending/
        scan_001_9f3a1c2b.pdf
        scan_001_9f3a1c2b.pdf.json
      completed/
        9f3a1c2b-....json
    2026/
      Rechnung/
        2026-06-24_Rechnung_Stadtwerke_Rechnung_P-2026-000123.pdf
        2026-06-24_Rechnung_Stadtwerke_Rechnung_P-2026-000123.pdf.json
        2026-06-24_Rechnung_Stadtwerke_Rechnung_P-2026-000123.pdf.xml
```

`Archive/_Queue/pending` enthält noch nicht bestätigte Dokumente als echte PDF+JSON-Paare. Das JSON ist die Analyseausgabe und kann auch von anderen Programmen gelesen oder verändert werden. Beim Bestätigen liest das Post-Processing dieses JSON, schreibt die endgültigen Dateien in den Archivordner und legt eine erledigte Auditkopie unter `Archive/_Queue/completed` ab.

Die alte SQLite-Warteschlange wird nicht mehr verwendet. Falls aus einer früheren Version noch `Archive/_Queue/review_queue.sqlite3` existiert, werden pending Einträge beim nächsten Start automatisch in JSON-Sidecars migriert.

## Lokale KI

Die Klassifikation läuft lokal über Ollama. Standardmodell:

```yaml
llm:
  provider: ollama
  base_url: http://localhost:11434
  model: gemma3:4b
```

Wenn die Qualität später nicht reicht, kann in `config.example.yml` ein größeres Modell eingetragen werden, zum Beispiel `gemma3:12b`. Danach muss das Modell lokal geladen werden:

```powershell
ollama pull gemma3:12b
```

## OCR

Für gescannte PDFs wird Tesseract verwendet. Empfohlen ist der UB-Mannheim-Build für Windows. Die Sprachen `deu` und `eng` sollten verfügbar sein.

Wichtige OCR-Einstellungen stehen in `config.example.yml`:

```yaml
ocr:
  enabled: true
  languages: deu+eng
  dpi: 260
  preprocess: true
  auto_rotate: true
  deskew: true
```

## Barcode-Erkennung

Der Barcode wird zuerst im rechten oberen Bereich der ersten Seite gesucht. Danach wird als Fallback die ganze erste Seite geprüft.

Der Ausschnitt ist konfigurierbar:

```yaml
barcode:
  left_ratio: 0.56
  top_ratio: 0.00
  width_ratio: 0.44
  height_ratio: 0.30
```

Wenn Barcodes nicht zuverlässig erkannt werden, sollte dieser Bereich an das echte Scanlayout angepasst werden.

## Archivcode

Der `ArchiveCode` ist die gemeinsame Suchnummer für Papier und digitale Dokumente.

- Für Papierdokumente ist der gelesene Barcode der `ArchiveCode`, zum Beispiel `P-2026-000123`.
- Für digitale Dokumente ohne Barcode vergibt die Software automatisch eine laufende Nummer, zum Beispiel `D-2026-000001`.
- Der `ArchiveCode` wird in Dateiname, JSON, XML und PDF-Metadaten geschrieben.

Die Einstellungen stehen in `config.example.yml`:

```yaml
archive_code:
  enabled: true
  paper_prefix: P
  digital_prefix: D
  number_width: 6
  counter_file: _archive_code_counters.json
  default_source_type: auto
  paper_input_folder: Paper
  digital_input_folder: Digital
  require_barcode_for_paper: true
```

Damit kann ein Papierdokument später über den Barcode in der physischen Mappe gefunden werden. Umgekehrt kann der Barcode vom Papierdokument als Suchbegriff im digitalen Archiv verwendet werden. Digitale Dokumente ohne Papieroriginal bleiben über ihren `D-*`-Archivcode auffindbar.

## Kategorien

Die festen Kategorien stehen in `config.example.yml` im Abschnitt `categories`. Das Modell soll möglichst eine feste Kategorie wählen. Wenn keine Kategorie passt, darf eine neue Kategorie vorgeschlagen werden; diese wird im Review-Fenster angezeigt und kann vom Benutzer bestätigt oder geändert werden.

## Metadaten

Beim finalen Speichern werden unter anderem diese PDF-Metadaten geschrieben:

- `Barcode`
- `ArchiveCode`
- `ArchiveId`
- `ArchiveSourceType`
- `ArchivePhysicalDocument`
- `DocumentDate`
- `DocumentCategory`
- `DocumentCategoryName`
- `ArchiveReviewRequired`
- `ArchiveReviewApproved`
- `ArchiveReviewApprovedAt`
- `ArchiveProcessedAt`

Die gleichen Werte stehen zusätzlich im JSON-Sidecar. Dadurch kann eine andere Anwendung die JSON-Datei lesen, eigene PDF-Eigenschaften schreiben, andere Umbenennungsregeln anwenden oder eine spätere KI-Version austauschen, ohne den Rest des Workflows neu zu bauen.

## CLI-Stufen

Analyse ohne finale Archivierung:

```powershell
python archive_pdf.py --analyze-only
```

Das ist identisch zu `--queue-review` und erzeugt in `Archive/_Queue/pending` PDF+JSON-Paare.

Review-Liste als JSON:

```powershell
python archive_pdf.py --list-review-queue --json
```

Post-Processing eines bestätigten Dokuments:

```powershell
python archive_pdf.py --approve-review <ID> --review-date 2026-06-24 --review-category-id invoice
```

Zusätzlich entstehen strukturierte `.json`- und optional `.xml`-Dateien.

## Technische Befehle

Für Diagnose oder manuelle Nutzung kann das Programm auch direkt über Python gestartet werden.

Queue füllen:

```powershell
.\.venv\Scripts\python.exe archive_pdf.py --queue-review
```

Review-Fenster öffnen:

```powershell
.\.venv\Scripts\python.exe archive_pdf.py --review-gui
```

Queue als JSON anzeigen:

```powershell
.\.venv\Scripts\python.exe archive_pdf.py --list-review-queue --json
```

Ohne LLM testen:

```powershell
.\.venv\Scripts\python.exe archive_pdf.py --no-llm --queue-review
```

Projekt manuell aktualisieren:

```powershell
git pull
```

## Testempfehlung

Für den ersten Test keine echten Kundendokumente verwenden. Geeignet sind synthetische PDFs:

- Rechnung mit Barcode;
- Kontoauszug mit Barcode;
- Arzt- oder Laborbericht mit Barcode;
- digitale Rechnung ohne Barcode;
- unklarer Brief ohne Barcode.

Erwartung: `Start.cmd` legt alle Dokumente in die Review-Warteschlange, öffnet das Fenster und speichert bestätigte Dokumente final unter `Archive/JAHR/Kategorie`.
