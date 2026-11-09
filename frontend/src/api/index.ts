import axios from "axios";
import type {
  Annotation,
  AnnotationCasePage,
  ApiToken,
  ApiTokenCreated,
  CaseItem,
  CasePage,
  Dataset,
  DatasetHierarchyPage,
  DatasetTaskSummary,
  Dashboard,
  DeviceAuthorizationInfo,
  DeviceCodeResponse,
  DeviceTokenResponse,
  EvaluationJob,
  ExportJob,
  ExternalEvaluation,
  ImportJob,
  ImportReport,
  LabelSchema,
  LoginResponse,
  MetricPoint,
  ModalitySpec,
  ScanProtocol,
  ScopeSpec,
  SliceInfo,
  StudioExperiment,
  StudioReadiness,
  StudioTaskSummary,
  TableInfo,
  TablePage,
  Task,
  TaskDatasetLink,
  TaskStats,
  TaskTypeSpec,
  User,
} from "./types";

export const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("mp_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem("mp_token");
      if (window.location.pathname !== "/login") {
        const next = encodeURIComponent(
          window.location.pathname + window.location.search,
        );
        window.location.href = `/login?next=${next}`;
      }
    }
    return Promise.reject(error);
  },
);

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item: any) => item?.msg ?? JSON.stringify(item))
        .join("；");
    }
    if (error.response?.data?.message) return String(error.response.data.message);
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return String(error);
}

export const authApi = {
  login: async (username: string, password: string) => {
    const { data } = await api.post<LoginResponse>("/auth/login", { username, password });
    return data;
  },
  me: async () => {
    const { data } = await api.get<User>("/auth/me");
    return data;
  },
  scopes: async () => (await api.get<ScopeSpec[]>("/auth/scopes")).data,
  tokens: async () => (await api.get<ApiToken[]>("/auth/tokens")).data,
  createToken: async (payload: {
    name: string;
    repo_key?: string;
    scopes: string[];
    expires_in_days: number;
  }) => (await api.post<ApiTokenCreated>("/auth/tokens", payload)).data,
  revokeToken: async (id: string) =>
    (await api.post<ApiToken>(`/auth/tokens/${id}/revoke`)).data,
  deleteToken: async (id: string) => {
    await api.delete(`/auth/tokens/${id}`);
  },
  deviceCode: async (payload: {
    client_name?: string;
    repo_key?: string;
    scopes?: string[];
  }) =>
    (await api.post<DeviceCodeResponse>("/auth/device/code", payload)).data,
  deviceToken: async (device_code: string) =>
    (await api.post<DeviceTokenResponse>("/auth/device/token", { device_code })).data,
  deviceLookup: async (user_code: string) =>
    (await api.post<DeviceAuthorizationInfo>("/auth/device/lookup", { user_code })).data,
  deviceApprove: async (user_code: string) =>
    (await api.post<DeviceAuthorizationInfo>("/auth/device/approve", { user_code })).data,
  deviceDeny: async (user_code: string) =>
    (await api.post<DeviceAuthorizationInfo>("/auth/device/deny", { user_code })).data,
};

export const metaApi = {
  modalities: async () => (await api.get<ModalitySpec[]>("/meta/modalities")).data,
  taskTypes: async () => (await api.get<TaskTypeSpec[]>("/meta/task-types")).data,
  roles: async () =>
    (await api.get<{ code: string; name: string }[]>("/meta/roles")).data,
};

export const protocolApi = {
  list: async (includeInactive = false) =>
    (
      await api.get<ScanProtocol[]>("/scan-protocols", {
        params: { include_inactive: includeInactive },
      })
    ).data,
  create: async (payload: Partial<ScanProtocol>) =>
    (await api.post<ScanProtocol>("/scan-protocols", payload)).data,
  update: async (id: string, payload: Partial<ScanProtocol>) =>
    (await api.patch<ScanProtocol>(`/scan-protocols/${id}`, payload)).data,
  remove: async (id: string) => {
    await api.delete(`/scan-protocols/${id}`);
  },
};

