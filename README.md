# PDF Archive MVP für Windows

Lokaler MVP zur automatischen Verarbeitung und Archivierung von PDF-Dokumenten.

Der Workflow:

- erkennt Barcodes im rechten oberen Bereich der ersten PDF-Seite;
- extrahiert vorhandenen PDF-Text oder nutzt OCR über Tesseract;
- bereitet Scanbilder für OCR vor, inklusive Autokontrast, optionalem Drehen und Deskew;
- klassifiziert Dokumente mit einem lokalen LLM über Ollama;
- schreibt Barcode und weitere Felder in die PDF-Metadaten;
- legt Dokumente unter `Archive/JAHR/Kategorie` ab;
- erzeugt zu jeder PDF eine `.json`-Datei und optional eine `.xml`-Datei;
- verschiebt unsichere Dokumente nach `_Review`.

## Schnellstart unter Windows

Für Kunden ist der einfache Weg:

1. Projektordner öffnen.
2. `Install_Windows.cmd` per Doppelklick starten.
3. PDF-Dateien in `Input` legen.
4. `Process_To_Queue.cmd` per Doppelklick starten.
5. `Review_GUI.cmd` per Doppelklick starten und Dokumente mit `Übernehmen` bestätigen.

`Install_Windows.cmd` versucht automatisch:

- Python 3.12 über `winget` zu installieren, falls Python fehlt;
- die virtuelle Umgebung `.venv` zu erstellen;
- alle Python-Abhängigkeiten aus `requirements.txt` zu installieren;
- Tesseract OCR zu prüfen beziehungsweise über `winget` zu installieren;
- Ollama zu prüfen beziehungsweise über `winget` zu installieren;
- das Modell `gemma3:4b` zu laden.

Wenn `winget` oder Firmenrichtlinien eine automatische Installation blockieren, zeigt das Skript die nötigen manuellen Schritte an. Danach `Install_Windows.cmd` einfach erneut starten.

Manuelle Installation für technische Nutzer:

Python 3.11 oder 3.12 installieren, dann in PowerShell:

```powershell
cd C:\path\to\pdf_archive_mvp
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Ollama installieren und das leichte Startmodell laden:

```powershell
ollama pull gemma3:4b
```

Falls die Klassifikation zu schwach ist, kann später auf `gemma3:12b` gewechselt werden. Dazu in `config.example.yml` das Modell ändern und ausführen:

```powershell
ollama pull gemma3:12b
```

Für OCR wird Tesseract benötigt. Unter Windows eignet sich zum Beispiel der UB-Mannheim-Build. Danach sollte `tesseract.exe` im `PATH` verfügbar sein. Für deutsche und englische Dokumente werden die Sprachpakete `deu` und `eng` benötigt.

## Verwendung

PDF-Dateien in den Ordner `Input` legen.

Zuerst einen Probelauf ohne Schreiben oder Verschieben ausführen:

```powershell
python archive_pdf.py --dry-run
```

Danach die echte Verarbeitung starten:

```powershell
python archive_pdf.py
```

Alle erkannten Daten zuerst in eine manuelle Review-Warteschlange legen:

```powershell
python archive_pdf.py --queue-review
```

Danach das einfache Windows-Formular für Prüfung und Umbenennung öffnen:

```powershell
python archive_pdf.py --review-gui
```

Alternativ kann das Formular direkt gestartet werden:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\review_gui.ps1 -Config .\config.example.yml
```

Ohne LLM, nur mit Keyword-Fallback:

```powershell
python archive_pdf.py --no-llm
```

Mit eigenen Ordnern:

```powershell
python archive_pdf.py --input "D:\Scan\Input" --archive "D:\Dokumente\Archiv"
```

## Ergebnis

Beispielstruktur:

```text
Archive/
  _Queue/
    review_queue.sqlite3
    pending/
      scan_12345678.pdf
    drafts/
      12345678-....json
  2026/
    Energie/
      2026-06-24_Energie_Stadtwerke_Rechnung_1234567890.pdf
      2026-06-24_Energie_Stadtwerke_Rechnung_1234567890.json
      2026-06-24_Energie_Stadtwerke_Rechnung_1234567890.xml
    _Review/
      Rechnung/
        undated_Rechnung_Dokument.pdf
```

## Manuelle Review-Warteschlange

Der Modus `--queue-review` analysiert PDF-Dateien wie gewohnt, archiviert sie aber noch nicht final. Stattdessen werden PDF und erkannte Felder in `Archive/_Queue` abgelegt. Das ist für den Startbetrieb sinnvoll, wenn jede Entscheidung vor dem finalen Speichern noch von einem Menschen bestätigt werden soll.

Das Windows-Formular `tools/review_gui.ps1` zeigt pro Dokument:

- erkanntes Dokumentdatum;
- Barcode;
- Kategorie;
- Absender;
- Titel;
- Kurztext für den Dateinamen;
- Review-Gründe und Textauszug.

Die Felder sind vorbefüllt, können aber manuell korrigiert werden. Erst nach `Übernehmen` passiert die finale Archivierung:

- der finale Dateiname wird gebildet;
- die PDF-Metadaten werden geschrieben;
- JSON und optional XML werden erzeugt;
- die PDF wird nach `Archive/JAHR/Kategorie` verschoben;
- der Queue-Eintrag wird als `approved` markiert.

Für Diagnose oder eigene Integrationen kann die Queue auch als JSON ausgegeben werden:

```powershell
python archive_pdf.py --list-review-queue --json
```

Ein Dokument landet in `_Review`, wenn:

