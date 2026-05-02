import axios from "axios";

import { heymClientHeaders } from "@/constants/httpIdentity";
import type { LoginRequest, PasswordChangeRequest, RegisterRequest, User, UserUpdateRequest } from "@/types/auth";
import type {
  CreateTemplateRequest,
  NodeTemplate,
  TemplateListResponse,
  WorkflowTemplate,
} from "@/features/templates/types/template.types";
import type {
  Credential,
  CredentialForIntellisense,
  CredentialListItem,
  CredentialShare,
  CredentialType,
  CreateCredentialRequest,
  LLMModel,
  UpdateCredentialRequest,
} from "@/types/credential";
import type { LLMTraceDetail, LLMTraceListResponse } from "@/types/trace";
import type {
  ActiveExecutionItem,
  AgentProgressEvent,
  AllExecutionHistoryEntry,
  AllExecutionHistoryEntryLight,
  ExpressionEvaluateRequest,
  ExpressionEvaluateResponse,
  ExecutionResult,
  Folder,
  FolderTree,
  FolderWithContents,
  HITLDecisionPayload,
  HITLReview,
  HistoryListResponse,
  InputField,
  LLMBatchProgressEvent,
  NodeResult,
  ServerExecutionHistory,
  ExecutionToken,
  WebhookBodyMode,
  Workflow,
  WorkflowListItem,
  WorkflowVersion,
  WorkflowVersionDiff,
  WorkflowShare,
} from "@/types/workflow";
import type {
  AnalyticsQueryOptions,
  AnalyticsStats,
  TimeSeriesMetrics,
  WorkflowBreakdownItem,
  WorkflowBreakdownResponse,
} from "@/types/analytics";
import type {
  CreateGlobalVariableRequest,
  GlobalVariable,
  GlobalVariableListItem,
  GlobalVariableShare,
  UpdateGlobalVariableRequest,
} from "@/types/globalVariable";
import type {
  CreateSuiteRequest,
  CreateTestCaseRequest,
  EvalRun,
  EvalRunListItem,
  EvalSuite,
  EvalSuiteListItem,
  GenerateTestDataRequest,
  GenerateTestDataResponse,
  OptimizePromptRequest,
  OptimizePromptResponse,
  RunEvalsRequest,
  UpdateSuiteRequest,
  UpdateTestCaseRequest,
} from "@/types/evals";
import type {
  AddTeamMemberRequest,
  CreateTeamRequest,
  Team,
  TeamDetail,
  TeamShare,
  TeamSharedEntities,
  UpdateTeamRequest,
} from "@/types/team";
import type {
  AgentMemoryEdgeDTO,
  AgentMemoryGraphResponse,
  AgentMemoryNodeDTO,
} from "@/types/agentMemory";

const API_URL = import.meta.env.VITE_API_URL || "";

const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    "Content-Type": "application/json",
    ...heymClientHeaders,
  },
  withCredentials: true,
});

export interface WorkflowExecuteOptions {
  bodyMode?: WebhookBodyMode;
  testRun?: boolean;
  triggerSource?: string;
  /** When false, request full JSON (node_results, etc.). Default API behavior is outputs-only (x-simple-response). */
  simpleResponse?: boolean;
}

function buildWorkflowExecuteRequest(
  body: unknown,
  options?: WorkflowExecuteOptions,
): { payload: unknown; query: string } {
  const bodyMode = options?.bodyMode || "legacy";
  const testRun = options?.testRun ?? false;
  const triggerSource = options?.triggerSource?.trim();
  const queryParams = new URLSearchParams();

  if (testRun) {
    queryParams.set("test_run", "true");
  }
  if (triggerSource) {
    queryParams.set("trigger_source", triggerSource);
  }
  const query = queryParams.toString() ? `?${queryParams.toString()}` : "";

  if (bodyMode === "generic") {
    return {
      payload: body === undefined ? {} : body,
      query,
    };
  }

  return {
    payload: {
      inputs: body === undefined ? {} : body,
      test_run: testRun,
    },
    query,
  };
}

let _isRefreshing = false;
let _refreshQueue: Array<{ resolve: () => void; reject: (err: Error) => void }> = [];

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Only skip automatic token refresh for endpoints where retrying after a
    // refresh would be wrong or cause an infinite loop:
    //  - /auth/refresh  → refreshing a failed refresh = infinite loop
    //  - /auth/login    → a 401 here means wrong credentials, not an expired session
    //  - /auth/register → same as login
    //
    // /auth/me MUST be allowed to trigger a refresh: the access-token cookie
    // expires on a timer and the app calls /auth/me on every page load to
    // restore the session.  Without this, the user is logged out the moment the
    // access token expires even though the refresh token is still valid.
    const url = originalRequest.url as string | undefined;
    const shouldSkipRefresh =
      url?.includes("/auth/refresh") ||
      url?.includes("/auth/login") ||
      url?.includes("/auth/register");

    if (error.response?.status === 401 && !originalRequest._retry && !shouldSkipRefresh) {
      originalRequest._retry = true;

      if (_isRefreshing) {
        return new Promise<void>((resolve, reject) => {
          _refreshQueue.push({ resolve, reject });
        }).then(() => api(originalRequest));
      }

      _isRefreshing = true;
      try {
        await axios.post(
          `${API_URL}/api/auth/refresh`,
          {},
          { withCredentials: true, headers: { ...heymClientHeaders } },
        );
        _refreshQueue.forEach(({ resolve }) => resolve());
        _refreshQueue = [];
        return api(originalRequest);
      } catch (refreshError) {
        _refreshQueue.forEach(({ reject }) => reject(refreshError instanceof Error ? refreshError : new Error("Session expired")));
        _refreshQueue = [];
        // Avoid a full-page-reload loop when already on /login, and never
        // redirect portal pages (/chat/*) to the main app login — portals
        // handle their own authentication independently.
        const path = window.location.pathname;
        if (
          !path.startsWith("/login") &&
          !path.startsWith("/chat/") &&
          !path.startsWith("/review/")
        ) {
          window.location.href = "/login";
        }
      } finally {
        _isRefreshing = false;
      }
    }
    return Promise.reject(error);
  },
);

export const authApi = {
  login: async (data: LoginRequest): Promise<void> => {
    await api.post("/auth/login", data);
  },

  register: async (data: RegisterRequest): Promise<void> => {
    await api.post("/auth/register", data);
  },

  logout: async (): Promise<void> => {
    await api.post("/auth/logout");
  },

  getMe: async (): Promise<User> => {
    const response = await api.get<User>("/auth/me");
    return response.data;
  },

  updateMe: async (data: UserUpdateRequest): Promise<User> => {
    const response = await api.put<User>("/auth/me", data);
    return response.data;
  },

  changePassword: async (data: PasswordChangeRequest): Promise<void> => {
    await api.post("/auth/change-password", {
      current_password: data.currentPassword,
      new_password: data.newPassword,
    });
  },
};

