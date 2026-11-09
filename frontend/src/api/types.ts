export type Role = "admin" | "annotator" | "reviewer";

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface UserBrief {
  id: string;
  username: string;
  display_name: string;
  role: Role;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export type ApiTokenStatus = "active" | "expired" | "revoked";
export type ApiTokenSource = "manual" | "device";

export interface ApiToken {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  source: ApiTokenSource;
  repo_key: string;
  client_name: string;
  status: ApiTokenStatus;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiTokenCreated {
  token: string;
  info: ApiToken;
}

export interface ScopeSpec {
  code: string;
  name: string;
  description: string;
}

export interface DeviceCodeResponse {
  device_code: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete: string;
  expires_in: number;
  interval: number;
}

export interface DeviceAuthorizationInfo {
  client_name: string;
  repo_key: string;
  scopes: string[];
  status: "pending" | "approved" | "denied" | "expired" | "consumed";
  expires_at: string;
}

export interface DeviceTokenResponse {
  access_token: string;
  token_type: string;
  scope: string;
  expires_at: string;
  user: User;
}

export type Dimension = "2d" | "3d" | "tabular";
export type DataKind = "volume3d" | "image2d" | "table";

export interface ModalitySpec {
  code: string;
  name: string;
  dimension: Dimension;
  data_kind: DataKind;
  description: string;
}

export interface TaskTypeSpec {
  code: string;
  name: string;
  dimension: "2d" | "3d";
  annotation_kind: "mask" | "keyframe" | "boxes";
  description: string;
  default_label_schema: LabelSchema;
}

export interface LabelClass {
  id: number;
  name: string;
  color: string;
}

export interface LabelSchema {
  classes?: LabelClass[];
  labels?: LabelClass[];
}

export interface ScanProtocol {
  id: string;
  code: string;
  name: string;
  description: string;
  modality_scope: string[];
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Dataset {
  id: string;
  code: string;
  name: string;
  description: string;
  modality: string;
  dimension: Dimension;
  data_kind: DataKind;
  scan_protocol_id: string;
  scan_protocol: { id: string; code: string; name: string };
  status: string;
  case_count: number;
  patient_count: number;
  study_count: number;
  storage_path: string;
  created_by: UserBrief | null;
  created_by_token_id: string | null;
  created_by_repo_key: string;
  created_at: string;
  updated_at: string;
}

export interface DatasetBrief {
  id: string;
  code: string;
  name: string;
  modality: string;
  dimension: Dimension;
  data_kind: DataKind;
  status: string;
  case_count: number;
}

export interface CaseItem {
  id: string;
  dataset_id: string;
  study_id: string | null;
  case_uid: string;
  series_uid: string | null;
  series_number: number | null;
  series_description: string;
  patient_key: string | null;
  image_format: string;
  data_kind: DataKind;
  size_bytes: number;
  sha256: string | null;
  geometry: {
    width?: number;
    height?: number;
    size?: number[];
    spacing?: number[];
    array_shape?: number[];
    origin?: number[];
    direction?: number[];
  };
  source_kind: string;
  source_path: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface CasePage {
  total: number;
  items: CaseItem[];
}

export interface ImportReport {
  imported: number;
  skipped: number;
  converted: number;
  stored_bytes: number;
  errors: { source: string; message: string }[];
  cases: string[];
  warnings: string[];
}

export interface ImportJob {
  id: string;
  dataset_id: string;
  source_type: string;
  source_path: string;
  recursive: boolean;
  status: "queued" | "running" | "succeeded" | "failed";
  imported: number;
  skipped: number;
  converted: number;
  stored_bytes: number;
  report: ImportReport;
  error: string | null;
  created_by_id: string | null;
  created_by_token_id: string | null;
  created_by_repo_key: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface SliceInfo {
  case_id: string;
  case_uid: string;
  dimension: "2d" | "3d";
  width: number;
  height: number;
  slices: number;
  spacing: number[] | null;
  origin: number[] | null;
  direction: number[] | null;
  default_window: number | null;
  default_level: number | null;
  axes: string[];
}

export interface TableColumn {
  name: string;
  type: string;
}

export interface TableInfo {
  row_count: number;
  column_count: number;
  columns: TableColumn[];
}

export interface TablePage extends TableInfo {
  total: number;
  offset: number;
  limit: number;
  rows: (string | number | boolean | null)[][];
}

export interface Task {
  id: string;
  code: string;
  name: string;
  description: string;
  task_type: string;
  dimension: "2d" | "3d";
  label_schema: LabelSchema;
  annotation_guide: string;
  status: string;
  dataset_count: number;
  created_at: string;
  updated_at: string;
}

export interface TaskDatasetLink {
  id: string;
  created_at: string;
  dataset: DatasetBrief;
}

export interface TaskStats {
  task_id: string;
  total_cases: number;
  pending: number;
  in_progress: number;
  submitted: number;
  approved: number;
  rejected: number;
  review_requested: number;
}

export interface Annotation {
  id: string | null;
  task_id: string;
  case_id: string;
  status: string;
  data: Record<string, unknown>;
  version: number;
  mask_available: boolean;
  annotator: UserBrief | null;
  reviewer: UserBrief | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  review_comment: string;
  updated_at: string | null;
}

export interface AnnotationCase {
  case_id: string;
  case_uid: string;
  patient_key: string | null;
  dataset_id: string;
  dataset_name: string;
  status: string;
  annotation_id: string | null;
  version: number;
  annotator_name: string | null;
  updated_at: string | null;
}

export interface AnnotationCasePage {
  total: number;
  items: AnnotationCase[];
}

export interface KeyFrame {
  label_id: number;
  z_index: number;
}

export interface DetBox {
  label_id: number;
  center_voxel: number[];
  size_voxel: number[];
  center_world?: number[];
  size_world?: number[];
}

export interface ExportJob {
  id: string;
  name: string;
  task_id: string;
  task_name: string;
  dataset_ids: string[];
  format: string;
  split_config: Record<string, unknown>;
  include_statuses: string[];
  status: string;
  output_dir: string;
  manifest_path: string | null;
  summary: Record<string, any>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EvaluationJob {
  id: string;
  name: string;
  task_id: string;
  task_name: string;
  dataset_ids: string[];
  gt_statuses: string[];
  metrics_config: Record<string, unknown>;
  status: string;
  report_path: string | null;
  summary: Record<string, any>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AnnotationCounts {
  pending: number;
  in_progress: number;
  submitted: number;
  approved: number;
  rejected: number;
  review_requested: number;
}

export interface TaskProgress extends AnnotationCounts {
  task_id: string;
  task_name: string;
  task_type: string;
  dataset_id: string | null;
  total_cases: number;
}

export interface DatasetTaskSummary {
  task_id: string;
  code: string;
  name: string;
  task_type: string;
  task_type_name: string;
  annotation_kind: "mask" | "keyframe" | "boxes";
  dimension: "2d" | "3d";
  status: string;
  label_schema: LabelSchema;
  total_series: number;
  pending: number;
  in_progress: number;
  submitted: number;
  approved: number;
  rejected: number;
  review_requested: number;
}

export interface SeriesNode {
  node_type: "series";
  case_id: string;
  case_uid: string;
  series_uid: string | null;
  series_number: number | null;
  series_description: string;
  image_format: string;
  data_kind: DataKind;
  geometry: {
    width?: number;
    height?: number;
    size?: number[];
    spacing?: number[];
    array_shape?: number[];
    origin?: number[];
    direction?: number[];
  };
  source_kind: string;
  annotation_id: string | null;
  annotation_status: string;
  version: number;
  annotator_name: string | null;
  updated_at: string | null;
  patient_id: string | null;
  patient_key: string | null;
  sex: string;
  age: string;
  study_id: string | null;
  study_uid: string | null;
  study_description: string;
  study_date: string;
  accession_number: string;
}

export interface StudyNode {
  node_type: "study";
  study_id: string;
  study_uid: string;
  description: string;
  study_date: string;
  accession_number: string;
  series_count: number;
  series: SeriesNode[];
  patient_id: string | null;
  patient_key: string | null;
  sex: string;
  age: string;
}

export interface PatientNode {
  node_type: "patient";
  patient_id: string;
  patient_key: string;
  sex: string;
  age: string;
  study_count: number;
  series_count: number;
  studies: StudyNode[];
}

export type HierarchyItem = PatientNode | StudyNode | SeriesNode;

export interface DatasetHierarchyPage {
  level: "patient" | "study" | "series";
  total_patients: number;
  matched_patients: number;
  total_studies: number;
  matched_studies: number;
  total_series: number;
  matched_series: number;
  unassigned_series: number;
  total: number;
  items: HierarchyItem[];
}

export interface Dashboard {
  datasets: number;
  tasks: number;
  cases: number;
  annotations: AnnotationCounts;
  task_progress: TaskProgress[];
  recent_exports: ExportJob[];
  recent_evaluations: EvaluationJob[];
}

export interface StudioTaskSummary {
  id: string;
  code: string;
  name: string;
  task_type: string;
  dimension: string;
  status: string;
  dataset_count: number;
  total_cases: number;
  approved: number;
  review_requested: number;
  annotation_contract_complete: boolean;
}

export interface StudioReadiness {
  task: StudioTaskSummary;
  datasets: DatasetBrief[];
  counts: Record<string, number>;
  total_cases: number;
  class_case_counts: Record<string, number>;
  qc_issues: Array<{ code: string; message: string; count: number }>;
  annotation_contract: Record<string, unknown>;
  annotation_contract_complete: boolean;
  last_updated: string | null;
}

export interface StudioExperiment {
  id: string;
  repo_key: string;
  exp_id: string;
  task_id: string;
  task_code: string;
  status: string;
  title: string;
  machine: string;
  git_commit: string;
  config: Record<string, unknown>;
  notes: string;
  record_path: string;
  record_sha256: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MetricPoint {
  name: string;
  value: number;
  step: number;
  epoch: number | null;
  split: string;
  class: string;
  timestamp: string;
  tags: Record<string, unknown>;
  source: string;
  extra: Record<string, unknown>;
}

export interface ExternalEvaluation {
  id: string;
  experiment_id: string;
  eval_id: string;
  source: string;
  task_code: string;
  gt_statuses: string[];
  dataset_version: string;
  summary: Record<string, unknown>;
  per_case: Array<Record<string, unknown>>;
  report_sha256: string;
  created_at: string;
}
