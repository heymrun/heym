# File Analysis

File analysis lets Chat, the [Agent node](../nodes/agent-node.md) and the [Code node](../nodes/code-node.md) open large files from [Drive](./drive.md) in an isolated Python sandbox. PDFs, spreadsheets, CSV, DOCX and JSON are inspected first and then read selectively, so a 200-page contract or a workbook with a million rows never has to fit into a model's context.

## How it works

Every call runs in a fresh container with no network access. The files it needs are copied in read-only, the code runs, and the container is removed. A small working folder survives between calls of the same session, so a later step can start from a result an earlier step saved.

| Path | What it holds |
|------|---------------|
| `/input` | The Drive files of this session, read-only |
| `/work` | Scratch space that persists for the session, for example `/work/sales.pkl` |
| `/work/out` | Files written here are saved to Drive after the call and returned as links |

The sandbox has pandas, openpyxl, xlrd, pdfplumber, pypdf, python-docx and langdetect installed, plus the Tesseract OCR the [Converter node](../nodes/converter-node.md) uses, so scanned PDFs are read in the sandbox too.

## Tools

The model works with three tools, plus a fourth in Chat:

| Tool | What it does |
|------|--------------|
| `list_files` | Lists the Drive files you can open (yours and those shared with your teams): name, type, size, date |
| `inspect_file` | Returns a file's type, metadata and structure with a short sample |
| `run_python` | Runs Python on the files it names and returns what the code prints |
| `clear_workspace` | Chat only: deletes the conversation's working folder |

`inspect_file` reads only what a summary needs:

| Type | Summary |
|------|---------|
| PDF | Page count, title and author, whether text can be extracted, language, page sizes, first page text and tables. A scanned PDF without a text layer has its first pages read with OCR (up to 5 per call) |
| XLSX / XLS | Sheets with row and column counts, the real header row (titles and notes above it are listed separately), header names and types, a ready pandas `read_hint`, named ranges, first rows, last filled row. A summary sheet of labels and values comes back as label/value pairs with each value's cell |
| CSV / TSV | Encoding, delimiter, row count, columns with types and empty-value ratios, first rows |
| DOCX | Heading outline, tables, word and character counts, author and dates |
| JSON | Root type, keys, array length, nesting depth, sample records |

Ask for one sheet with `sheet`, a page range with `pages` (for example `1-3,7`), or exact CSV counts with `full`.

Inside `run_python`, open a file with the `heym_files` module. `heym_ocr.pdf_to_text(data, page_range="3-4").text` reads scanned pages:

```python
import heym_files
import pandas as pd

df = pd.read_excel(heym_files.path("q3.xlsx"), sheet_name="Summary", usecols=["Region", "Amount"])
print(df.groupby("Region").Amount.sum())
df.to_csv(f"{heym_files.out_dir()}/by-region.csv", index=False)
```

## In Chat

Attach a PDF, spreadsheet, DOCX, CSV or JSON file in the [Chat tab](../tabs/chat-tab.md), Heym Work's Chat or through the MCP `heym_chat` tool. The file is stored in your Drive and only its name and id go into the message. Chat inspects it, reads the part your question needs, and answers with tables or short extracts. You can also ask about a file already in Drive by name.

When Chat builds a workflow around a file, it inspects the real file first, so sheet, column and page names in the workflow match it. The workflow starts with a File Upload trigger. Fixed extraction becomes a Code node with **Files** set; open questions about documents that vary become an Agent that receives the file id in its message. The test run hands your file to the trigger, the way an upload arrives, and running a workflow from Chat with an attached file does the same.

A conversation keeps its working folder between messages, so a follow-up such as "now add a column for Q4" starts from the results already computed. The folder is deleted when you delete the conversation, when you ask Chat to clear it, or after 30 days without use. Your Drive files stay where they are.

## In workflows

A run opens only its own files: those uploaded through the workflow's [File Upload trigger](../nodes/file-upload-trigger-node.md) and those its nodes wrote to Drive. A sub-workflow also opens its parent's. A Drive file id typed into an input or put together in a prompt opens nothing, so nobody can add a node to a workflow to read the owner's Drive.

- **Agent node**: there is nothing to switch on. When the agent's input or message carries a file of the run, it gets the tools above for those files; its working folder is deleted when the node finishes. Pass the file id in the message, for example `Summarize the risks in $Upload.file.id`.
- **Code node**: set **Files** to an expression such as `$Upload.file.id`. The files are mounted for that run, listed in `params.files`, and anything written to `heym_files.out_dir()` comes back in `$label.files`.

## Limits

| Limit | Value |
|-------|-------|
| Memory per call | 2 GB |
| Time per call | 120 seconds |
| Working folder per session | 2 GB |
| Output files per call | 20, up to 100 MB each |
| Printed output returned to the model | 20,000 characters |
| Files per call | 20 |

Read large files in chunks or with `nrows` and `usecols`, and save intermediate results under `/work`.

## Security

- The sandbox has no network, no access to Heym's settings or secrets, and runs as an unprivileged user.
- Files are parsed only inside the sandbox.
- In Chat, access follows Drive: you open files you own and files shared with a team you belong to. In a workflow run, only the run's own files open. Every file is checked again on each call, so a removed share takes effect at the next call.
- Opening a file in Chat is recorded in the audit log.
- File contents are treated as data. Instructions written inside a file are not followed.

An Agent reads the contents of the files it receives. When the same agent also reads outside input (mail, chat, webhooks) and has tools that send data out, a crafted message could make it share those contents. Keep those agents narrow, or add a [human review](./human-in-the-loop.md) step before anything is sent.

## Requirements

File analysis needs Docker on the Heym instance, like the Code node. Runs that read Drive files run on the main instance of a [cluster](./cluster.md).

## Related

- [Drive](./drive.md)
- [Code node](../nodes/code-node.md)
- [Agent node](../nodes/agent-node.md)
- [Chat tab](../tabs/chat-tab.md)