export const workflowApi = {
  list: async (): Promise<WorkflowListItem[]> => {
    const response = await api.get<WorkflowListItem[]>("/workflows");
    return response.data;
  },

  listWithInputs: async (): Promise<WorkflowWithInputs[]> => {
    const response = await api.get<WorkflowWithInputs[]>(
      "/workflows/with-inputs",
    );
    return response.data;
  },

  get: async (id: string): Promise<Workflow> => {
    const response = await api.get<Workflow>(`/workflows/${id}`);
    return response.data;
  },

  getAgentMemoryGraph: async (
    workflowId: string,
    canvasNodeId: string,
  ): Promise<AgentMemoryGraphResponse> => {
    const enc = encodeURIComponent(canvasNodeId);
    const response = await api.get<AgentMemoryGraphResponse>(
      `/workflows/${workflowId}/nodes/${enc}/agent-memory/graph`,
    );
    return response.data;
  },

  createAgentMemoryNode: async (
    workflowId: string,
    canvasNodeId: string,
    body: {
      entity_name: string;
      entity_type: string;
      properties?: Record<string, unknown>;
      confidence?: number;
    },
  ): Promise<AgentMemoryNodeDTO> => {
    const enc = encodeURIComponent(canvasNodeId);
    const response = await api.post<AgentMemoryNodeDTO>(
      `/workflows/${workflowId}/nodes/${enc}/agent-memory/nodes`,
      body,
    );
    return response.data;
  },

  updateAgentMemoryNode: async (
    workflowId: string,
    memoryNodeId: string,
    body: {
      entity_name?: string;
      entity_type?: string;
      properties?: Record<string, unknown>;
      confidence?: number;
    },
  ): Promise<AgentMemoryNodeDTO> => {
    const response = await api.put<AgentMemoryNodeDTO>(
      `/workflows/${workflowId}/agent-memory/nodes/${memoryNodeId}`,
      body,
    );
    return response.data;
  },

  deleteAgentMemoryNode: async (workflowId: string, memoryNodeId: string): Promise<void> => {
    await api.delete(`/workflows/${workflowId}/agent-memory/nodes/${memoryNodeId}`);
  },

  createAgentMemoryEdge: async (
    workflowId: string,
    canvasNodeId: string,
    body: {
      source_entity_name: string;
      target_entity_name: string;
      relationship_type: string;
      properties?: Record<string, unknown>;
      confidence?: number;
    },
  ): Promise<AgentMemoryEdgeDTO> => {
    const enc = encodeURIComponent(canvasNodeId);
    const response = await api.post<AgentMemoryEdgeDTO>(
      `/workflows/${workflowId}/nodes/${enc}/agent-memory/edges`,
      body,
    );
    return response.data;
  },

  updateAgentMemoryEdge: async (
    workflowId: string,
    memoryEdgeId: string,
    body: {
      relationship_type?: string;
      properties?: Record<string, unknown>;
      confidence?: number;
    },
  ): Promise<AgentMemoryEdgeDTO> => {
    const response = await api.put<AgentMemoryEdgeDTO>(
      `/workflows/${workflowId}/agent-memory/edges/${memoryEdgeId}`,
      body,
    );
    return response.data;
  },

  deleteAgentMemoryEdge: async (workflowId: string, memoryEdgeId: string): Promise<void> => {
    await api.delete(`/workflows/${workflowId}/agent-memory/edges/${memoryEdgeId}`);
  },

  create: async (data: {
    name: string;
    description?: string;
  }): Promise<Workflow> => {
    const response = await api.post<Workflow>("/workflows", data);
    return response.data;
  },

  update: async (
    id: string,
    data: Partial<
      Pick<
        Workflow,
        | "name"
        | "description"
        | "nodes"
        | "edges"
        | "auth_type"
        | "auth_header_key"
        | "auth_header_value"
        | "webhook_body_mode"
        | "cache_ttl_seconds"
        | "rate_limit_requests"
        | "rate_limit_window_seconds"
        | "sse_enabled"
        | "sse_node_config"
      >
    >,
  ): Promise<Workflow> => {
    const response = await api.put<Workflow>(`/workflows/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/workflows/${id}`);
  },

  scheduleForDeletion: async (id: string): Promise<WorkflowListItem> => {
    const response = await api.put<WorkflowListItem>(
      `/workflows/${id}/schedule-deletion`,
    );
    return response.data;
  },

  unscheduleForDeletion: async (id: string): Promise<WorkflowListItem> => {
    const response = await api.delete<WorkflowListItem>(
      `/workflows/${id}/schedule-deletion`,
    );
    return response.data;
  },

  getHistory: async (
    id: string,
    limit = 50,
    offset = 0,
    search?: string,
    triggerSource?: string,
  ): Promise<HistoryListResponse<AllExecutionHistoryEntryLight>> => {
    const response = await api.get<HistoryListResponse<AllExecutionHistoryEntryLight>>(
      `/workflows/${id}/history`,
      {
        params: {
          limit,
          offset,
          search: search || undefined,
          trigger_source: triggerSource || undefined,
        },
      },
    );
    return response.data;
  },
  getWorkflowHistoryEntry: async (
    workflowId: string,
    entryId: string,
  ): Promise<ServerExecutionHistory> => {
    const response = await api.get<ServerExecutionHistory>(
      `/workflows/${workflowId}/history/${entryId}`,
    );
    return response.data;
  },
  streamWorkflowHistoryEntry: (
    workflowId: string,
    entryId: string,
    onEntry: (entry: ServerExecutionHistory) => void,
    onDone: () => void,
    onError: (error: Error) => void,
    signal?: AbortSignal,
  ): void => {
    const API_URL = import.meta.env.VITE_API_URL || "";

    fetch(`${API_URL}/api/workflows/${workflowId}/history/${entryId}/stream`, {
      method: "GET",
      credentials: "include",
      headers: { ...heymClientHeaders },
      signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.detail || `HTTP error! status: ${response.status}`,
          );
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let doneReceived = false;

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const data = JSON.parse(line.slice(6));

            if (data.type === "history_update" && data.entry) {
              onEntry(data.entry as ServerExecutionHistory);
            } else if (data.type === "done") {
              doneReceived = true;
              onDone();
              return;
            } else if (data.type === "error") {
              throw new Error(data.message || "History stream error");
            }
          }
        }

        if (!doneReceived && !signal?.aborted) {
          throw new Error("History stream disconnected");
        }
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        onError(error instanceof Error ? error : new Error("History stream failed"));
      });
  },
  getAllHistory: async (
    limit = 50,
    offset = 0,
    search?: string,
    status?: string,
    triggerSource?: string,
    workflowId?: string,
  ): Promise<HistoryListResponse<AllExecutionHistoryEntryLight>> => {
    const response = await api.get<HistoryListResponse<AllExecutionHistoryEntryLight>>(
      "/workflows/history/all",
      {
        params: {
          limit,
          offset,
          search: search || undefined,
          status: status || undefined,
          trigger_source: triggerSource || undefined,
          workflow_id: workflowId || undefined,
        },
      },
    );
    return response.data;
  },
  getHistoryEntry: async (entryId: string): Promise<AllExecutionHistoryEntry> => {
    const response = await api.get<AllExecutionHistoryEntry>(
      `/workflows/history/all/${entryId}`,
    );
    return response.data;
  },

  clearHistory: async (id: string): Promise<void> => {
    await api.delete(`/workflows/${id}/history`);
  },

  clearAllHistory: async (): Promise<void> => {
    await api.delete("/workflows/history/all");
  },

  getVersions: async (id: string): Promise<WorkflowVersion[]> => {
    const response = await api.get<WorkflowVersion[]>(`/workflows/${id}/versions`);
    return response.data;
  },

  getVersion: async (id: string, versionId: string): Promise<WorkflowVersion> => {
    const response = await api.get<WorkflowVersion>(
      `/workflows/${id}/versions/${versionId}`,
    );
    return response.data;
  },

  getVersionDiff: async (
    id: string,
    versionId: string,
    compareTo?: string,
  ): Promise<WorkflowVersionDiff> => {
    const params = compareTo ? { compare_to: compareTo } : {};
    const response = await api.get<WorkflowVersionDiff>(
      `/workflows/${id}/versions/${versionId}/diff`,
      { params },
    );
    return response.data;
  },

  revertToVersion: async (id: string, versionId: string): Promise<Workflow> => {
    const response = await api.post<Workflow>(
      `/workflows/${id}/versions/${versionId}/revert`,
      { confirm: true },
    );
    return response.data;
  },

  clearVersions: async (id: string): Promise<void> => {
    await api.delete(`/workflows/${id}/versions`);
  },

  execute: async (
    id: string,
    body: unknown,
    options?: WorkflowExecuteOptions,
  ): Promise<ExecutionResult> => {
    const request = buildWorkflowExecuteRequest(body, options);
    const response = await api.post<ExecutionResult>(
      `/workflows/${id}/execute${request.query}`,
      request.payload,
      options?.simpleResponse === false
        ? { headers: { "x-simple-response": "false" } }
        : undefined,
    );
    return response.data;
  },

  executeStream: (
    id: string,
    body: unknown,
    onExecutionStarted: (data: { execution_id: string }) => void,
    onNodeStart: (nodeId: string) => void,
    onNodeComplete: (data: {
      node_id: string;
      node_label?: string;
      node_type?: string;
      status: string;
      output: Record<string, unknown>;
      execution_time_ms: number;
      error?: string;
      metadata?: Record<string, unknown>;
    }) => void,
    onComplete: (result: ExecutionResult) => void,
    onError: (error: Error) => void,
    testRun?: boolean,
    signal?: AbortSignal,
    onFinalOutput?: (data: {
      node_id: string;
      node_label: string;
      node_type?: string;
      output: Record<string, unknown>;
      execution_time_ms: number;
    }) => void,
    onNodeRetry?: (data: {
      node_id: string;
      node_label: string;
      attempt: number;
      max_attempts: number;
      retry_result?: NodeResult;
    }) => void,
    onAgentProgress?: (data: AgentProgressEvent) => void,
    onLlmBatchProgress?: (data: LLMBatchProgressEvent) => void,
    options?: Omit<WorkflowExecuteOptions, "testRun">,
  ): void => {
    const API_URL = import.meta.env.VITE_API_URL || "";
    const request = buildWorkflowExecuteRequest(body, {
      bodyMode: options?.bodyMode,
      testRun: testRun ?? false,
      triggerSource: options?.triggerSource,
    });

    fetch(`${API_URL}/api/workflows/${id}/execute/stream${request.query}`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "x-simple-response": "false",
        ...heymClientHeaders,
      },
      body: JSON.stringify(request.payload),
      signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let completionReceived = false;

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const data = JSON.parse(line.slice(6));

              if (data.type === "execution_started") {
                onExecutionStarted({ execution_id: data.execution_id });
              } else if (data.type === "node_start") {
                onNodeStart(data.node_id);
              } else if (data.type === "node_retry" && onNodeRetry) {
                onNodeRetry(data);
              } else if (data.type === "agent_progress" && onAgentProgress) {
                onAgentProgress(data);
              } else if (data.type === "llm_batch_progress" && onLlmBatchProgress) {
                onLlmBatchProgress(data);
              } else if (data.type === "node_complete") {
                onNodeComplete(data);
              } else if (data.type === "final_output" && onFinalOutput) {
                onFinalOutput(data);
              } else if (data.type === "execution_complete") {
                completionReceived = true;
                onComplete({
                  workflow_id: data.workflow_id,
                  status: data.status,
                  outputs: data.outputs,
                  execution_time_ms: data.execution_time_ms,
                  node_results: data.node_results,
                  execution_history_id: data.execution_history_id,
                });
              }
            }
          }
        }

        // Stream closed from server side without execution_complete
        // (e.g. cancelled by an external request from another tab/session).
        if (!completionReceived) {
          onError(new Error("Execution cancelled"));
        }
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        onError(error instanceof Error ? error : new Error("Workflow execution failed"));
      });
  },
  cancelExecution: async (workflowId: string, executionId: string): Promise<void> => {
    await api.post(`/workflows/${workflowId}/executions/${executionId}/cancel`);
  },
  getActiveExecutions: async (): Promise<ActiveExecutionItem[]> => {
    const response = await api.get<ActiveExecutionItem[]>(
      "/workflows/executions/active",
    );
    return response.data;
  },
  listShares: async (id: string): Promise<WorkflowShare[]> => {
    const response = await api.get<WorkflowShare[]>(`/workflows/${id}/shares`);
    return response.data;
  },
  addShare: async (id: string, email: string): Promise<WorkflowShare> => {
    const response = await api.post<WorkflowShare>(`/workflows/${id}/shares`, {
      email,
    });
    return response.data;
  },
  removeShare: async (id: string, userId: string): Promise<void> => {
    await api.delete(`/workflows/${id}/shares/${userId}`);
  },
  listTeamShares: async (id: string): Promise<TeamShare[]> => {
    const response = await api.get<TeamShare[]>(
      `/workflows/${id}/team-shares`,
    );
    return response.data;
  },
  addTeamShare: async (id: string, teamId: string): Promise<TeamShare> => {
    const response = await api.post<TeamShare>(
      `/workflows/${id}/team-shares`,
      { team_id: teamId },
    );
    return response.data;
  },
  removeTeamShare: async (id: string, teamId: string): Promise<void> => {
    await api.delete(`/workflows/${id}/team-shares/${teamId}`);
  },

  getInputFields: async (
    id: string,
  ): Promise<{ name: string; inputFields: InputField[] }> => {
    const workflow = await workflowApi.get(id);
    const inputFields: InputField[] = [];

    const targetNodeIds = new Set(workflow.edges.map((e) => e.target));
    const startNodes = workflow.nodes.filter(
      (node) =>
        !targetNodeIds.has(node.id) &&
        node.type === "textInput" &&
        node.data.active !== false,
    );

    for (const node of startNodes) {
      const nodeFields = node.data.inputFields || [];
      for (const field of nodeFields) {
        inputFields.push({
          key: field.key,
          defaultValue: field.defaultValue,
        });
      }
    }

    return { name: workflow.name, inputFields };
  },

  executionTokens: {
    list: async (workflowId: string): Promise<ExecutionToken[]> => {
      const response = await api.get<ExecutionToken[]>(
        `/workflows/${workflowId}/execution-tokens`,
      );
      return response.data;
    },
    create: async (workflowId: string, ttlSeconds: number): Promise<ExecutionToken> => {
      const response = await api.post<ExecutionToken>(
        `/workflows/${workflowId}/execution-tokens`,
        { ttl_seconds: ttlSeconds },
      );
      return response.data;
    },
    revoke: async (workflowId: string, tokenId: string): Promise<void> => {
      await api.delete(`/workflows/${workflowId}/execution-tokens/${tokenId}`);
    },
  },
};

