# File Generation

Skills can generate files (PDF, DOCX, CSV, images, etc.) during execution. Generated files are automatically stored and made available for download.

## How It Works

When a skill runs, Heym creates an `_output_files/` directory in the skill's execution environment. The path is available as the `_OUTPUT_DIR` environment variable.

Any file written to this directory (except files starting with `_`) is captured after the skill completes, stored in the file system, and a download link is generated automatically.

## Writing Files in a Skill

```python
import os
import json
import sys
import csv

args = json.load(sys.stdin)
output_dir = os.environ.get("_OUTPUT_DIR", ".")

# Generate a CSV
csv_path = os.path.join(output_dir, "report.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Name", "Value"])
    writer.writerow(["Revenue", args.get("revenue", 0)])
    writer.writerow(["Users", args.get("users", 0)])

print(json.dumps({"status": "Report generated"}))
```

## PDF Generation

The `reportlab` library is available for PDF generation:

```python
import os
import json
import sys
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

args = json.load(sys.stdin)
output_dir = os.environ.get("_OUTPUT_DIR", ".")

pdf_path = os.path.join(output_dir, "invoice.pdf")
c = canvas.Canvas(pdf_path, pagesize=A4)
c.drawString(100, 750, f"Invoice for {args.get('customer', 'Unknown')}")
c.drawString(100, 730, f"Amount: ${args.get('amount', 0)}")
c.save()

print(json.dumps({"status": "Invoice generated"}))
```

## DOCX Generation

The `python-docx` library is available:

```python
import os
import json
import sys
from docx import Document

args = json.load(sys.stdin)
output_dir = os.environ.get("_OUTPUT_DIR", ".")

doc = Document()
doc.add_heading(args.get("title", "Report"), level=1)
doc.add_paragraph(args.get("content", ""))
doc.save(os.path.join(output_dir, "report.docx"))

print(json.dumps({"status": "Document generated"}))
```

## Multiple Files

Skills can generate multiple files in a single execution:

```python
import os
import json
import sys
import csv

args = json.load(sys.stdin)
output_dir = os.environ.get("_OUTPUT_DIR", ".")

# Generate CSV
with open(os.path.join(output_dir, "data.csv"), "w") as f:
    writer = csv.writer(f)
    writer.writerow(["col1", "col2"])
    writer.writerow(["val1", "val2"])

# Generate text summary
with open(os.path.join(output_dir, "summary.txt"), "w") as f:
    f.write("Summary of the data processing...")

print(json.dumps({"status": "done", "files_generated": 2}))
```

## File Size Limits

Generated files are subject to the `FILE_MAX_SIZE_MB` configuration (default: 99 MB). Files exceeding this limit are silently skipped.

## Download Links

After execution, each generated file gets a unique download URL. These URLs are included in the skill's output under the `_generated_files` key:

```json
{
  "_generated_files": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "report.csv",
      "mime_type": "text/csv",
      "size_bytes": 1234,
      "download_url": "https://your-domain.com/api/files/dl/abc123..."
    }
  ]
}
```

The `id` field is the file UUID. Use it with the [Drive node](../nodes/drive-node.md) to manage the file from within the workflow — delete it, add a password, set an expiry, or limit downloads:

```
$agentLabel._generated_files[0].id
```

These links can also be shared directly or managed through the [Drive](../reference/drive.md) tab.

Depending on deployment configuration, `download_url` can be either:
- An absolute URL (when `FRONTEND_URL` is configured for the backend container).
- A relative path (for example `/api/files/dl/abc123...`), which still works in the browser UI.

## Supported MIME Types

File types are automatically detected from the file extension. Common types:

| Extension | MIME Type |
|-----------|-----------|
| .pdf | application/pdf |
| .docx | application/vnd.openxmlformats-officedocument.wordprocessingml.document |
| .csv | text/csv |
| .json | application/json |
| .txt | text/plain |
| .png | image/png |
| .jpg | image/jpeg |

## Related

- [Drive Node](../nodes/drive-node.md) - Programmatic delete, password, TTL, and download limits on generated files
- [Drive](../reference/drive.md) - Dashboard Drive tab and share-link behavior
- [Drive Tab](../tabs/drive-tab.md) - Browse and manage files in the UI
