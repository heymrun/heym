# Converter

The **Converter** node converts data and files between formats without writing code. It is technology-neutral so more formats can be added over time. It converts CSV text and JSON rows in both directions, runs Tesseract OCR to pull text out of images and PDFs, and rewrites a stored file in another format.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.result` (parsed rows for `csvToJson`, CSV text for `jsonToCsv`, extracted text for `imageToText` / `pdfToText`, new file metadata for `fileConvert`) |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `conversion` | string | `csvToJson` (CSV text → array of row objects), `jsonToCsv` (array of objects/rows → CSV text), `imageToText` (OCR an image), `pdfToText` (OCR every selected PDF page), or `fileConvert` (rewrite a stored file in another format) |
| `source` | expression | The data to convert. Leave empty to use the node's first input |
| `delimiter` | string | Single-character field separator (default `,`) |
| `hasHeader` | boolean | `csvToJson` only — treat the first row as the header (default `true`) |
| `trimValues` | boolean | `csvToJson` only — strip whitespace around header names and cell values (default `true`) |
| `includeHeader` | boolean | `jsonToCsv` only — write a header row (default `true`) |
| `converterColumns` | string | `jsonToCsv` only — optional comma-separated column order |
| `converterFileId` | expression | File conversions — the Heym Drive file to read, e.g. `$Upload.file.id` |
| `converterTargetFormat` | string | `fileConvert` only — output format (`pdf`, `docx`, `html`, `md`, `txt`, `csv`, `epub`, `jpg`, `png`, `bmp`, `webp`) |
| `ocrLanguage` | string | OCR only — `auto` (default), a Tesseract code such as `tur`, or `custom` |
| `ocrLanguageCustom` | string | OCR only — language codes used when `ocrLanguage` is `custom`, e.g. `eng+tur` |
| `ocrEncoding` | string | OCR only — charset the text is normalized to (default `utf-8`) |
| `ocrNormalizeUnicode` | boolean | OCR only — apply NFC normalization (default `true`) |
| `ocrPsm` | string | OCR only — Tesseract page segmentation mode (default `3`) |
| `ocrDpi` | number | `pdfToText` only — page rasterization DPI (default `300`) |
| `ocrPageRange` | expression | `pdfToText` only — `3` or `2-5`. Empty means every page |

## Behavior

- **`csvToJson`** parses the source CSV text. With `hasHeader: true` each row becomes an object keyed by the header values; with `hasHeader: false` each row becomes an array of cell values. Quoted fields, embedded delimiters, and embedded newlines are handled per RFC 4180. A leading UTF-8 BOM (common in Excel exports) is stripped, and duplicate header names are made unique without overwriting a real column (`a, a, a_2` → `a`, `a_3`, `a_2`). Set `delimiter` to `\t` to parse tab-separated values.
- **`trimValues`** (default `true`) strips surrounding whitespace from header names and cell values, **including inside quoted fields** (`" padded "` → `padded`). RFC 4180 treats quoted whitespace as data, so set `trimValues: false` to preserve it exactly.
- **`jsonToCsv`** builds CSV text from an array of objects (or arrays). Column order is taken from `converterColumns` when provided, otherwise inferred from the first object's keys. Values containing the delimiter, quotes, or newlines are quoted automatically.
- **`imageToText`** runs Tesseract over a single image (PNG, JPEG, TIFF, WebP, BMP).
- **`pdfToText`** rasterizes each selected page at `ocrDpi` and recognizes it. Every page goes through OCR, so a digital PDF with a perfectly good text layer is still re-read from pixels. That keeps scanned and digital documents behaving identically, at the cost of speed, so narrow `ocrPageRange` on long files.
- **`fileConvert`** rewrites the source file in another format and stores the result as a **new** Drive file. The original is never modified. Documents go through pandoc, images through Pillow, and JSON to CSV through the Python csv writer. An image cannot become a document and a document cannot become an image; to read text out of an image use `imageToText`.

## Getting the file in

File conversions read from Heym Drive, not from a path or a URL, so the file has to be stored first. Three common chains:

- **[File upload trigger](./file-upload-trigger-node.md) → Converter** — point `converterFileId` at `$Upload.file.id`.
- **[Drive](./drive-node.md) (`downloadUrl`) → Converter** — fetch a remote file into Drive, then pass `$Download.id`.
- **[Agent](./agent-node.md) → Converter** — a skill that writes a file exposes it as `$reportAgent._generated_files[0].id`.

`converterFileId` also accepts a whole file object (`$Upload.file`) or a Heym download URL; the file id is pulled out of either. The file must be one you own or one a teammate shared with you.

## Languages

`auto` (the default) runs Tesseract's orientation-and-script detection first, then picks the best installed model for the detected script. Script models such as `Latin` or `Cyrillic` read every language written in that script, which is why auto handles a Turkish invoice and an English one without being told which is which.

Naming the language is still more accurate when you know it. Use a single code (`tur`), or join several with `+` (`eng+tur`) for mixed documents — more languages means slower and slightly noisier recognition, so keep the list short. Codes only work when the matching language data is installed on the backend; the node lists what is available when you pick a missing one.

Every Heym image ships `osd`, English, Turkish, German, French, Spanish, Italian, Portuguese, Dutch, Russian, Arabic, Simplified Chinese, Japanese, Korean, and the Latin, Cyrillic, Arabic, HanS, Japanese, and Hangul script models.

## Encoding

Recognized text is UTF-8 and keeps every character Tesseract produced. `ocrNormalizeUnicode` (on by default) applies NFC normalization, so a letter written as `s` plus a combining cedilla becomes a single `ş` — worth leaving on, because the two forms are not equal in comparisons or database lookups.

`ocrEncoding` matters only when something downstream cannot store the full Unicode range. Picking `cp1254` or `iso-8859-9` keeps Turkish text intact while guaranteeing the result fits that charset; `latin-1` and `ascii` are narrower and replace what they cannot represent with `?`. Leave it at `utf-8` unless a target system forces your hand.

## Output

`csvToJson` and `jsonToCsv` return `$label.result` and `$label.conversion`. OCR conversions add:

| Field | Description |
|-------|-------------|
| `$label.result` | The full extracted text, pages joined by a blank line |
| `$label.language` | The model that actually ran (useful to see what `auto` chose) |
| `$label.encoding` | The charset the text was normalized to |
| `$label.page_count` | Number of pages recognized |
| `$label.pages` | Array of `{ page, text }` for per-page handling |
| `$label.file` | `{ id, filename, mime_type, size_bytes }` of the source file |

`fileConvert` returns the new file instead:

| Field | Description |
|-------|-------------|
| `$label.id` | UUID of the newly stored file |
| `$label.filename` | Converted filename, base name kept and extension swapped |
| `$label.mime_type` | MIME type of the new file |
| `$label.size_bytes` | Size of the new file |
| `$label.download_url` | Drive download URL for the new file |
| `$label.source_file` | Metadata of the file that was converted |

## Example

```json
{
  "type": "converter",
  "data": {
    "label": "toRows",
    "conversion": "csvToJson",
    "source": "$userInput.body.text",
    "delimiter": ",",
    "hasHeader": true
  }
}
```

For input `name,age\nAda,36`, downstream nodes access the parsed rows via `$toRows.result` (`[{ "name": "Ada", "age": "36" }]`).

Reading a scanned invoice uploaded through a file upload trigger:

```json
{
  "type": "converter",
  "data": {
    "label": "readInvoice",
    "conversion": "pdfToText",
    "converterFileId": "$Upload.file.id",
    "ocrLanguage": "tur",
    "ocrEncoding": "utf-8",
    "ocrDpi": 300,
    "ocrPageRange": "1-3"
  }
}
```

An [Agent](./agent-node.md) or [LLM](./llm-node.md) node downstream can then pull structured fields out of `$readInvoice.result`.

Turning an agent's markdown report into a PDF:

```json
{
  "type": "converter",
  "data": {
    "label": "convertDoc",
    "conversion": "fileConvert",
    "converterFileId": "$reportAgent._generated_files[0].id",
    "converterTargetFormat": "pdf"
  }
}
```

Downstream nodes read `$convertDoc.download_url` to share the PDF, or `$convertDoc.id` to keep working with it in [Drive](./drive-node.md).

## Requirements

OCR shells out to `tesseract` and poppler's `pdftoppm`, and document conversion uses pandoc. All three ship with every way of running Heym, including `run.sh`, docker-compose, and the single release image, so there is nothing to configure. Page limits, timeouts, and the maximum DPI are fixed platform values rather than settings.

## Related

- [Set](./set-node.md) – Transform and map individual fields
- [JSON output mapper](./json-output-mapper-node.md) – Build a JSON response object
- [File upload trigger](./file-upload-trigger-node.md) – Accept a file into Heym Drive
- [Drive](./drive-node.md) – Store, fetch, and share files
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Expression DSL](../reference/expression-dsl.md) – Functions and syntax