export const datasetApi = {
  list: async (params?: { modality?: string; status?: string; search?: string }) =>
    (await api.get<Dataset[]>("/datasets", { params })).data,
  get: async (id: string) => (await api.get<Dataset>(`/datasets/${id}`)).data,
  create: async (payload: {
    code: string;
    name: string;
    modality: string;
    scan_protocol_id: string;
    description?: string;
  }) => (await api.post<Dataset>("/datasets", payload)).data,
  update: async (id: string, payload: Partial<Dataset>) =>
    (await api.patch<Dataset>(`/datasets/${id}`, payload)).data,
  markReady: async (id: string) =>
    (await api.post<Dataset>(`/datasets/${id}/ready`)).data,
  archive: async (id: string) =>
    (await api.post<Dataset>(`/datasets/${id}/archive`)).data,
  cases: async (
    id: string,
    params?: { page?: number; page_size?: number; search?: string },
  ) => (await api.get<CasePage>(`/datasets/${id}/cases`, { params })).data,
  tasks: async (id: string) =>
    (await api.get<DatasetTaskSummary[]>(`/datasets/${id}/tasks`)).data,
  hierarchy: async (
    id: string,
    params?: {
      task_id?: string;
      search?: string;
      level?: "patient" | "study" | "series";
      page?: number;
      page_size?: number;
    },
  ) =>
    (await api.get<DatasetHierarchyPage>(`/datasets/${id}/hierarchy`, { params })).data,
  importPath: async (
    id: string,
    payload: {
      path: string;
      recursive: boolean;
      acknowledge_source_discarded: boolean;
    },
  ) =>
    (await api.post<ImportReport>(`/datasets/${id}/import-path`, payload)).data,
  importUpload: async (
    id: string,
    file: File,
    acknowledgeSourceDiscarded: boolean,
    onProgress?: (percent: number) => void,
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("acknowledge_source_discarded", String(acknowledgeSourceDiscarded));
    const { data } = await api.post<ImportReport>(`/datasets/${id}/import-upload`, form, {
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
    });
    return data;
  },
  createImportJob: async (
    id: string,
    payload: { path: string; recursive: boolean; acknowledge_source_discarded: boolean },
  ) => (await api.post<ImportJob>(`/datasets/${id}/import-jobs`, payload)).data,
  getImportJob: async (id: string, jobId: string) =>
    (await api.get<ImportJob>(`/datasets/${id}/import-jobs/${jobId}`)).data,
};

export const caseApi = {
  get: async (id: string) => (await api.get<CaseItem>(`/cases/${id}`)).data,
  sliceInfo: async (id: string) =>
    (await api.get<SliceInfo>(`/cases/${id}/slice-info`)).data,
  sliceBlob: async (
    id: string,
    params: { axis: string; index: number; window?: number; level?: number },
  ) =>
    (
      await api.get<Blob>(`/cases/${id}/slice`, {
        params,
        responseType: "blob",
      })
    ).data,
  tableInfo: async (id: string) =>
    (await api.get<TableInfo>(`/cases/${id}/table-info`)).data,
  tablePage: async (id: string, params: { offset: number; limit: number }) =>
    (await api.get<TablePage>(`/cases/${id}/table`, { params })).data,
};

export const taskApi = {
  list: async (params?: { task_type?: string; status?: string; search?: string }) =>
    (await api.get<Task[]>("/tasks", { params })).data,
  get: async (id: string) => (await api.get<Task>(`/tasks/${id}`)).data,
  create: async (payload: {
    code: string;
    name: string;
    task_type: string;
    description?: string;
    annotation_guide?: string;
    label_schema?: LabelSchema;
  }) => (await api.post<Task>("/tasks", payload)).data,
  update: async (id: string, payload: Partial<Task>) =>
    (await api.patch<Task>(`/tasks/${id}`, payload)).data,
  stats: async (id: string) => (await api.get<TaskStats>(`/tasks/${id}/stats`)).data,
  linkedDatasets: async (id: string) =>
    (await api.get<TaskDatasetLink[]>(`/tasks/${id}/datasets`)).data,
  linkDataset: async (id: string, datasetId: string) =>
    (await api.post<TaskDatasetLink>(`/tasks/${id}/datasets`, { dataset_id: datasetId }))
      .data,
  unlinkDataset: async (id: string, datasetId: string) => {
    await api.delete(`/tasks/${id}/datasets/${datasetId}`);
  },
};