export const folderApi = {
  list: async (): Promise<Folder[]> => {
    const response = await api.get<Folder[]>("/folders");
    return response.data;
  },

  getTree: async (): Promise<FolderTree[]> => {
    const response = await api.get<FolderTree[]>("/folders/tree");
    return response.data;
  },

  get: async (id: string): Promise<FolderWithContents> => {
    const response = await api.get<FolderWithContents>(`/folders/${id}`);
    return response.data;
  },

  create: async (data: {
    name: string;
    parent_id?: string | null;
  }): Promise<Folder> => {
    const response = await api.post<Folder>("/folders", data);
    return response.data;
  },

  update: async (
    id: string,
    data: { name?: string; parent_id?: string | null },
  ): Promise<Folder> => {
    const response = await api.put<Folder>(`/folders/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/folders/${id}`);
  },

  moveWorkflowToFolder: async (
    folderId: string,
    workflowId: string,
  ): Promise<WorkflowListItem> => {
    const response = await api.put<WorkflowListItem>(
      `/folders/${folderId}/workflows/${workflowId}`,
    );
    return response.data;
  },

  removeWorkflowFromFolder: async (
    workflowId: string,
  ): Promise<WorkflowListItem> => {
    const response = await api.delete<WorkflowListItem>(
      `/folders/workflows/${workflowId}/folder`,
    );
    return response.data;
  },

  exportZip: async (id: string): Promise<Blob> => {
    const response = await api.get(`/folders/${id}/export`, { responseType: "blob" });
    return response.data as Blob;
  },
};

