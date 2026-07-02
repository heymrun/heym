export interface OperationOption {
  value: string;
  label: string;
}

export interface OperationOptionGroup {
  label?: string;
  options: OperationOption[];
}

function flattenOperationGroups(groups: OperationOptionGroup[]): OperationOption[] {
  return groups.flatMap((group) => group.options);
}

export const ragOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation" },
  { value: "insert", label: "Insert" },
  { value: "search", label: "Search" },
];

export const redisOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation..." },
  { value: "set", label: "Set Variable" },
  { value: "get", label: "Get Variable" },
  { value: "hasKey", label: "Has Key" },
  { value: "deleteKey", label: "Delete Key" },
];

export const linearOperationGroups: OperationOptionGroup[] = [
  {
    label: "Workspace",
    options: [
      { value: "getViewer", label: "Get Viewer" },
      { value: "listTeams", label: "List Teams" },
      { value: "listProjects", label: "List Projects" },
      { value: "listWorkflowStates", label: "List Workflow States" },
      { value: "listTeamMembers", label: "List Team Members" },
    ],
  },
  {
    label: "Issues",
    options: [
      { value: "listIssues", label: "List Issues" },
      { value: "getIssue", label: "Get Issue" },
      { value: "createIssue", label: "Create Issue" },
      { value: "updateIssue", label: "Update Issue" },
      { value: "deleteIssue", label: "Delete Issue" },
      { value: "addIssueLink", label: "Add Issue Link" },
    ],
  },
  {
    label: "Comments",
    options: [
      { value: "createComment", label: "Create Comment" },
      { value: "listComments", label: "List Comments" },
      { value: "updateComment", label: "Update Comment" },
      { value: "deleteComment", label: "Delete Comment" },
      { value: "resolveComment", label: "Resolve Comment" },
      { value: "unresolveComment", label: "Unresolve Comment" },
    ],
  },
];

export const linearOperationOptions: OperationOption[] =
  flattenOperationGroups(linearOperationGroups);

export const githubOperationGroups: OperationOptionGroup[] = [
  {
    label: "Repository",
    options: [
      { value: "getRepository", label: "Get Repository" },
      { value: "getRepositoryLicense", label: "Get Repository License" },
      { value: "getRepositoryProfile", label: "Get Repository Profile" },
      { value: "listPopularPaths", label: "List Popular Paths for Repository" },
      { value: "listReferrers", label: "List Top Referrers for Repository" },
    ],
  },
  {
    label: "Users and Organizations",
    options: [
      { value: "listOrganizationRepositories", label: "List Organization Repositories" },
      { value: "listUserRepositories", label: "List User Repositories" },
      { value: "getUserRepositories", label: "Get User Repositories" },
      { value: "getUserIssues", label: "Get User Issues" },
      { value: "inviteUser", label: "Invite User" },
    ],
  },
  {
    label: "Issues",
    options: [
      { value: "createIssue", label: "Create Issue" },
      { value: "getIssue", label: "Get Issue" },
      { value: "listIssues", label: "List Issues" },
      { value: "getRepositoryIssues", label: "Get Repository Issues" },
      { value: "lockIssue", label: "Lock Issue" },
      { value: "updateIssue", label: "Edit Issue" },
      { value: "createComment", label: "Create Comment" },
    ],
  },
  {
    label: "Pull Requests and Reviews",
    options: [
      { value: "createPullRequest", label: "Create Pull Request" },
      { value: "listPullRequests", label: "List Pull Requests" },
      { value: "getRepositoryPullRequests", label: "Get Repository Pull Requests" },
      { value: "createReview", label: "Create Review" },
      { value: "getReview", label: "Get Review" },
      { value: "listReviews", label: "List Reviews" },
      { value: "updateReview", label: "Update Review" },
    ],
  },
  {
    label: "Releases",
    options: [
      { value: "createRelease", label: "Create Release" },
      { value: "deleteRelease", label: "Delete Release" },
      { value: "getRelease", label: "Get Release" },
      { value: "listReleases", label: "List Releases" },
      { value: "updateRelease", label: "Update Release" },
    ],
  },
  {
    label: "Actions Workflows",
    options: [
      { value: "dispatchWorkflow", label: "Dispatch Workflow" },
      { value: "dispatchWorkflowAndWait", label: "Dispatch Workflow and Wait" },
      { value: "disableWorkflow", label: "Disable Workflow" },
      { value: "enableWorkflow", label: "Enable Workflow" },
      { value: "getWorkflow", label: "Get Workflow" },
      { value: "getWorkflowUsage", label: "Get Workflow Usage" },
      { value: "listWorkflows", label: "List Workflows" },
    ],
  },
  {
    label: "Files",
    options: [
      { value: "upsertFile", label: "Create or Update File" },
      { value: "deleteFile", label: "Delete File" },
      { value: "getFile", label: "Get File" },
      { value: "listFiles", label: "List Files" },
    ],
  },
];

export const githubOperationOptions: OperationOption[] =
  flattenOperationGroups(githubOperationGroups);

export const gristOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation..." },
  { value: "getRecord", label: "Get Record" },
  { value: "getRecords", label: "Get Records" },
  { value: "createRecord", label: "Create Record" },
  { value: "createRecords", label: "Create Records (Batch)" },
  { value: "updateRecord", label: "Update Record" },
  { value: "updateRecords", label: "Update Records (Batch)" },
  { value: "deleteRecord", label: "Delete Record(s)" },
  { value: "listTables", label: "List Tables" },
  { value: "listColumns", label: "List Columns" },
];

