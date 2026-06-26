# PDF Archive MVP für Windows

Lokaler PDF-Archivierungsassistent für Windows. Das Programm erkennt Barcodes, liest Text per PDF-Extraktion oder OCR, klassifiziert Dokumente mit einem lokalen Ollama-Modell und zeigt die Ergebnisse vor dem finalen Speichern in einem einfachen Review-Fenster.

Der aktuelle Standardprozess ist bewusst halbautomatisch: Die Software schlägt Datum, Barcode, Kategorie und Dateiname vor, der Benutzer bestätigt oder korrigiert die Werte, erst danach wird das Dokument final archiviert.

## Kundenstart

Nach dem Herunterladen oder Klonen des Projektordners:

1. `Install.cmd` per Doppelklick starten.
2. PDF-Dateien in den Ordner `Input` legen.
3. `Start.cmd` per Doppelklick starten.
4. Im Review-Fenster die erkannten Daten prüfen.
5. Mit `Übernehmen` das Dokument final speichern.

`Start.cmd` macht immer beides:

1. neue PDFs aus `Input` analysieren und in die Review-Warteschlange legen;
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

## Nutzung

PDF-Dateien werden in diesen Ordner gelegt:

```text
Input/
```

Danach:

```text
Start.cmd
```

Im Fenster werden pro Dokument angezeigt:

- Dokumentdatum;
- Barcode;
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
- JSON-Sidecar wird erstellt;
- XML-Sidecar wird erstellt, wenn `create_xml: true` gesetzt ist;
- PDF wird nach `Archive/JAHR/Kategorie` verschoben;
- Queue-Eintrag wird als bestätigt markiert.

## Ordnerstruktur

Beispiel:

```text
pdf-archive/
  Install.cmd
  Start.cmd
  Input/
    scan_001.pdf
  Archive/
    _Queue/
      review_queue.sqlite3
      pending/
      drafts/
    2026/
      Rechnung/
        2026-06-24_Rechnung_Stadtwerke_Rechnung_1234567890.pdf
        2026-06-24_Rechnung_Stadtwerke_Rechnung_1234567890.json
        2026-06-24_Rechnung_Stadtwerke_Rechnung_1234567890.xml
```

`Archive/_Queue` ist die interne Warteschlange für noch nicht bestätigte Dokumente.

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

## Kategorien

Die festen Kategorien stehen in `config.example.yml` im Abschnitt `categories`. Das Modell soll möglichst eine feste Kategorie wählen. Wenn keine Kategorie passt, darf eine neue Kategorie vorgeschlagen werden; diese wird im Review-Fenster angezeigt und kann vom Benutzer bestätigt oder geändert werden.

## Metadaten

Beim finalen Speichern werden unter anderem diese PDF-Metadaten geschrieben:

- `Barcode`
- `ArchiveId`
- `DocumentDate`
- `DocumentCategory`
- `DocumentCategoryName`
- `ArchiveReviewRequired`
- `ArchiveReviewApproved`
- `ArchiveReviewApprovedAt`
- `ArchiveProcessedAt`

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
- unklarer Brief ohne Barcode.

Erwartung: `Start.cmd` legt alle Dokumente in die Review-Warteschlange, öffnet das Fenster und speichert bestätigte Dokumente final unter `Archive/JAHR/Kategorie`.