export const teamsApi = {
  list: async (): Promise<Team[]> => {
    const response = await api.get<Team[]>("/teams");
    return response.data;
  },

  get: async (id: string): Promise<TeamDetail> => {
    const response = await api.get<TeamDetail>(`/teams/${id}`);
    return response.data;
  },

  getSharedEntities: async (id: string): Promise<TeamSharedEntities> => {
    const response = await api.get<TeamSharedEntities>(
      `/teams/${id}/shared-entities`,
    );
    return response.data;
  },

  create: async (data: CreateTeamRequest): Promise<TeamDetail> => {
    const response = await api.post<TeamDetail>("/teams", data);
    return response.data;
  },

  update: async (
    id: string,
    data: UpdateTeamRequest,
  ): Promise<Team> => {
    const response = await api.patch<Team>(`/teams/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/teams/${id}`);
  },

  addMember: async (
    id: string,
    data: AddTeamMemberRequest,
  ): Promise<TeamDetail> => {
    const response = await api.post<TeamDetail>(`/teams/${id}/members`, data);
    return response.data;
  },

  removeMember: async (id: string, userId: string): Promise<void> => {
    await api.delete(`/teams/${id}/members/${userId}`);
  },
};

export const credentialsApi = {
  list: async (): Promise<CredentialListItem[]> => {
    const response = await api.get<CredentialListItem[]>("/credentials");
    return response.data;
  },

  listByType: async (type: CredentialType): Promise<CredentialListItem[]> => {
    const response = await api.get<CredentialListItem[]>(
      `/credentials/by-type/${type}`,
    );
    return response.data;
  },

  listLLM: async (): Promise<CredentialListItem[]> => {
    const response = await api.get<CredentialListItem[]>("/credentials/llm");
    return response.data;
  },

  getAvailable: async (): Promise<CredentialForIntellisense[]> => {
    const response = await api.get<CredentialForIntellisense[]>(
      "/credentials/available",
    );
    return response.data;
  },

  get: async (id: string): Promise<Credential> => {
    const response = await api.get<Credential>(`/credentials/${id}`);
    return response.data;
  },

  create: async (data: CreateCredentialRequest): Promise<Credential> => {
    const response = await api.post<Credential>("/credentials", data);
    return response.data;
  },

  update: async (
    id: string,
    data: UpdateCredentialRequest,
  ): Promise<Credential> => {
    const response = await api.put<Credential>(`/credentials/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/credentials/${id}`);
  },

  getModels: async (id: string): Promise<LLMModel[]> => {
    const response = await api.get<LLMModel[]>(`/credentials/${id}/models`);
    return response.data;
  },

  listShares: async (id: string): Promise<CredentialShare[]> => {
    const response = await api.get<CredentialShare[]>(
      `/credentials/${id}/shares`,
    );
    return response.data;
  },

  addShare: async (id: string, email: string): Promise<CredentialShare> => {
    const response = await api.post<CredentialShare>(
      `/credentials/${id}/shares`,
      { email },
    );
    return response.data;
  },

  removeShare: async (id: string, userId: string): Promise<void> => {
    await api.delete(`/credentials/${id}/shares/${userId}`);
  },
  listTeamShares: async (id: string): Promise<TeamShare[]> => {
    const response = await api.get<TeamShare[]>(
      `/credentials/${id}/team-shares`,
    );
    return response.data;
  },
  addTeamShare: async (id: string, teamId: string): Promise<TeamShare> => {
    const response = await api.post<TeamShare>(
      `/credentials/${id}/team-shares`,
      { team_id: teamId },
    );
    return response.data;
  },
  removeTeamShare: async (id: string, teamId: string): Promise<void> => {
    await api.delete(`/credentials/${id}/team-shares/${teamId}`);
  },

  googleSheetsOAuthAuthorize: async (credentialId: string): Promise<{ auth_url: string }> => {
    const response = await api.post<{ auth_url: string }>(
      "/credentials/google-sheets/oauth/authorize",
      { credential_id: credentialId },
    );
    return response.data;
  },

  bigQueryOAuthAuthorize: async (credentialId: string): Promise<{ auth_url: string }> => {
    const response = await api.post<{ auth_url: string }>(
      "/credentials/bigquery/oauth/authorize",
      { credential_id: credentialId },
    );
    return response.data;
  },
};

export const gristApi = {
  getColumns: async (docId: string, tableId: string): Promise<{ id: string; name: string; type: string }[]> => {
    const response = await api.get<{ columns: { id: string; name: string; type: string }[] }>(
      `/workflows/grist/columns?doc_id=${docId}&table_id=${tableId}`,
    );
    return response.data.columns;
  },
};