export const googleSheetsOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation..." },
  { value: "readRange", label: "Read" },
  { value: "appendRows", label: "Append Rows" },
  { value: "updateRange", label: "Update Rows" },
  { value: "clearRange", label: "Clear Rows" },
  { value: "getSheetInfo", label: "Get Sheet Info" },
];

export const bigQueryOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation..." },
  { value: "query", label: "Run Query" },
  { value: "insertRows", label: "Insert Rows" },
];

export const clickhouseOperationGroups: OperationOptionGroup[] = [
  {
    options: [
      { value: "", label: "Select operation..." },
      { value: "query", label: "Run SQL Query" },
    ],
  },
  {
    label: "Read",
    options: [
      { value: "find", label: "Find Rows" },
      { value: "getAll", label: "Get All Rows" },
      { value: "count", label: "Count Rows" },
      { value: "getById", label: "Get By ID" },
    ],
  },
  {
    label: "Write",
    options: [
      { value: "insert", label: "Insert Rows" },
      { value: "update", label: "Update Rows" },
      { value: "remove", label: "Remove Rows" },
      { value: "upsert", label: "Upsert Rows" },
    ],
  },
];

export const clickhouseOperationOptions: OperationOption[] =
  flattenOperationGroups(clickhouseOperationGroups);

export const supabaseOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation..." },
  { value: "select", label: "Select Rows" },
  { value: "insert", label: "Insert Rows" },
  { value: "update", label: "Update Rows" },
  { value: "upsert", label: "Upsert Rows" },
  { value: "delete", label: "Delete Rows" },
];

export const notionOperationGroups: OperationOptionGroup[] = [
  {
    options: [
      { value: "", label: "Select operation..." },
      { value: "search", label: "Search" },
    ],
  },
  {
    label: "Pages",
    options: [
      { value: "getPage", label: "Get Page" },
      { value: "createPage", label: "Create Page" },
      { value: "updatePage", label: "Update Page" },
      { value: "trashPage", label: "Move Page to Trash" },
      { value: "restorePage", label: "Restore Page" },
    ],
  },
  {
    label: "Databases",
    options: [
      { value: "createDatabase", label: "Create Database" },
      { value: "retrieveDatabase", label: "Retrieve Database" },
      { value: "updateDatabase", label: "Update Database" },
    ],
  },
  {
    label: "Data Sources",
    options: [
      { value: "createDataSource", label: "Create Data Source" },
      { value: "retrieveDataSource", label: "Retrieve Data Source" },
      { value: "updateDataSource", label: "Update Data Source" },
      { value: "queryDataSource", label: "Query Data Source" },
    ],
  },
  {
    label: "Blocks",
    options: [
      { value: "getBlockChildren", label: "Get Block Children" },
      { value: "updateBlock", label: "Update Block" },
      { value: "deleteBlock", label: "Delete Block" },
      { value: "appendBlocks", label: "Append Blocks" },
    ],
  },
];

export const notionOperationOptions: OperationOption[] =
  flattenOperationGroups(notionOperationGroups);

export const s3OperationGroups: OperationOptionGroup[] = [
  {
    label: "Buckets",
    options: [
      { value: "createBucket", label: "Create Bucket" },
      { value: "deleteBucket", label: "Delete Bucket" },
      { value: "listBuckets", label: "List Buckets" },
    ],
  },
  {
    label: "Folders",
    options: [
      { value: "createFolder", label: "Create Folder" },
      { value: "deleteFolder", label: "Delete Folder" },
      { value: "getAllFolder", label: "Get All in Folder" },
    ],
  },
  {
    label: "Objects",
    options: [
      { value: "copyObject", label: "Copy Object" },
      { value: "deleteObject", label: "Delete Object" },
      { value: "getObject", label: "Get Object" },
      { value: "listObjects", label: "List Objects" },
      { value: "putObject", label: "Upload Object" },
    ],
  },
];

export const s3OperationOptions: OperationOption[] = flattenOperationGroups(s3OperationGroups);

export const dataTableOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation..." },
  { value: "find", label: "Find Rows" },
  { value: "getAll", label: "Get All Rows" },
  { value: "count", label: "Count Rows" },
  { value: "getById", label: "Get Row by ID" },
  { value: "insert", label: "Insert Row" },
  { value: "update", label: "Update Row" },
  { value: "remove", label: "Remove Row" },
  { value: "upsert", label: "Upsert Row" },
];

export const driveOperationOptions: OperationOption[] = [
  { value: "get", label: "Get File" },
  { value: "getAll", label: "Get All Files" },
  { value: "downloadUrl", label: "Download from URL" },
  { value: "save", label: "Save from Base64" },
  { value: "convertFile", label: "Convert File" },
  { value: "delete", label: "Delete File" },
  { value: "setPassword", label: "Set Password" },
  { value: "setTtl", label: "Set TTL (Expiry)" },
  { value: "setMaxDownloads", label: "Set Max Downloads" },
];

export const rabbitmqOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation..." },
  { value: "send", label: "Send Message" },
  { value: "receive", label: "Receive Message (Trigger)" },
];