- kein Barcode erkannt wurde;
- kein Dokumentdatum erkannt wurde;
- die erkannte Datumsangabe nicht durch extrahierten Text bestätigt wird;
- die Klassifikationssicherheit unter `confidence_review_threshold` liegt;
- das LLM eine neue Kategorie vorgeschlagen hat.

## PDF-Metadaten

In die PDF werden folgende Felder geschrieben:

- `Barcode`
- `ArchiveId`
- `DocumentDate`
- `DocumentCategory`
- `DocumentCategoryName`
- `ArchiveReviewRequired`
- `ArchiveReviewReasons`
- `ArchiveProcessedAt`

Die `.json`-Datei ist die wichtigste strukturierte Datenquelle. Die PDF-Metadaten dienen vor allem der zusätzlichen Kompatibilität mit Suche, DMS-Systemen oder späteren Importen.

## JSON- und XML-Sidecars

Zu jedem verarbeiteten Dokument wird eine JSON-Datei erzeugt. Standardmäßig wird zusätzlich XML geschrieben.

Die Sidecar-Dateien enthalten unter anderem:

- Barcode und erkannte Barcode-Variante;
- Dokumentdatum;
- Zielpfad und finaler Dateiname;
- Kategorie, Kategoriequelle und Review-Status;
- Absender, Titel und Kurzbeschreibung;
- LLM-Modell, LLM-Status und Klassifikationsbegründung;
- OCR- beziehungsweise Textextraktionsinformationen;
- OCR-Preprocessing-Schritte pro Seite;
- Datumsvalidierung und Review-Gründe;
- kurze Textexzerpte.

Ob der vollständige extrahierte Text gespeichert wird, steuert `include_extracted_text` in `config.example.yml`.

## Kategorien

Die festen Kategorien stehen in `config.example.yml` im Abschnitt `categories`.

Das LLM erhält diesen Kategorienkatalog und soll möglichst eine feste Kategorie wählen. Wenn keine Kategorie passt und `allow_ai_categories: true` gesetzt ist, darf das LLM eine neue Kategorie vorschlagen. Solche Dokumente werden bewusst nach `_Review` verschoben, damit der Kategorienkatalog nicht unkontrolliert wächst.

## Wichtige Einstellungen

Barcode-Erkennung:

```yaml
barcode:
  left_ratio: 0.56
  top_ratio: 0.00
  width_ratio: 0.44
  height_ratio: 0.30
```

Diese Werte beschreiben den rechten oberen Ausschnitt der ersten Seite. Wenn Barcodes nicht erkannt werden, sollte dieser Bereich angepasst werden.

OCR:

```yaml
ocr:
  enabled: true
  languages: deu+eng
  dpi: 260
  tesseract_config: "--oem 1 --psm 6"
  preprocess: true
  auto_rotate: true
  deskew: true
  max_deskew_degrees: 4.0
  contrast: 1.35
  sharpness: 1.15
  threshold: null
```

`preprocess` aktiviert die Bildvorbereitung für gescannte Dokumente. Dabei werden Seiten in Graustufen umgewandelt, per Autokontrast verbessert, leicht geschärft und optional gedreht beziehungsweise entzerrt. `threshold` sollte nur gesetzt werden, wenn sehr schlechte Scans aggressiv binarisiert werden müssen, zum Beispiel mit einem Wert zwischen `170` und `210`.

LLM:

```yaml
llm:
  enabled: true
  provider: ollama
  base_url: http://localhost:11434
  model: gemma3:4b
```

Datumsvalidierung:

```yaml
settings:
  min_document_year: 1990
  max_future_years: 1
  require_date_in_text: true
```

Wenn `require_date_in_text` aktiv ist, wird ein vom LLM vorgeschlagenes Datum nur akzeptiert, wenn es auch im extrahierten Text als Kandidat gefunden wurde. Das reduziert Halluzinationen bei schlechten Scans.

## Testen

Für einen sicheren Test sollten synthetische PDFs verwendet werden, nicht echte private Dokumente.

Empfohlene Testfälle:

- Rechnung eines Energieversorgers mit Barcode;
- Kontoauszug mit Barcode;
- medizinischer Laborbericht mit Barcode;
- unklarer Testbrief ohne Barcode.

Erwartung:

- die ersten drei Dokumente werden nach `Archive/JAHR/Kategorie` verschoben;
- das Dokument ohne Barcode landet in `_Review`;
- zu jedem Dokument entstehen `.json` und `.xml`;
- die PDF-Metadaten enthalten `Barcode`, `DocumentDate` und `DocumentCategory`.
- unsichere Dokumente enthalten im JSON `review_reasons` und `date_validation`.

## Praktische Hinweise

- Wenn Barcodes nicht gefunden werden, den Block `barcode` in `config.example.yml` anpassen.
- Wenn OCR zu langsam ist, `ocr.dpi` oder `max_pages_for_text` reduzieren.
- Wenn Dokumente überwiegend gescannt sind, Tesseract installiert halten und `deu+eng` prüfen.
- Wenn viele Dokumente in `_Review` landen, zuerst `text_length`, `ocr_pages` und `review_reasons` in den JSON-Dateien prüfen.
- Wenn Datenschutz besonders wichtig ist, `include_extracted_text: false` lassen. Dann wird nur ein kurzer Textauszug gespeichert.
- Für den ersten Funktionstest ist `--no-llm` nützlich, weil damit Barcode, Datum, Ordnerstruktur, Metadaten und Sidecars unabhängig von Ollama geprüft werden können.