export const globalVariablesApi = {
  list: async (): Promise<GlobalVariableListItem[]> => {
    const response = await api.get<GlobalVariableListItem[]>(
      "/global-variables",
    );
    return response.data;
  },

  get: async (id: string): Promise<GlobalVariable> => {
    const response = await api.get<GlobalVariable>(
      `/global-variables/${id}`,
    );
    return response.data;
  },

  create: async (
    data: CreateGlobalVariableRequest,
  ): Promise<GlobalVariable> => {
    const response = await api.post<GlobalVariable>(
      "/global-variables",
      data,
    );
    return response.data;
  },

  update: async (
    id: string,
    data: UpdateGlobalVariableRequest,
  ): Promise<GlobalVariable> => {
    const response = await api.patch<GlobalVariable>(
      `/global-variables/${id}`,
      data,
    );
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/global-variables/${id}`);
  },

  bulkDelete: async (ids: string[]): Promise<void> => {
    await api.post("/global-variables/bulk-delete", { ids });
  },

  listShares: async (id: string): Promise<GlobalVariableShare[]> => {
    const response = await api.get<GlobalVariableShare[]>(
      `/global-variables/${id}/shares`,
    );
    return response.data;
  },

  addShare: async (id: string, email: string): Promise<GlobalVariableShare> => {
    const response = await api.post<GlobalVariableShare>(
      `/global-variables/${id}/shares`,
      { email },
    );
    return response.data;
  },

  removeShare: async (id: string, userId: string): Promise<void> => {
    await api.delete(`/global-variables/${id}/shares/${userId}`);
  },
  listTeamShares: async (id: string): Promise<TeamShare[]> => {
    const response = await api.get<TeamShare[]>(
      `/global-variables/${id}/team-shares`,
    );
    return response.data;
  },
  addTeamShare: async (id: string, teamId: string): Promise<TeamShare> => {
    const response = await api.post<TeamShare>(
      `/global-variables/${id}/team-shares`,
      { team_id: teamId },
    );
    return response.data;
  },
  removeTeamShare: async (id: string, teamId: string): Promise<void> => {
    await api.delete(`/global-variables/${id}/team-shares/${teamId}`);
  },
};

export interface WorkflowInputField {
  key: string;
  defaultValue?: string;
}

export interface OutputNodeInfo {
  label: string;
  node_type: string;
  output_expression: string | null;
}

export interface WorkflowWithInputs {
  id: string;
  name: string;
  description: string | null;
  input_fields: WorkflowInputField[];
  output_node: OutputNodeInfo | null;
  created_at: string;
  updated_at: string;
}

export interface AIAssistantRequest {
  credentialId: string;
  model: string;
  message: string;
  currentWorkflow?: {
    id?: string;
    name?: string;
    description?: string | null;
    nodes: unknown[];
    edges: unknown[];
  };
  conversationHistory?: Array<{ role: string; content: string }>;
  availableWorkflows?: Array<{
    id: string;
    name: string;
    description?: string | null;
    input_fields?: WorkflowInputField[];
    output_node?: OutputNodeInfo | null;
  }>;
  askMode?: boolean;
}

export interface FixTranscriptionRequest {
  credentialId: string;
  model: string;
  text: string;
}

export interface FixTranscriptionResponse {
  fixed_text: string;
}

export interface FileAttachmentPayload {
  name: string;
  kind: "text" | "image" | "pdf";
  content: string;
}

export interface DashboardChatRequest {
  credentialId: string;
  model: string;
  message: string;
  conversationHistory?: Array<{ role: string; content: string }>;
  chatSurface?: "dashboard" | "documentation";
  /** User rules / custom instructions from settings; included in dashboard chat if set. */
  userRules?: string | null;
  /** Client local date and time (one line), sent at request time. */
  clientLocalDatetime?: string | null;
  attachment?: FileAttachmentPayload;
}

export interface DashboardChatPendingReview {
  summary: string;
  reviewUrl: string;
  draftText: string;
}

export const configApi = {
  getReservedVariableNames: async (): Promise<string[]> => {
    const response = await api.get<string[]>("/config/reserved-variable-names");
    return response.data;
  },
};

export interface VectorStoreStats {
  vector_count: number;
  points_count: number;
  status: string;
}

export interface VectorStoreListItem {
  id: string;
  name: string;
  description: string | null;
  collection_name: string;
  created_at: string;
  updated_at: string;
  is_shared: boolean;
  shared_by: string | null;
  stats: VectorStoreStats | null;
}

export interface VectorStore {
  id: string;
  name: string;
  description: string | null;
  collection_name: string;
  owner_id: string;
  credential_id: string;
  created_at: string;
  updated_at: string;
  stats: VectorStoreStats | null;
}

export interface VectorStoreShare {
  id: string;
  user_id: string;
  email: string;
  name: string;
  shared_at: string;
}

export interface VectorStoreUploadResponse {
  chunks_processed: number;
  points_inserted: number;
}

export interface FileCheckItem {
  filename: string;
  file_size: number;
}

export interface DuplicateFile {
  filename: string;
  file_size: number;
  chunk_count: number;
}

export interface CheckDuplicatesResponse {
  duplicates: DuplicateFile[];
}

export interface VectorStoreItem {
  id: string;
  text: string;
  source: string | null;
  metadata: Record<string, unknown>;
}

export interface VectorStoreSourceGroup {
  source: string;
  file_size: number | null;
  chunk_count: number;
  items: VectorStoreItem[];
}

export interface VectorStoreItemsResponse {
  sources: VectorStoreSourceGroup[];
  total_items: number;
}

export const vectorStoresApi = {
  list: async (): Promise<VectorStoreListItem[]> => {
    const response = await api.get<VectorStoreListItem[]>("/vector-stores");
    return response.data;
  },

  get: async (id: string): Promise<VectorStore> => {
    const response = await api.get<VectorStore>(`/vector-stores/${id}`);
    return response.data;
  },

  create: async (data: {
    name: string;
    description?: string;
    credential_id: string;
    collection_name?: string;
  }): Promise<VectorStore> => {
    const response = await api.post<VectorStore>("/vector-stores", data);
    return response.data;
  },

  update: async (
    id: string,
    data: { name?: string; description?: string },
  ): Promise<VectorStore> => {
    const response = await api.put<VectorStore>(`/vector-stores/${id}`, data);
    return response.data;
  },

  delete: async (id: string, deleteCollection: boolean = true): Promise<void> => {
    await api.delete(`/vector-stores/${id}?delete_collection=${deleteCollection}`);
  },

  clone: async (id: string): Promise<VectorStore> => {
    const response = await api.post<VectorStore>(`/vector-stores/${id}/clone`);
    return response.data;
  },

  checkDuplicates: async (
    id: string,
    files: FileCheckItem[],
  ): Promise<CheckDuplicatesResponse> => {
    const response = await api.post<CheckDuplicatesResponse>(
      `/vector-stores/${id}/check-duplicates`,
      { files },
    );
    return response.data;
  },

  uploadFile: async (
    id: string,
    file: File,
    overrideDuplicates: boolean = false,
  ): Promise<VectorStoreUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post<VectorStoreUploadResponse>(
      `/vector-stores/${id}/upload?override_duplicates=${overrideDuplicates}`,
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      },
    );
    return response.data;
  },

  listShares: async (id: string): Promise<VectorStoreShare[]> => {
    const response = await api.get<VectorStoreShare[]>(
      `/vector-stores/${id}/shares`,
    );
    return response.data;
  },

  addShare: async (id: string, email: string): Promise<VectorStoreShare> => {
    const response = await api.post<VectorStoreShare>(
      `/vector-stores/${id}/shares`,
      { email },
    );
    return response.data;
  },

  removeShare: async (id: string, userId: string): Promise<void> => {
    await api.delete(`/vector-stores/${id}/shares/${userId}`);
  },
  listTeamShares: async (id: string): Promise<TeamShare[]> => {
    const response = await api.get<TeamShare[]>(
      `/vector-stores/${id}/team-shares`,
    );
    return response.data;
  },
  addTeamShare: async (id: string, teamId: string): Promise<TeamShare> => {
    const response = await api.post<TeamShare>(
      `/vector-stores/${id}/team-shares`,
      { team_id: teamId },
    );
    return response.data;
  },
  removeTeamShare: async (id: string, teamId: string): Promise<void> => {
    await api.delete(`/vector-stores/${id}/team-shares/${teamId}`);
  },

  listItems: async (id: string, limit: number = 1000, textTruncateLength: number = 5000): Promise<VectorStoreItemsResponse> => {
    const response = await api.get<VectorStoreItemsResponse>(
      `/vector-stores/${id}/items?limit=${limit}&text_truncate_length=${textTruncateLength}`,
    );
    return response.data;
  },

  deleteItemsBySource: async (id: string, source: string): Promise<void> => {
    await api.delete(`/vector-stores/${id}/items/by-source?source=${encodeURIComponent(source)}`);
  },

  deleteItem: async (id: string, pointId: string): Promise<void> => {
    await api.delete(`/vector-stores/${id}/items/${pointId}`);
  },
};

export interface MCPInputField {
  key: string;
  defaultValue?: string;
}

export interface MCPWorkflowItem {
  id: string;
  name: string;
  description: string | null;
  mcp_enabled: boolean;
  input_fields: MCPInputField[];
}

export interface MCPConfigResponse {
  mcp_api_key: string | null;
  mcp_endpoint_url: string;
  workflows: MCPWorkflowItem[];
}

export interface MCPRegenerateKeyResponse {
  mcp_api_key: string;
}

export interface MCPFetchToolItem {
  name: string;
  description: string;
}

export interface MCPFetchToolsResponse {
  tools: MCPFetchToolItem[];
}

export const mcpApi = {
  getConfig: async (): Promise<MCPConfigResponse> => {
    const response = await api.get<MCPConfigResponse>("/mcp/config");
    return response.data;
  },

  toggleWorkflow: async (
    workflowId: string,
    enabled: boolean,
  ): Promise<MCPWorkflowItem> => {
    const response = await api.patch<MCPWorkflowItem>(
      `/mcp/workflows/${workflowId}`,
      { mcp_enabled: enabled },
    );
    return response.data;
  },

  regenerateKey: async (): Promise<MCPRegenerateKeyResponse> => {
    const response = await api.post<MCPRegenerateKeyResponse>(
      "/mcp/regenerate-key",
    );
    return response.data;
  },

  fetchTools: async (
    connection: Record<string, unknown>,
  ): Promise<MCPFetchToolsResponse> => {
    const response = await api.post<MCPFetchToolsResponse>("/mcp/fetch-tools", {
      connection,
    });
    return response.data;
  },
};

export const traceApi = {
  list: async (params: {
    limit?: number;
    offset?: number;
    credentialId?: string;
    workflowId?: string;
    source?: string;
    status?: string;
    search?: string;
    order?: "asc" | "desc";
  }): Promise<LLMTraceListResponse> => {
    const response = await api.get<LLMTraceListResponse>("/traces", {
      params: {
        limit: params.limit,
        offset: params.offset,
        credential_id: params.credentialId,
        workflow_id: params.workflowId,
        source: params.source,
        status: params.status,
        search: params.search,
        order: params.order,
      },
    });
    return response.data;
  },

  get: async (id: string): Promise<LLMTraceDetail> => {
    const response = await api.get<LLMTraceDetail>(`/traces/${id}`);
    return response.data;
  },

  clear: async (): Promise<void> => {
    await api.delete("/traces");
  },
};

export const aiApi = {
  fixTranscription: async (
    request: FixTranscriptionRequest,
  ): Promise<FixTranscriptionResponse> => {
    const response = await api.post<FixTranscriptionResponse>(
      "/ai/fix-transcription",
      {
        credential_id: request.credentialId,
        model: request.model,
        text: request.text,
      },
    );
    return response.data;
  },

  assistantStream: (
    request: AIAssistantRequest,
    onContent: (text: string) => void,
    onDone: () => void,
    onError: (error: Error) => void,
    signal?: AbortSignal,
  ): void => {
    const API_URL = import.meta.env.VITE_API_URL || "";

    fetch(`${API_URL}/api/ai/workflow-assistant`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...heymClientHeaders,
      },
      body: JSON.stringify({
        credential_id: request.credentialId,
        model: request.model,
        message: request.message,
        current_workflow: request.currentWorkflow,
        conversation_history: request.conversationHistory,
        available_workflows: request.availableWorkflows,
        ask_mode: request.askMode ?? false,
      }),
      signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.detail || `HTTP error! status: ${response.status}`,
          );
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }

        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const data = JSON.parse(line.slice(6));

              if (data.type === "content") {
                onContent(data.text);
              } else if (data.type === "done") {
                onDone();
              } else if (data.type === "error") {
                throw new Error(data.message);
              }
            }
          }
        }
      })
      .catch(onError);
  },

  dashboardChatStream: (
    request: DashboardChatRequest,
    onContent: (text: string) => void,
    onDone: () => void,
    onError: (error: Error) => void,
    signal?: AbortSignal,
    onStep?: (label: string) => void,
    onToolOutput?: (images: string[]) => void,
    onWorkflowPending?: (payload: DashboardChatPendingReview) => void,
  ): void => {
    const API_URL = import.meta.env.VITE_API_URL || "";

    fetch(`${API_URL}/api/ai/dashboard-chat`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...heymClientHeaders,
      },
      body: JSON.stringify({
        credential_id: request.credentialId,
        model: request.model,
        message: request.message,
        conversation_history: request.conversationHistory,
        ...(request.chatSurface ? { chat_surface: request.chatSurface } : {}),
        ...(request.userRules?.trim()
          ? { user_rules: request.userRules.trim() }
          : {}),
        ...(request.clientLocalDatetime?.trim()
          ? { client_local_datetime: request.clientLocalDatetime.trim() }
          : {}),
        ...(request.attachment
          ? {
              attachment: {
                name: request.attachment.name,
                kind: request.attachment.kind,
                content: request.attachment.content,
              },
            }
          : {}),
      }),
      signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.detail || `HTTP error! status: ${response.status}`,
          );
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }

        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const data = JSON.parse(line.slice(6));

              if (data.type === "content") {
                onContent(data.text);
              } else if (data.type === "done") {
                onDone();
              } else if (data.type === "step" && onStep && data.label) {
                onStep(data.label);
              } else if (
                data.type === "tool_output" &&
                onToolOutput &&
                Array.isArray(data.images) &&
                data.images.length > 0
              ) {
                onToolOutput(data.images);
              } else if (
                data.type === "workflow_pending" &&
                onWorkflowPending &&
                typeof data.review_url === "string"
              ) {
                onWorkflowPending({
                  summary: typeof data.summary === "string" ? data.summary : "",
                  reviewUrl: data.review_url,
                  draftText: typeof data.draft_text === "string" ? data.draft_text : "",
                });
              } else if (data.type === "error") {
                throw new Error(data.message);
              }
            }
          }
        }
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        onError(error instanceof Error ? error : new Error("Dashboard chat failed"));
      });
  },
};

export interface PortalSettings {
  portal_enabled: boolean;
  portal_slug: string | null;
  portal_stream_enabled: boolean;
  portal_file_upload_enabled: boolean;
  portal_file_config: Record<
    string,
    { file_upload_enabled: boolean; allowed_types: string[]; max_size_mb: number }
  >;
  input_fields: Array<{ key: string; defaultValue?: string }>;
}

export interface PortalSettingsUpdate {
  portal_enabled?: boolean;
  portal_slug?: string;
  portal_stream_enabled?: boolean;
  portal_file_upload_enabled?: boolean;
  portal_file_config?: Record<
    string,
    { file_upload_enabled: boolean; allowed_types: string[]; max_size_mb: number }
  >;
}

export interface PortalUser {
  id: string;
  username: string;
  created_at: string;
}

export interface PortalUserCreate {
  username: string;
  password: string;
}

export const portalApi = {
  getSettings: async (workflowId: string): Promise<PortalSettings> => {
    const response = await api.get<PortalSettings>(`/workflows/${workflowId}/portal`);
    return response.data;
  },

  updateSettings: async (
    workflowId: string,
    data: PortalSettingsUpdate,
  ): Promise<PortalSettings> => {
    const response = await api.put<PortalSettings>(`/workflows/${workflowId}/portal`, data);
    return response.data;
  },

  listUsers: async (workflowId: string): Promise<PortalUser[]> => {
    const response = await api.get<PortalUser[]>(`/workflows/${workflowId}/portal/users`);
    return response.data;
  },

  createUser: async (workflowId: string, data: PortalUserCreate): Promise<PortalUser> => {
    const response = await api.post<PortalUser>(`/workflows/${workflowId}/portal/users`, data);
    return response.data;
  },

  deleteUser: async (workflowId: string, userId: string): Promise<void> => {
    await api.delete(`/workflows/${workflowId}/portal/users/${userId}`);
  },
};

export const hitlApi = {
  get: async (token: string): Promise<HITLReview> => {
    const response = await api.get<HITLReview>(`/hitl/${token}`);
    return response.data;
  },

  decide: async (
    token: string,
    payload: HITLDecisionPayload,
  ): Promise<{ request_id: string; status: string }> => {
    const response = await api.post<{ request_id: string; status: string }>(
      `/hitl/${token}/decision`,
      payload,
    );
    return response.data;
  },
};

export const analyticsApi = {
  getStats: async (
    workflowId?: string,
    options: AnalyticsQueryOptions = {},
  ): Promise<AnalyticsStats> => {
    const params = buildAnalyticsQueryParams(options);
    if (workflowId) {
      const response = await api.get<AnalyticsStats>(
        `/analytics/stats/${workflowId}`,
        { params },
      );
      return response.data;
    }
    const response = await api.get<AnalyticsStats>("/analytics/stats", { params });
    return response.data;
  },

  getMetrics: async (
    workflowId?: string,
    options: AnalyticsQueryOptions = {},
  ): Promise<TimeSeriesMetrics> => {
    const params = buildAnalyticsQueryParams(options);
    if (workflowId) {
      const response = await api.get<TimeSeriesMetrics>(
        `/analytics/metrics/${workflowId}`,
        { params },
      );
      return response.data;
    }
    const response = await api.get<TimeSeriesMetrics>("/analytics/metrics", {
      params,
    });
    return response.data;
  },

  getWorkflowBreakdown: async (
    options: AnalyticsQueryOptions = {},
    limit: number = 10,
  ): Promise<WorkflowBreakdownItem[]> => {
    const params: Record<string, string | number> = {
      ...buildAnalyticsQueryParams(options),
      limit,
    };
    const response = await api.get<WorkflowBreakdownResponse>("/analytics/workflows", {
      params,
    });
    return response.data.items;
  },
};

function buildAnalyticsQueryParams(options: AnalyticsQueryOptions): Record<string, string> {
  const params: Record<string, string> = {
    time_range: options.timeRange ?? "7d",
  };

  if (options.bucketSize) {
    params.bucket_size = options.bucketSize;
  }
  if (options.dateRange) {
    params.start_at = options.dateRange.startAt;
    params.end_at = options.dateRange.endAt;
  }

  return params;
}

export const evalsApi = {
  listSuites: async (): Promise<EvalSuiteListItem[]> => {
    const response = await api.get<EvalSuiteListItem[]>("/evals/suites");
    return response.data;
  },

  createSuite: async (data: CreateSuiteRequest): Promise<EvalSuite> => {
    const response = await api.post<EvalSuite>("/evals/suites", data);
    return response.data;
  },

  getSuite: async (id: string): Promise<EvalSuite> => {
    const response = await api.get<EvalSuite>(`/evals/suites/${id}`);
    return response.data;
  },

  updateSuite: async (
    id: string,
    data: UpdateSuiteRequest,
  ): Promise<EvalSuite> => {
    const response = await api.patch<EvalSuite>(`/evals/suites/${id}`, data);
    return response.data;
  },

  deleteSuite: async (id: string): Promise<void> => {
    await api.delete(`/evals/suites/${id}`);
  },

  addTestCase: async (
    suiteId: string,
    data: CreateTestCaseRequest,
  ): Promise<import("@/types/evals").EvalTestCase> => {
    const response = await api.post(
      `/evals/suites/${suiteId}/test-cases`,
      data,
    );
    return response.data;
  },

  updateTestCase: async (
    suiteId: string,
    tcId: string,
    data: UpdateTestCaseRequest,
  ): Promise<import("@/types/evals").EvalTestCase> => {
    const response = await api.patch(
      `/evals/suites/${suiteId}/test-cases/${tcId}`,
      data,
    );
    return response.data;
  },

  deleteTestCase: async (
    suiteId: string,
    tcId: string,
  ): Promise<void> => {
    await api.delete(`/evals/suites/${suiteId}/test-cases/${tcId}`);
  },

  optimizePrompt: async (
    suiteId: string,
    data: OptimizePromptRequest,
  ): Promise<OptimizePromptResponse> => {
    const response = await api.post<OptimizePromptResponse>(
      `/evals/suites/${suiteId}/optimize-prompt`,
      data,
    );
    return response.data;
  },

  generateTestData: async (
    suiteId: string,
    data: GenerateTestDataRequest,
  ): Promise<GenerateTestDataResponse> => {
    const response = await api.post<GenerateTestDataResponse>(
      `/evals/suites/${suiteId}/generate-test-data`,
      data,
    );
    return response.data;
  },

  runEvals: async (suiteId: string, data: RunEvalsRequest): Promise<EvalRun> => {
    const response = await api.post<EvalRun>(
      `/evals/suites/${suiteId}/run`,
      data,
    );
    return response.data;
  },

  getRun: async (runId: string): Promise<EvalRun> => {
    const response = await api.get<EvalRun>(`/evals/runs/${runId}`);
    return response.data;
  },

  listRuns: async (suiteId: string): Promise<EvalRunListItem[]> => {
    const response = await api.get<EvalRunListItem[]>(
      `/evals/suites/${suiteId}/runs`,
    );
    return response.data;
  },

  renameRun: async (
    runId: string,
    name: string,
  ): Promise<{ name: string }> => {
    const response = await api.patch<{ name: string }>(
      `/evals/runs/${runId}`,
      { name },
    );
    return response.data;
  },

  deleteRun: async (runId: string): Promise<void> => {
    await api.delete(`/evals/runs/${runId}`);
  },

  clearAllRuns: async (suiteId: string): Promise<void> => {
    await api.delete(`/evals/suites/${suiteId}/runs`);
  },
};

export const logsApi = {
  getDockerLogs: async (
    containerName: string,
    lines: number = 100,
    since?: string,
  ): Promise<string> => {
    const params: Record<string, string | number> = { lines };
    if (since) {
      params.since = since;
    }
    const response = await api.get<{ logs: string; container: string }>(
      `/logs/docker/${containerName}`,
      { params },
    );
    return response.data.logs;
  },

  streamDockerLogs: (
    containerName: string,
    onLog: (log: string) => void,
    onError: (error: Error) => void,
  ): (() => void) => {
    const API_URL = import.meta.env.VITE_API_URL || "";
    let aborted = false;

    fetch(`${API_URL}/api/logs/docker/${containerName}/stream`, {
      credentials: "include",
      headers: { ...heymClientHeaders },
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              onLog(line.slice(6));
            } else if (line.trim()) {
              onLog(line);
            }
          }
        }
      })
      .catch((error) => {
        if (!aborted) {
          onError(error);
        }
      });

    return () => {
      aborted = true;
    };
  },
};

export const templatesApi = {
  list(params?: { type?: "workflow" | "node"; search?: string }): Promise<TemplateListResponse> {
    return api.get("/templates", { params }).then((r) => r.data);
  },

  getWorkflow(id: string): Promise<WorkflowTemplate> {
    return api.get(`/templates/workflow/${id}`).then((r) => r.data);
  },

  getNode(id: string): Promise<NodeTemplate> {
    return api.get(`/templates/node/${id}`).then((r) => r.data);
  },

  create(payload: CreateTemplateRequest): Promise<WorkflowTemplate | NodeTemplate> {
    return api.post("/templates", payload).then((r) => r.data);
  },

  useWorkflow(id: string): Promise<WorkflowTemplate> {
    return api.post(`/templates/workflow/${id}/use`).then((r) => r.data);
  },

  useNode(id: string): Promise<NodeTemplate> {
    return api.post(`/templates/node/${id}/use`).then((r) => r.data);
  },

  updateWorkflow(
    id: string,
    payload: {
      name?: string;
      description?: string;
      tags?: string[];
      visibility?: string;
      shared_with?: string[];
      shared_with_teams?: string[];
    },
  ): Promise<WorkflowTemplate> {
    return api.patch(`/templates/workflow/${id}`, payload).then((r) => r.data);
  },

  updateNode(
    id: string,
    payload: {
      name?: string;
      description?: string;
      tags?: string[];
      visibility?: string;
      shared_with?: string[];
      shared_with_teams?: string[];
    },
  ): Promise<NodeTemplate> {
    return api.patch(`/templates/node/${id}`, payload).then((r) => r.data);
  },

  deleteWorkflow(id: string): Promise<void> {
    return api.delete(`/templates/workflow/${id}`).then(() => undefined);
  },

  deleteNode(id: string): Promise<void> {
    return api.delete(`/templates/node/${id}`).then(() => undefined);
  },
};

// ---------- Files / Drive ----------

import type {
  CreateShareRequest,
  FileAccessToken,
  FileListParams,
  FileListResponse,
  GeneratedFile,
} from "@/types/file";

export const filesApi = {
  list: async (params?: FileListParams): Promise<FileListResponse> => {
    const response = await api.get<FileListResponse>("/files", { params });
    return response.data;
  },

  get: async (fileId: string): Promise<GeneratedFile> => {
    const response = await api.get<GeneratedFile>(`/files/${fileId}`);
    return response.data;
  },

  delete: async (fileId: string): Promise<void> => {
    await api.delete(`/files/${fileId}`);
  },

  clearAll: async (): Promise<void> => {
    await api.delete("/files");
  },

  upload: async (file: File): Promise<GeneratedFile> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post<GeneratedFile>("/files/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  createShare: async (
    fileId: string,
    data: CreateShareRequest,
  ): Promise<FileAccessToken> => {
    const response = await api.post<FileAccessToken>(`/files/${fileId}/share`, data);
    return response.data;
  },

  listShares: async (fileId: string): Promise<FileAccessToken[]> => {
    const response = await api.get<FileAccessToken[]>(`/files/${fileId}/share`);
    return response.data;
  },

  revokeShare: async (fileId: string, tokenId: string): Promise<void> => {
    await api.delete(`/files/${fileId}/share/${tokenId}`);
  },
};

// ---------- Data Tables ----------

import type {
  DataTable,
  DataTableImportResult,
  DataTableListItem,
  DataTableRow,
  DataTableShare,
  DataTableTeamShare,
} from "@/types/dataTable";

export const dataTablesApi = {
  list: async (): Promise<DataTableListItem[]> => {
    const response = await api.get<DataTableListItem[]>("/data-tables");
    return response.data;
  },

  get: async (id: string): Promise<DataTable> => {
    const response = await api.get<DataTable>(`/data-tables/${id}`);
    return response.data;
  },

  create: async (data: { name: string; description?: string; columns?: unknown[] }): Promise<DataTable> => {
    const response = await api.post<DataTable>("/data-tables", data);
    return response.data;
  },

  update: async (id: string, data: { name?: string; description?: string; columns?: unknown[] }): Promise<DataTable> => {
    const response = await api.put<DataTable>(`/data-tables/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/data-tables/${id}`);
  },

  listRows: async (id: string, limit = 50, offset = 0): Promise<DataTableRow[]> => {
    const response = await api.get<DataTableRow[]>(`/data-tables/${id}/rows?limit=${limit}&offset=${offset}`);
    return response.data;
  },

  createRow: async (id: string, data: Record<string, unknown>): Promise<DataTableRow> => {
    const response = await api.post<DataTableRow>(`/data-tables/${id}/rows`, { data });
    return response.data;
  },

  updateRow: async (id: string, rowId: string, data: Record<string, unknown>): Promise<DataTableRow> => {
    const response = await api.put<DataTableRow>(`/data-tables/${id}/rows/${rowId}`, { data });
    return response.data;
  },

  deleteRow: async (id: string, rowId: string): Promise<void> => {
    await api.delete(`/data-tables/${id}/rows/${rowId}`);
  },

  clearRows: async (id: string): Promise<void> => {
    await api.delete(`/data-tables/${id}/rows`);
  },

  bulkCreateRows: async (id: string, rows: Array<{ data: Record<string, unknown> }>): Promise<DataTableImportResult> => {
    const response = await api.post<DataTableImportResult>(`/data-tables/${id}/rows/bulk`, rows);
    return response.data;
  },

  importCsv: async (id: string, file: File): Promise<DataTableImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post<DataTableImportResult>(`/data-tables/${id}/import-csv`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  exportCsv: async (id: string): Promise<Blob> => {
    const response = await api.get(`/data-tables/${id}/export-csv`, { responseType: "blob" });
    return response.data;
  },

  listShares: async (id: string): Promise<DataTableShare[]> => {
    const response = await api.get<DataTableShare[]>(`/data-tables/${id}/shares`);
    return response.data;
  },

  addShare: async (id: string, email: string, permission = "read"): Promise<DataTableShare> => {
    const response = await api.post<DataTableShare>(`/data-tables/${id}/shares`, { email, permission });
    return response.data;
  },

  removeShare: async (id: string, userId: string): Promise<void> => {
    await api.delete(`/data-tables/${id}/shares/${userId}`);
  },

  listTeamShares: async (id: string): Promise<DataTableTeamShare[]> => {
    const response = await api.get<DataTableTeamShare[]>(`/data-tables/${id}/team-shares`);
    return response.data;
  },

  addTeamShare: async (id: string, teamId: string, permission = "read"): Promise<DataTableTeamShare> => {
    const response = await api.post<DataTableTeamShare>(`/data-tables/${id}/team-shares`, { team_id: teamId, permission });
    return response.data;
  },

  removeTeamShare: async (id: string, teamId: string): Promise<void> => {
    await api.delete(`/data-tables/${id}/team-shares/${teamId}`);
  },
};

export const expressionApi = {
  evaluate: async (
    request: ExpressionEvaluateRequest,
  ): Promise<ExpressionEvaluateResponse> => {
    const response = await api.post<ExpressionEvaluateResponse>(
      "/expressions/evaluate",
      request,
    );
    return response.data;
  },
};

export default api;
