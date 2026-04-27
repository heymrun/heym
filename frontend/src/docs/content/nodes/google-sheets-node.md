# Google Sheets

The **Google Sheets** node reads, writes, and manages data in Google Sheets spreadsheets via OAuth2. Use it to automate spreadsheet workflows — reading reports, logging results, updating trackers, and more.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | Google Sheets (OAuth2) |
| Output | `$nodeLabel.values`, `$nodeLabel.updatedRange`, `$nodeLabel.sheets`, `$nodeLabel.success` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | Google Sheets credential from [Credentials](../tabs/credentials-tab.md) |
| `gsOperation` | string | Operation: `readRange`, `appendRows`, `updateRange`, `clearRange`, `getSheetInfo` |
| `gsSpreadsheetId` | expression | Spreadsheet ID or full Google Sheets URL |
| `gsSheetName` | expression | Sheet tab name (e.g. `Sheet1`). Not required for `getSheetInfo`. |
| `gsStartRow` | expression | For `readRange`: 1-based first data row (with `gsHasHeader`, row 1 is the header). |
| `gsMaxRows` | expression | For `readRange`: max rows of data (0 = all). |
| `gsHasHeader` | boolean | For `readRange`: treat row 1 as column names when true. |
| `gsUpdateRow` | expression | For `updateRange` only: 1-based sheet row number to update (columns A–Z); if unset, `gsStartRow` is used. Not batchUpdate — one values API PUT. |
| `gsRange` | expression | A1 notation range (e.g. `A1:D100`). Legacy examples; the editor uses row fields for read/update. |
| `gsKeepHeader` | boolean | For `clearRange` only: when true, row 1 is kept and data rows below are cleared (columns A–Z). |
| `gsAppendPlacement` | `append` \| `prepend` | For `appendRows` only: **Bottom** adds after the last row with data; **Top** inserts new rows directly under row 1 (shifts data down). |
| `gsValuesInputMode` | `raw` \| `selective` | For `appendRows` / `updateRange`: **Raw** = full JSON array; **Selective** = one sheet row, column fields only (no A1 labels). |
| `gsValuesSelectiveCols` | string | Selective mode: number of columns (A–Z). |
| `gsValues` | expression | JSON 2D array of values (e.g. `[["Name","Age"],["Alice",30]]`). Required for `appendRows`, `updateRange`. |

## Spreadsheet ID

The `gsSpreadsheetId` field accepts either the **bare ID** (the long alphanumeric string between `/d/` and `/edit` in a Google Sheets URL) or the **full URL** — Heym extracts the ID automatically.

## Credential Setup

Google Sheets uses an **OAuth2 "Bring Your Own App"** model. You provide your own Google Cloud OAuth2 credentials.

**Backend configuration:** Set **`FRONTEND_URL`** on the Heym backend to the public URL of the app (the address users type in the browser), e.g. `https://your-heym-domain`. The OAuth redirect URI is always `{FRONTEND_URL}/api/credentials/google-sheets/oauth/callback` — it is derived only from this setting, not from request headers.

1. Go to [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services** → **Enable APIs** → enable **Google Sheets API**.
2. Go to **Credentials** → **Create Credentials** → **OAuth client ID** → select **Web application**.
3. Under **Authorized redirect URIs**, add exactly: `{your FRONTEND_URL}/api/credentials/google-sheets/oauth/callback` (for example `https://your-heym-domain/api/credentials/google-sheets/oauth/callback`).
4. Copy the **Client ID** and **Client Secret**.
5. In Heym Dashboard → **Credentials** → **New** → select **Google Sheets (OAuth2)**.
6. Enter the Client ID, Client Secret, and a name, then click **Connect** to complete the OAuth2 consent in a browser popup.

Tokens refresh automatically in the background — no manual token management required.

## Operations

| Operation | Required Fields | Description |
|-----------|-----------------|-------------|
| `readRange` | gsSpreadsheetId, gsSheetName, gsStartRow, gsMaxRows, gsHasHeader | Read cell values (A–Z); optional `gsRange` in legacy flows |
| `appendRows` | gsSpreadsheetId, gsSheetName, gsValues | Add rows at the bottom (`gsAppendPlacement` append) or under row 1 (`prepend`) |
| `updateRange` | gsSpreadsheetId, gsSheetName, gsUpdateRow, gsValues | Overwrite row(s) starting at `gsUpdateRow` (A–Z); multi-row JSON writes consecutive rows |
| `clearRange` | gsSpreadsheetId, gsSheetName | Clear all values in columns A–Z for the tab; optional `gsKeepHeader` keeps the first row |
| `getSheetInfo` | gsSpreadsheetId | Get spreadsheet title and list of sheet tabs |

## Output Reference

| Operation | Output field | Type | Description |
|-----------|-------------|------|-------------|
| `readRange` | `.rows` | array | Row objects: column keys (header names or A, B, …) plus **`rowIndex`** (1-based sheet row) |
| `readRange` | `.total` | number | Number of data rows returned |
| `appendRows` | `.updatedRange` | string | Range written |
| `appendRows` | `.updates` | number | Number of rows appended |
| `updateRange` | `.updatedRange` | string | Range written |
| `updateRange` | `.updatedCells` | number | Number of cells updated |
| `clearRange` | `.clearedRange` | string | Range that was cleared |
| `getSheetInfo` | `.title` | string | Spreadsheet title |
| `getSheetInfo` | `.sheets` | array | List of `{sheetId, title}` objects |

All operations include `success: true` and `operation: "<name>"` in the output.

## Example – Read a Range

```json
{
  "type": "googleSheets",
  "data": {
    "label": "readReport",
    "credentialId": "google-sheets-credential-uuid",
    "gsOperation": "readRange",
    "gsSpreadsheetId": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
    "gsSheetName": "Sheet1",
    "gsRange": "A1:D100"
  }
}
```

Access output: `$readReport.rows[0]` (first data row object), `$readReport.rows[0].Name` (column by header), `$readReport.rows[0].rowIndex` (1-based sheet row).

## Example – Append a Row from Input

```json
{
  "type": "googleSheets",
  "data": {
    "label": "logEntry",
    "credentialId": "google-sheets-credential-uuid",
    "gsOperation": "appendRows",
    "gsSpreadsheetId": "$input.spreadsheetUrl",
    "gsSheetName": "Log",
    "gsValues": "[[\"$input.name\", \"$input.email\", \"$input.timestamp\"]]"
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Credentials Tab](../tabs/credentials-tab.md) – Add Google Sheets OAuth2 credential
- [Third-Party Integrations](../reference/integrations.md#google-sheets-oauth2) – Google Sheets credential setup
