# PDF Archive MVP для Windows

Локальный MVP для автоматической обработки PDF:

- распознает штрихкод в правом верхнем углу первой страницы;
- извлекает текст из PDF или делает OCR через Tesseract;
- классифицирует документ локальной LLM через Ollama;
- записывает штрихкод и другие поля в PDF metadata;
- раскладывает PDF по папкам `Archive/ГОД/Категория`;
- создает рядом `.json` и, по умолчанию, `.xml`;
- отправляет сомнительные документы в `_Review`.

## Быстрый запуск на Windows

Установите Python 3.11 или 3.12, затем в PowerShell:

```powershell
cd C:\path\to\pdf_archive_mvp
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Установите Ollama и легкую стартовую модель:

```powershell
ollama pull gemma3:4b
```

Если классификация окажется слишком слабой, можно позже подняться до `gemma3:12b`: поменяйте модель в `config.example.yml` и выполните:

```powershell
ollama pull gemma3:12b
```

Для OCR установите Tesseract для Windows, например сборку UB Mannheim, и добавьте `tesseract.exe` в `PATH`. Для немецких и английских документов нужны языки `deu` и `eng`.

## Использование

Положите PDF-файлы в папку `Input`, затем сначала проверьте план:

```powershell
python archive_pdf.py --dry-run
```

После проверки запустите реальную обработку:

```powershell
python archive_pdf.py
```

Без LLM, только keyword fallback:

```powershell
python archive_pdf.py --no-llm
```

С другими папками:

```powershell
python archive_pdf.py --input "D:\Scan\Input" --archive "D:\Dokumente\Archiv"
```

## Результат

Пример структуры:

```text
Archive/
  2026/
    Energie/
      2026-06-24_Energie_Stadtwerke_Rechnung_1234567890.pdf
      2026-06-24_Energie_Stadtwerke_Rechnung_1234567890.json
      2026-06-24_Energie_Stadtwerke_Rechnung_1234567890.xml
    _Review/
      Rechnung/
        undated_Rechnung_Dokument.pdf
```

Документ попадает в `_Review`, если:

- не найден штрихкод;
- не найдена дата;
- уверенность классификации ниже `confidence_review_threshold`;
- LLM создала новую категорию.

## PDF metadata

В PDF записываются поля:

- `Barcode`
- `ArchiveId`
- `DocumentDate`
- `DocumentCategory`
- `DocumentCategoryName`
- `ArchiveProcessedAt`

Главным источником структурированных данных является `.json`; PDF metadata нужны для дополнительной совместимости с поиском и DMS-системами.

## Настройка категорий

Фиксированные категории находятся в `config.example.yml` в секции `categories`.

LLM получает список категорий и должна выбрать одну из них. Если ничего не подходит и `allow_ai_categories: true`, она может предложить новую категорию. Такие документы специально отправляются в `_Review`, чтобы категориальный справочник не разрастался случайно.

## Практические советы

- Если штрихкод не находится, подстройте блок `barcode` в `config.example.yml`.
- Если OCR работает медленно, уменьшите `ocr.dpi` или `max_pages_for_text`.
- Если документы в основном сканированные, держите Tesseract установленным и проверьте `deu+eng`.
- Если приватность критична, оставьте `include_extracted_text: false`; в JSON будет только короткий фрагмент текста.
