# Grist

The **Grist** node reads, writes, and manages data in Grist spreadsheets. Use it for CRUD operations, batch updates, and spreadsheet automation.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.records`, `$nodeLabel.record`, `$nodeLabel.success`, `$nodeLabel.id` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | Grist credential from [Credentials](../tabs/credentials-tab.md) |
| `gristOperation` | string | Operation: `getRecord`, `getRecords`, `createRecord`, `createRecords`, `updateRecord`, `updateRecords`, `deleteRecord`, `listTables`, `listColumns` |
| `gristDocId` | expression | Document ID (from Grist URL) |
| `gristTableId` | expression | Table ID |
| `gristRecordId` | expression | Record ID (single-record ops) |
| `gristRecordData` | JSON string | Field values for create/update. Use **column IDs** (e.g. `User_Name`), not labels. |
| `gristRecordsData` | JSON string | Array of records for batch ops |
| `gristFilter` | JSON string | Filter: `{"Column_ID": [values]}` |
| `gristSort` | string | Sort: `Column_ID` or `-Column_ID` (descending) |
| `gristLimit` | number | Max records (default: 100) |

## Column IDs vs Labels

Use **column IDs** (underscores, e.g. `User_Name`) in `gristRecordData` and filters, not display labels. Use `listColumns` to discover column IDs.

## Example – Get Records

```json
{
  "type": "grist",
  "data": {
    "label": "getUsers",
    "credentialId": "grist-credential-uuid",
    "gristOperation": "getRecords",
    "gristDocId": "doc-id",
    "gristTableId": "Users",
    "gristFilter": "{\"User_Status\": [\"Active\"]}",
    "gristLimit": 50
  }
}
```

## Example – Create Record

```json
{
  "type": "grist",
  "data": {
    "label": "createUser",
    "credentialId": "grist-credential-uuid",
    "gristOperation": "createRecord",
    "gristDocId": "doc-id",
    "gristTableId": "Users",
    "gristRecordData": "{\"User_Name\": \"$userInput.body.name\", \"Email_Address\": \"$userInput.body.email\"}"
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Credentials Tab](../tabs/credentials-tab.md) – Add Grist API key
- [Third-Party Integrations](../reference/integrations.md#grist) – Grist credential setup
