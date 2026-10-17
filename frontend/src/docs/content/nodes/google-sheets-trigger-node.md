# Google Sheets Trigger

The **Google Sheets Trigger** node watches one sheet tab and starts a workflow once for each row that is added, updated, or deleted. Use it for form responses, lead lists, and status columns your team edits.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.event`, `$nodeLabel.row`, `$nodeLabel.changed_columns`, `$nodeLabel.key`, `$nodeLabel.spreadsheet_id`, `$nodeLabel.sheet_name`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `google_sheets` credential |
| `gstSpreadsheetId` | String | Spreadsheet ID or URL |
| `gstSheetName` | String | Tab name (default `Sheet1`) |
| `gstHasHeader` | Boolean | Row 1 holds column names (default on) |
| `gstKeyColumn` | String | Optional, recommended. Header name (or column letter without a header) whose value is unique per row |
| `gstEvents` | Array | Any of `created`, `updated`, `deleted` (default all three) |
| `pollIntervalMinutes` | Integer | How often Heym checks the sheet (minimum and default 1) |

These fields take plain values, not `$` expressions.

## Setup Guide

1. Create a **Google Sheets (OAuth2)** credential. See [Third-Party Integrations](../reference/integrations.md#google-sheets-oauth2).
2. Drag **Google Sheets Trigger** onto the canvas and select the credential.
3. Paste the spreadsheet URL, enter the tab name, and set a key column such as `Email` or `ID`.

## Row Identity

- **With a key column**, a row is matched by its key value. Inserting, deleting, or sorting rows is detected correctly. A row with an empty key is ignored until the key is filled in. If two rows share a key, the first one is used.
- **Without a key column**, a row is matched by its row number. Deleting a row in the middle of the sheet then reads as `updated` for every row below it plus one `deleted` at the end.

## Trigger Semantics

- The first poll records the sheet as it is and starts nothing.
- Blank rows are ignored.
- Editing the header row records the sheet again without starting runs.
- Each change starts exactly one run with `trigger_source = "google_sheets"`, also when Heym runs several workers or instances. If a run cannot start, the change is tried again on the next poll. A server crash in the moment between recording a change and starting its run can drop that one change; it is never run twice.
- At most 50 runs start per poll; the rest follow on the next polls.
- A tab with more than 10,000 rows is skipped with a warning in the logs.

## Writing Back to the Same Sheet

A workflow that writes to the sheet it watches causes its own `updated` events. If your workflow writes a score or status back into the row, keep only **Row added** (`created`) on.

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.event` | `created`, `updated`, or `deleted` |
| `$nodeLabel.row` | The row's current cells by column name, plus `rowIndex` |
| `$nodeLabel.row.rowIndex` | Sheet row number |
| `$nodeLabel.changed_columns` | Columns that changed. On `created`, every non-empty column |
| `$nodeLabel.key` | Key column value, `null` on `deleted` or without a key column |
| `$nodeLabel.spreadsheet_id` | Watched spreadsheet |
| `$nodeLabel.sheet_name` | Watched tab |
| `$nodeLabel.triggered_at` | When the change was seen |

For `deleted`, `row` holds only `rowIndex`, the row number it last had.

## What Heym Stores

Heym does not store cell values. For each row it keeps the last row number and a keyed fingerprint per cell, derived from the instance's `SECRET_KEY`. That is enough to tell which columns changed, but not what they said before. Runs read the row's current values from Google.

## Example Workflow

**New lead row: score it and write the score back**

```
googleSheetsTrigger (created only) → llm → googleSheets (updateRange) → condition → slack
```

- **Google Sheets** `gsUpdateRow`: `$newLead.row.rowIndex`

## Related

- [Google Sheets](./google-sheets-node.md): read or write rows in the run
- [Google Drive Trigger](./google-drive-trigger-node.md)
- [Triggers](../reference/triggers.md)
