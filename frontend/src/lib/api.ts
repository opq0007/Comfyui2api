import { getAdminToken } from "./auth";

export type TaskStatus = "pending" | "queued" | "running" | "completed" | "failed";

export interface TaskOutput {
  filename: string;
  url: string;
  media_type?: string | null;
  node_id?: string | null;
  output_key?: string | null;
}

export interface TaskRecord {
  job_id: string;
  created_at: number;
  created_at_utc: string;
  started_at_utc?: string | null;
  finished_at_utc?: string | null;
  updated_at_utc?: string | null;
  duration_s?: number | null;
  platform: string;
  kind: string;
  workflow: string;
  requested_model?: string | null;
  model_slug?: string | null;
  instance_slug?: string | null;
  status: TaskStatus;
  progress_percent: number;
  progress?: Record<string, unknown> | null;
  prompt_id?: string | null;
  queue_number?: number | null;
  current_node?: string | null;
  url?: string | null;
  output_count: number;
  error?: string | null;
  prompt_preview?: string | null;
  request_json?: Record<string, unknown>;
  outputs?: TaskOutput[];
}

export interface TaskListResponse {
  total: number;
  counts: Record<TaskStatus, number>;
  items: TaskRecord[];
}

export interface TaskDetailResponse {
  task: TaskRecord;
  outputs: TaskOutput[];
}

export interface AdminStats {
  counts: Record<TaskStatus, number>;
  instance_count: number;
  healthy_instance_count: number;
  workflows_dir: string;
  runs_dir: string;
  database_path: string;
  ui_enabled: boolean;
}

export type InstanceHealth = "unknown" | "healthy" | "unhealthy" | "disabled";

export interface InstanceRecord {
  slug: string;
  display_name?: string | null;
  base_url: string;
  enabled: boolean;
  max_in_flight: number;
  health_interval_s?: number | null;
  has_auth_token: boolean;
  health: InstanceHealth;
  consecutive_failures: number;
  last_check_at?: number | null;
  last_error?: string | null;
  in_flight: number;
  bound_model_count: number;
}

export interface ExternalModelRecord {
  slug: string;
  display_name?: string | null;
  workflow_name?: string | null;
  routing_policy: "round_robin" | "random";
  enabled: boolean;
  instance_slugs: string[];
  kind: string[];
  workflow_available: boolean;
  ready: boolean;
}

export interface TaskFilters {
  start?: string;
  end?: string;
  q?: string;
  status?: string;
  kind?: string;
  platform?: string;
}

export interface WorkflowItem {
  name: string;
  kind?: string | null;
  available: boolean;
  load_error?: string | null;
  parameter_error?: string | null;
}

export interface WorkflowListResponse {
  workflows_dir: string;
  items: WorkflowItem[];
}

export interface SnapshotEvent {
  type: "snapshot";
  data: TaskListResponse;
}

export interface TaskUpdatedEvent {
  type: "task_updated";
  event: string;
  ts: string;
  job: TaskRecord;
}

export type AdminWsEvent = SnapshotEvent | TaskUpdatedEvent;

export class AuthError extends Error {
  constructor() {
    super("Unauthorized");
  }
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function listTasks(filters: TaskFilters, limit = 200, offset = 0): Promise<TaskListResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(Math.min(200, Math.max(1, limit))));
  params.set("offset", String(Math.max(0, offset)));
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  return requestJson<TaskListResponse>(`/v1/admin/tasks?${params.toString()}`);
}

export async function getTask(jobId: string): Promise<TaskDetailResponse> {
  return requestJson<TaskDetailResponse>(`/v1/admin/tasks/${encodeURIComponent(jobId)}`);
}

export async function getStats(): Promise<AdminStats> {
  return requestJson<AdminStats>("/v1/admin/stats");
}

export async function listWorkflows(): Promise<WorkflowListResponse> {
  return requestJson<WorkflowListResponse>("/v1/admin/workflows");
}

export async function listInstances(): Promise<{ items: InstanceRecord[] }> {
  return requestJson<{ items: InstanceRecord[] }>("/v1/admin/instances");
}

export async function createInstance(body: Record<string, unknown>): Promise<InstanceRecord> {
  return requestJson<InstanceRecord>("/v1/admin/instances", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

export async function patchInstance(slug: string, body: Record<string, unknown>): Promise<InstanceRecord> {
  return requestJson<InstanceRecord>(`/v1/admin/instances/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

export async function deleteInstance(slug: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/v1/admin/instances/${encodeURIComponent(slug)}`, { method: "DELETE" });
}

export async function listModels(): Promise<{ items: ExternalModelRecord[] }> {
  return requestJson<{ items: ExternalModelRecord[] }>("/v1/admin/models");
}

export async function createModel(body: Record<string, unknown>): Promise<ExternalModelRecord> {
  return requestJson<ExternalModelRecord>("/v1/admin/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

export async function patchModel(slug: string, body: Record<string, unknown>): Promise<ExternalModelRecord> {
  return requestJson<ExternalModelRecord>(`/v1/admin/models/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

export async function deleteModel(slug: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/v1/admin/models/${encodeURIComponent(slug)}`, { method: "DELETE" });
}

export async function shutdownApp(): Promise<{ status: string }> {
  return requestJson<{ status: string }>("/v1/admin/shutdown", { method: "POST" });
}

export function adminWsUrl(token: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL("/v1/admin/tasks/ws", `${protocol}//${window.location.host}`);
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const token = getAdminToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    throw new AuthError();
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: { message?: string }; detail?: unknown };
    return payload.error?.message ?? String(payload.detail ?? response.statusText);
  } catch {
    return response.statusText;
  }
}
