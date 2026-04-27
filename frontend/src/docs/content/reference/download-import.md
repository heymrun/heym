# Download & Import

Export workflows or entire folders as files, or import them via drag & drop. Use this for backup, sharing, or migrating workflows between instances.

## Download Workflow (JSON)

**Location:** Editor toolbar → **Download** button (visible on large screens)

**What it exports:**
- `nodes` – All nodes on the canvas
- `edges` – All connections between nodes

**Filename:** `{workflow-name}.json` (derived from the workflow name)

**Format:** See [Workflow Structure](./workflow-structure.md) for the JSON schema.

## Download Folder (ZIP)

**Location:** Dashboard → Workflows tab → folder 3-dot menu → **Download as ZIP**

**What it exports:**
- All workflows in the folder and all sub-folders, recursively
- Folder hierarchy preserved as directories inside the ZIP

**ZIP structure:**
```
FolderName/
  workflow1.json
  workflow2.json
  SubFolder/
    workflow3.json
    DeepSub/
      workflow4.json
```

Each `.json` file contains `{ name, nodes, edges }`.

## Import

### From Dashboard (Workflows Tab)

1. Go to the [Workflows](../tabs/workflows-tab.md) tab
2. Drag a **JSON** or **ZIP** file onto the workflow area

**JSON file:** A new workflow is created. The workflow name comes from the `name` field in the JSON, or the filename if `name` is missing.

**ZIP file:** The entire folder structure is recreated at root level. Each `.json` file inside the ZIP becomes a workflow placed in the matching folder. Credentials and cross-workflow references that don't exist in the current instance are cleared automatically. If some workflows fail to import, a summary shows how many succeeded.

### From Canvas (Editor)

1. Open a workflow in the editor
2. Drag a JSON file onto the canvas
3. If the canvas already has nodes or edges, a confirmation dialog asks whether to replace the current workflow
4. The imported nodes and edges replace or merge into the current workflow

## File Formats

### JSON (single workflow)

```json
{
  "nodes": [...],
  "edges": [...],
  "name": "Optional workflow name"
}
```

- `nodes` – Required; array of node objects
- `edges` – Optional; array of edge objects (defaults to `[]`)
- `name` – Optional; used when creating a new workflow from the Dashboard import

### ZIP (folder)

ZIP archive where the directory structure mirrors the folder hierarchy. Each file is a workflow JSON (see above). Folder and workflow names are derived from the directory and file names respectively.

See [Workflow Structure](./workflow-structure.md) for node and edge formats.

## Use Cases

- **Backup** – Download workflows or entire folders before major changes
- **Sharing** – Export and share JSON files with teammates
- **Migration** – Move workflows or folder structures between Heym instances
- **Version control** – Store workflow JSON in Git alongside code

## Related

- [Workflow Structure](./workflow-structure.md) – JSON format for nodes and edges
- [Workflows Tab](../tabs/workflows-tab.md) – Create workflows and import via drag & drop
- [Workflow Organization](./workflow-organization.md) – Folders and sub-folders
- [Canvas Features](./canvas-features.md) – Editor features including canvas import