export const annotationApi = {
  cases: async (
    taskId: string,
    params?: {
      status?: string;
      dataset_id?: string;
      search?: string;
      page?: number;
      page_size?: number;
    },
  ) =>
    (await api.get<AnnotationCasePage>(`/tasks/${taskId}/annotation-cases`, { params }))
      .data,
  get: async (taskId: string, caseId: string) =>
    (await api.get<Annotation>(`/tasks/${taskId}/annotations/${caseId}`)).data,
  saveData: async (taskId: string, caseId: string, data: Record<string, unknown>) =>
    (
      await api.put<Annotation>(`/tasks/${taskId}/annotations/${caseId}`, { data })
    ).data,
  saveMask: async (taskId: string, caseId: string, blob: Blob) => {
    const form = new FormData();
    form.append("file", blob, "mask.png");
    return (await api.put<Annotation>(`/tasks/${taskId}/annotations/${caseId}/mask`, form))
      .data;
  },
  saveMaskSlice: async (taskId: string, caseId: string, index: number, blob: Blob) => {
    const form = new FormData();
    form.append("file", blob, `slice_${index}.png`);
    return (
      await api.put<Annotation>(
        `/tasks/${taskId}/annotations/${caseId}/mask-slice`,
        form,
        { params: { axis: "axial", index } },
      )
    ).data;
  },
  maskSliceBlob: async (taskId: string, caseId: string, index: number) => {
    const response = await api.get<Blob>(
      `/tasks/${taskId}/annotations/${caseId}/mask-slice`,
      {
        params: { axis: "axial", index },
        responseType: "blob",
        validateStatus: (status) => (status >= 200 && status < 300) || status === 204,
      },
    );
    if (response.status === 204) return null;
    return response.data;
  },
  submit: async (annotationId: string) =>
    (await api.post<Annotation>(`/annotations/${annotationId}/submit`)).data,
  review: async (annotationId: string, decision: "approved" | "rejected", comment = "") =>
    (
      await api.post<Annotation>(`/annotations/${annotationId}/review`, {
        decision,
        comment,
      })
    ).data,
  reopen: async (annotationId: string) =>
    (await api.post<Annotation>(`/annotations/${annotationId}/reopen`)).data,
};

export const exportApi = {
  list: async (params?: { task_id?: string; status?: string }) =>
    (await api.get<ExportJob[]>("/exports", { params })).data,
  get: async (id: string) => (await api.get<ExportJob>(`/exports/${id}`)).data,
  create: async (payload: {
    name: string;
    task_id: string;
    dataset_ids: string[];
    format?: "nnunet";
    split_config: Record<string, unknown>;
    include_statuses: string[];
  }) => (await api.post<ExportJob>("/exports", payload)).data,
  manifest: async (id: string) =>
    (await api.get<Record<string, unknown>>(`/exports/${id}/manifest`)).data,
  download: async (id: string) =>
    (await api.get<Blob>(`/exports/${id}/download`, { responseType: "blob" })).data,
};

export const evaluationApi = {
  list: async (params?: { task_id?: string; status?: string }) =>
    (await api.get<EvaluationJob[]>("/evaluations", { params })).data,
  get: async (id: string) => (await api.get<EvaluationJob>(`/evaluations/${id}`)).data,
  create: async (payload: {
    name: string;
    taskId: string;
    datasetIds: string[];
    gtStatuses: string[];
    metricsConfig: Record<string, unknown>;
    file: File;
  }) => {
    const form = new FormData();
    form.append("name", payload.name);
    form.append("task_id", payload.taskId);
    form.append("dataset_ids", JSON.stringify(payload.datasetIds));
    form.append("gt_statuses", JSON.stringify(payload.gtStatuses));
    form.append("metrics_config", JSON.stringify(payload.metricsConfig));
    form.append("file", payload.file);
    return (await api.post<EvaluationJob>("/evaluations", form)).data;
  },
  report: async (id: string) =>
    (await api.get<Record<string, any>>(`/evaluations/${id}/report`)).data,
};

export const userApi = {
  list: async () => (await api.get<User[]>("/users")).data,
  create: async (payload: {
    username: string;
    password: string;
    display_name?: string;
    role: string;
  }) => (await api.post<User>("/users", payload)).data,
  update: async (id: string, payload: Partial<User>) =>
    (await api.patch<User>(`/users/${id}`, payload)).data,
  resetPassword: async (id: string, password: string) =>
    (await api.post<User>(`/users/${id}/reset-password`, { password })).data,
};

export const dashboardApi = {
  get: async () => (await api.get<Dashboard>("/dashboard")).data,
};

export const studioApi = {
  tasks: async () => (await api.get<StudioTaskSummary[]>("/studio/tasks")).data,
  readiness: async (code: string) =>
    (await api.get<StudioReadiness>(`/studio/tasks/${code}/readiness`)).data,
  taskExperiments: async (code: string, params?: Record<string, unknown>) =>
    (await api.get<StudioExperiment[]>(`/studio/tasks/${code}/experiments`, { params })).data,
  metrics: async (expId: string, repoKey: string, params?: Record<string, unknown>) =>
    (
      await api.get<MetricPoint[]>(`/studio/experiments/${expId}/metrics`, {
        params: { repo_key: repoKey, ...(params ?? {}) },
      })
    ).data,
  evaluations: async (expId: string, repoKey: string) =>
    (
      await api.get<ExternalEvaluation[]>(`/studio/experiments/${expId}/evaluations`, {
        params: { repo_key: repoKey },
      })
    ).data,
};

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
