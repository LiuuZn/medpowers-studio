import { useEffect, useMemo, useRef, useState } from "react";
import type { Key } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  Popconfirm,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  InboxOutlined,
  ReloadOutlined,
  UploadOutlined,
  UserOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { datasetApi, getErrorMessage } from "../api";
import type {
  DataKind,
  Dataset,
  DatasetHierarchyPage,
  DatasetTaskSummary,
  HierarchyItem,
  ImportJob,
  ImportReport,
  PatientNode,
  SeriesNode,
  StudyNode,
} from "../api/types";
import StatusTag from "../components/StatusTag";
import TablePreview from "../components/TablePreview";

const { Title, Text, Paragraph } = Typography;

type HierarchyLevel = "patient" | "study" | "series";

interface HierarchyRow {
  key: string;
  nodeType: "patient" | "study" | "series";
  title: string;
  subtitle: string;
  code?: string;
  sex?: string;
  age?: string;
  studyDate?: string;
  accession?: string;
  studyCount?: number;
  seriesCount?: number;
  seriesTotal?: number;
  statusCounts?: Record<string, number>;
  patientKey?: string | null;
  studyTitle?: string;
  studyUid?: string | null;
  caseId?: string;
  status?: string;
  annotatorName?: string | null;
  updatedAt?: string | null;
  imageFormat?: string;
  dataKind?: DataKind;
  shape?: string;
  version?: number;
  children?: HierarchyRow[];
}

function shapeText(series: SeriesNode): string {
  const geometry = series.geometry;
  if (geometry.array_shape?.length) {
    return geometry.array_shape.join(" × ");
  }
  if (geometry.width && geometry.height) {
    return `${geometry.height} × ${geometry.width}`;
  }
  return "-";
}

function countStatuses(series: SeriesNode[]): Record<string, number> {
  const result: Record<string, number> = {};
  for (const item of series) {
    result[item.annotation_status] = (result[item.annotation_status] || 0) + 1;
  }
  return result;
}

function seriesToRow(series: SeriesNode): HierarchyRow {
  return {
    key: `series-${series.case_id}`,
    nodeType: "series",
    title: series.series_description || series.case_uid,
    subtitle: "序列",
    code: series.series_uid || series.case_uid,
    caseId: series.case_id,
    patientKey: series.patient_key,
    studyTitle: series.study_description || series.study_uid || "",
    studyUid: series.study_uid,
    studyDate: series.study_date,
    status: series.annotation_status,
    annotatorName: series.annotator_name,
    updatedAt: series.updated_at,
    imageFormat: series.image_format,
    dataKind: series.data_kind,
    shape: shapeText(series),
    version: series.version,
  };
}

function studyToRow(study: StudyNode): HierarchyRow {
  return {
    key: `study-${study.study_id}`,
    nodeType: "study",
    title: study.description || "未命名检查",
    subtitle: "检查",
    code: study.study_uid,
    patientKey: study.patient_key,
    studyUid: study.study_uid,
    studyDate: study.study_date,
    accession: study.accession_number,
    seriesCount: study.series_count,
    seriesTotal: study.series_count,
    statusCounts: countStatuses(study.series),
    children: study.series.map(seriesToRow),
  };
}

function patientToRow(patient: PatientNode): HierarchyRow {
  return {
    key: `patient-${patient.patient_id}`,
    nodeType: "patient",
    title: patient.patient_key,
    subtitle: "患者",
    sex: patient.sex,
    age: patient.age,
    studyCount: patient.study_count,
    seriesCount: patient.series_count,
    seriesTotal: patient.series_count,
    statusCounts: countStatuses(patient.studies.flatMap((study) => study.series)),
    children: patient.studies.map(studyToRow),
  };
}

function hierarchyItemToRow(item: HierarchyItem): HierarchyRow {
  if (item.node_type === "patient") return patientToRow(item);
  if (item.node_type === "study") return studyToRow(item);
  return seriesToRow(item);
}

export default function DatasetDetailPage() {
  const { datasetId } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryTaskId = searchParams.get("taskId") || undefined;
  const rawLevel = searchParams.get("level");
  const level: HierarchyLevel =
    rawLevel === "patient" || rawLevel === "study" || rawLevel === "series"
      ? rawLevel
      : "series";

  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [tasks, setTasks] = useState<DatasetTaskSummary[]>([]);
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | undefined>();
  const [hierarchy, setHierarchy] = useState<DatasetHierarchyPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [hierarchyLoading, setHierarchyLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [expandedRowKeys, setExpandedRowKeys] = useState<Key[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeTab, setActiveTab] = useState("overview");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [importing, setImporting] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [importJob, setImportJob] = useState<ImportJob | null>(null);
  const pollTimer = useRef<number | null>(null);
  const [previewCase, setPreviewCase] = useState<{ id: string; title: string } | null>(null);
  const [pathForm] = Form.useForm();

  const updateQuery = (updates: Record<string, string | undefined>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value) {
        next.set(key, value);
      } else {
        next.delete(key);
      }
    }
    setSearchParams(next, { replace: true });
  };

  useEffect(() => {
    setPage(1);
    setSearch("");
    setReport(null);
    setAcknowledged(false);
    setImportJob(null);
    setPreviewCase(null);
    setTasksLoaded(false);
    setSelectedTaskId(undefined);
    setHierarchy(null);
    setActiveTab("overview");
  }, [datasetId]);

  useEffect(() => {
    if (!datasetId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([datasetApi.get(datasetId), datasetApi.tasks(datasetId)])
      .then(([datasetData, taskData]) => {
        if (cancelled) return;
        setDataset(datasetData);
        setTasks(taskData);
        setTasksLoaded(true);
        const preferred =
          queryTaskId && taskData.some((item) => item.task_id === queryTaskId)
            ? queryTaskId
            : taskData[0]?.task_id;
        setSelectedTaskId(preferred);
        if (preferred && preferred !== queryTaskId) {
          updateQuery({ taskId: preferred });
        }
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  useEffect(() => {
    if (!queryTaskId) return;
    if (tasks.some((item) => item.task_id === queryTaskId)) {
      setSelectedTaskId(queryTaskId);
    }
  }, [queryTaskId, tasks]);

  useEffect(() => {
    if (!datasetId || !tasksLoaded) return;
    let cancelled = false;
    setHierarchyLoading(true);
    datasetApi
      .hierarchy(datasetId, {
        task_id: selectedTaskId,
        search: search || undefined,
        level,
        page,
        page_size: pageSize,
      })
      .then((data) => {
        if (cancelled) return;
        setHierarchy(data);
        setExpandedRowKeys([]);
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => {
        if (!cancelled) setHierarchyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, selectedTaskId, search, level, page, pageSize, tasksLoaded, refreshKey]);

  const selectedTask = useMemo(
    () => tasks.find((item) => item.task_id === selectedTaskId),
    [tasks, selectedTaskId],
  );
  const labelItems = useMemo(
    () => selectedTask?.label_schema.classes ?? selectedTask?.label_schema.labels ?? [],
    [selectedTask],
  );
  const approvedPercent = selectedTask?.total_series
    ? Math.round((selectedTask.approved / selectedTask.total_series) * 100)
    : 0;

  const rows = useMemo<HierarchyRow[]>(() => {
    if (!hierarchy) return [];
    return hierarchy.items.map(hierarchyItemToRow);
  }, [hierarchy]);

  const openAnnotation = (record: HierarchyRow) => {
    if (!datasetId || !record.caseId) return;
    if (!selectedTaskId) {
      message.warning("请先选择标注任务");
      return;
    }
    navigate(`/datasets/${datasetId}/annotate/${selectedTaskId}/${record.caseId}`);
  };

  const contextColumns: TableColumnsType<HierarchyRow> =
    level === "patient"
      ? []
      : [
          {
            title: level === "series" ? "患者 / 检查" : "患者",
            width: level === "series" ? 220 : 160,
            render: (_, record) => (
              <Space direction="vertical" size={0}>
                <Text>{record.patientKey || "未归类"}</Text>
                {level === "series" && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {record.studyTitle || record.studyUid || "未归类检查"}
                  </Text>
                )}
              </Space>
            ),
          },
        ];

  const columns: TableColumnsType<HierarchyRow> = [
    {
      title: "患者 / 检查 / 序列",
      dataIndex: "title",
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Space size={6} wrap>
            <Tag
              color={
                record.nodeType === "patient"
                  ? "purple"
                  : record.nodeType === "study"
                    ? "blue"
                    : "cyan"
              }
            >
              {record.nodeType === "patient"
                ? "患者"
                : record.nodeType === "study"
                  ? "检查"
                  : "序列"}
            </Tag>
            <Text strong={record.nodeType !== "series"}>{record.title}</Text>
            {record.sex && <Tag>{record.sex}</Tag>}
            {record.age && <Tag>{record.age}</Tag>}
          </Space>
          <Text
            type="secondary"
            style={{ fontSize: 12 }}
            ellipsis={{ tooltip: record.code || record.subtitle }}
          >
            {record.code || record.subtitle}
          </Text>
        </Space>
      ),
    },
    ...contextColumns,
    {
      title: "结构",
      width: 190,
      render: (_, record) => {
        if (record.nodeType === "patient") {
          return `检查 ${record.studyCount ?? 0} · 序列 ${record.seriesCount ?? 0}`;
        }
        if (record.nodeType === "study") {
          return `序列 ${record.seriesCount ?? 0}`;
        }
        return `${(record.imageFormat || "").toUpperCase()} · ${record.shape || "-"}`;
      },
    },
    {
      title: "检查日期",
      width: 110,
      render: (_, record) =>
        record.nodeType === "patient" ? "-" : record.studyDate || "-",
    },
    {
      title: "标注进度",
      width: 200,
      render: (_, record) => {
        if (record.nodeType === "series") {
          return (
            <Space size={4}>
              <StatusTag status={record.status || "pending"} />
              <Text type="secondary">v{record.version ?? 0}</Text>
            </Space>
          );
        }
        const counts = record.statusCounts || {};
        const total = record.seriesTotal || 0;
        const approved = counts.approved || 0;
        const percent = total ? Math.round((approved / total) * 100) : 0;
        return (
          <div style={{ minWidth: 160 }}>
            <Progress
              percent={percent}
              size="small"
              showInfo={false}
              status={percent === 100 ? "success" : "active"}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              通过 {approved}/{total} · 标注中 {counts.in_progress || 0} · 待审{" "}
              {counts.submitted || 0} · 待标 {counts.pending || 0}
            </Text>
          </div>
        );
      },
    },
    {
      title: "标注员",
      width: 110,
      render: (_, record) =>
        record.nodeType === "series" ? record.annotatorName || "-" : "-",
    },
    {
      title: "更新时间",
      width: 150,
      render: (_, record) =>
        record.nodeType === "series" && record.updatedAt
          ? dayjs(record.updatedAt).format("YYYY-MM-DD HH:mm")
          : "-",
    },
    {
      title: "操作",
      width: 100,
      render: (_, record) => {
        if (record.nodeType !== "series") return null;
        if (record.dataKind === "table") {
          return (
            <Button
              size="small"
              onClick={(event) => {
                event.stopPropagation();
                if (record.caseId) {
                  setPreviewCase({ id: record.caseId, title: record.title });
                }
              }}
            >
              预览表格
            </Button>
          );
        }
        return (
          <Button
            size="small"
            type="primary"
            ghost
            disabled={!selectedTaskId}
            onClick={(event) => {
              event.stopPropagation();
              openAnnotation(record);
            }}
          >
            {record.status === "approved" || record.status === "submitted"
              ? "查看"
              : "标注"}
          </Button>
        );
      },
    },
  ];

  const refresh = () => {
    if (!datasetId) return;
    datasetApi
      .get(datasetId)
      .then(setDataset)
      .catch((error) => message.error(getErrorMessage(error)));
    datasetApi
      .tasks(datasetId)
      .then((taskData) => {
        setTasks(taskData);
        if (selectedTaskId && !taskData.some((item) => item.task_id === selectedTaskId)) {
          const next = taskData[0]?.task_id;
          setSelectedTaskId(next);
          if (next) updateQuery({ taskId: next });
        }
      })
      .catch((error) => message.error(getErrorMessage(error)));
    setRefreshKey((value) => value + 1);
  };

  const markReady = async () => {
    if (!datasetId) return;
    try {
      const updated = await datasetApi.markReady(datasetId);
      setDataset(updated);
      message.success("数据集已标记为就绪，可被同维度任务关联");
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const archive = async () => {
    if (!datasetId) return;
    try {
      const updated = await datasetApi.archive(datasetId);
      setDataset(updated);
      message.success("数据集已归档");
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const afterImport = async (result: ImportReport) => {
    setReport(result);
    if (result.imported) {
      message.success(`成功导入 ${result.imported} 个记录`);
    } else {
      message.warning("没有导入任何记录，请查看错误信息");
    }
    if (!datasetId) return;
    try {
      const [datasetData, taskData] = await Promise.all([
        datasetApi.get(datasetId),
        datasetApi.tasks(datasetId),
      ]);
      setDataset(datasetData);
      setTasks(taskData);
      if (selectedTaskId && !taskData.some((item) => item.task_id === selectedTaskId)) {
        setSelectedTaskId(taskData[0]?.task_id);
      }
      setRefreshKey((value) => value + 1);
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const importPath = async () => {
    if (!datasetId) return;
    if (!acknowledged) {
      message.warning("请先确认已自行备份原始数据");
      return;
    }
    const values = await pathForm.validateFields();
    setImporting(true);
    try {
      const result = await datasetApi.importPath(datasetId, {
        ...values,
        acknowledge_source_discarded: true,
      });
      await afterImport(result);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setImporting(false);
    }
  };

  const startImportJob = async () => {
    if (!datasetId) return;
    if (!acknowledged) {
      message.warning("请先确认已自行备份原始数据");
      return;
    }
    const values = await pathForm.validateFields();
    setImporting(true);
    try {
      const job = await datasetApi.createImportJob(datasetId, {
        ...values,
        acknowledge_source_discarded: true,
      });
      setImportJob(job);
      message.info("已提交后台导入任务，可关闭页面，稍后回来查看结果");
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setImporting(false);
    }
  };

  useEffect(() => {
    if (!datasetId || !importJob) return;
    if (importJob.status !== "queued" && importJob.status !== "running") return;
    pollTimer.current = window.setTimeout(() => {
      datasetApi
        .getImportJob(datasetId, importJob.id)
        .then((next) => {
          setImportJob(next);
          if (next.status === "succeeded") {
            void afterImport(next.report);
          } else if (next.status === "failed") {
            message.error(next.error || "后台导入失败");
          }
        })
        .catch((error) => message.error(getErrorMessage(error)));
    }, 2000);
    return () => {
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
    };
  }, [datasetId, importJob]);

  if (!dataset) {
    return (
      <div className="mp-page">
        <Card className="mp-card" loading={loading} />
      </div>
    );
  }

  const overview = (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="患者"
              value={hierarchy?.total_patients ?? dataset.patient_count}
              prefix={<UserOutlined style={{ color: "#722ed1" }} />}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="检查"
              value={hierarchy?.total_studies ?? dataset.study_count}
              prefix={<ExperimentOutlined style={{ color: "#13c2c2" }} />}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="序列"
              value={hierarchy?.total_series ?? dataset.case_count}
              prefix={<DatabaseOutlined style={{ color: "#1677ff" }} />}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="当前任务已通过"
              value={selectedTask?.approved ?? 0}
              suffix={`/ ${selectedTask?.total_series ?? hierarchy?.total_series ?? 0}`}
              prefix={<CheckCircleOutlined style={{ color: "#52c41a" }} />}
            />
          </Card>
        </Col>
      </Row>

      {hierarchy && hierarchy.unassigned_series > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`${hierarchy.unassigned_series} 个序列尚未建立患者/检查层级`}
          description="历史数据可运行 backend/scripts/backfill_hierarchy.py 完成补齐。"
        />
      )}

      {!tasks.length ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="数据集尚未关联任务"
          description="标注按任务定义标签体系。请先创建同维度任务并关联此数据集，之后即可在这里直接标注。"
          action={
            <Button size="small" onClick={() => navigate("/tasks")}>
              去任务页
            </Button>
          }
        />
      ) : (
        <Card className="mp-card" style={{ marginBottom: 16 }}>
          <Row gutter={[16, 16]} align="middle">
            <Col xs={24} lg={9}>
              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                <Text type="secondary">当前标注任务</Text>
                <Select
                  style={{ width: "100%" }}
                  value={selectedTaskId}
                  placeholder="选择任务"
                  onChange={(value) => {
                    setSelectedTaskId(value);
                    updateQuery({ taskId: value });
                    setPage(1);
                  }}
                  options={tasks.map((item) => ({
                    value: item.task_id,
                    label: `${item.name}（${item.task_type_name} · ${item.approved}/${item.total_series} 已通过）`,
                  }))}
                />
              </Space>
            </Col>
            <Col xs={24} lg={15}>
              {selectedTask && (
                <div>
                  <Space
                    style={{ width: "100%", justifyContent: "space-between" }}
                    wrap
                  >
                    <Text strong>标注完成度</Text>
                    <Text type="secondary">
                      {selectedTask.approved} / {selectedTask.total_series} 已通过 · 待审核{" "}
                      {selectedTask.submitted} · 标注中 {selectedTask.in_progress} · 待标注{" "}
                      {selectedTask.pending}
                    </Text>
                  </Space>
                  <Progress
                    percent={approvedPercent}
                    status={approvedPercent === 100 ? "success" : "active"}
                  />
                </div>
              )}
            </Col>
          </Row>
          {selectedTask && (
            <Space style={{ marginTop: 12 }} wrap>
              <Tag color="blue">{selectedTask.name}</Tag>
              <Tag>{selectedTask.dimension.toUpperCase()}</Tag>
              <StatusTag status={selectedTask.status} />
              {labelItems.map((item) => (
                <Tag key={item.id} color={item.color}>
                  {item.id}. {item.name}
                </Tag>
              ))}
            </Space>
          )}
        </Card>
      )}

      <Card className="mp-card">
        <Row gutter={[12, 12]} align="middle" style={{ marginBottom: 16 }}>
          <Col xs={24} lg={9}>
            <Segmented
              block
              value={level}
              onChange={(value) => {
                updateQuery({ level: String(value) });
                setPage(1);
                setExpandedRowKeys([]);
              }}
              options={[
                {
                  value: "patient",
                  label: `患者 ${hierarchy?.total_patients ?? dataset.patient_count}`,
                },
                {
                  value: "study",
                  label: `检查 ${hierarchy?.total_studies ?? dataset.study_count}`,
                },
                {
                  value: "series",
                  label: `序列 ${hierarchy?.total_series ?? dataset.case_count}`,
                },
              ]}
            />
          </Col>
          <Col xs={24} md={10}>
            <Input.Search
              allowClear
              placeholder="搜索患者标识、检查/序列 UID 或描述"
              onSearch={(value) => {
                setPage(1);
                setSearch(value);
              }}
            />
          </Col>
          <Col>
            <Button icon={<ReloadOutlined />} onClick={refresh}>
              刷新
            </Button>
          </Col>
        </Row>
        <Table
          rowKey="key"
          loading={hierarchyLoading}
          dataSource={rows}
          columns={columns}
          pagination={{
            current: page,
            pageSize,
            total: hierarchy?.total ?? 0,
            showSizeChanger: true,
            showTotal: (value) =>
              level === "patient"
                ? `共 ${value} 位患者`
                : level === "study"
                  ? `共 ${value} 个检查`
                  : `共 ${value} 个序列`,
            onChange: (nextPage, nextSize) => {
              setPage(nextPage);
              setPageSize(nextSize);
            },
          }}
          expandable={{
            expandedRowKeys,
            onExpandedRowsChange: (keys) => setExpandedRowKeys([...keys]),
          }}
          onRow={(record) => ({
            onClick: () => {
              if (record.nodeType === "series") openAnnotation(record);
            },
            style: record.nodeType === "series" ? { cursor: "pointer" } : undefined,
          })}
          locale={{
            emptyText: (
              <div className="mp-empty">
                <InboxOutlined style={{ fontSize: 36, color: "#b6c4d4" }} />
                <div style={{ marginTop: 10 }}>
                  {dataset.case_count
                    ? "没有符合条件的数据"
                    : "还没有序列，先导入影像数据"}
                </div>
                {!dataset.case_count && (
                  <Button
                    type="primary"
                    style={{ marginTop: 12 }}
                    onClick={() => setActiveTab("import")}
                  >
                    去导入
                  </Button>
                )}
              </div>
            ),
          }}
        />
      </Card>
    </div>
  );

  const importPanel = (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card className="mp-card" title="从服务器路径导入">
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="平台只保留规范化格式"
            description="3D 影像统一保存为 NRRD，2D 影像统一保存为 PNG，表格统一保存为 Parquet。原始 DICOM/NIfTI/图片/表格文件不会进入平台长期存储，请务必自行保留备份。"
          />
          <Paragraph type="secondary">
            {dataset.data_kind === "table"
              ? "支持 CSV / TSV / XLSX / Parquet / JSON；XLSX 的每个 sheet 会导入为一个记录。"
              : "支持 DICOM 序列目录、NRRD / NIfTI 文件，以及 2D PNG/JPG。导入时会转换并写入平台内容寻址存储。"}
            NRRD/DICOM 头中的 PatientID / StudyInstanceUID / SeriesInstanceUID 会自动建立
            patient / study / series 层级。
          </Paragraph>
          <Form form={pathForm} layout="vertical" initialValues={{ recursive: true }}>
            <Form.Item
              name="path"
              label="服务器路径"
              rules={[{ required: true, message: "请输入路径" }]}
            >
              <Input
                placeholder={
                  dataset.data_kind === "table" ? "/imports/tables/2026" : "/imports/ct/chest_2026"
                }
              />
            </Form.Item>
            <Form.Item name="recursive" label="递归扫描子目录" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item>
              <Checkbox
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              >
                我已自行备份原始数据，理解平台只保留规范化格式
              </Checkbox>
            </Form.Item>
            <Space wrap>
              <Button
                type="primary"
                icon={<UploadOutlined />}
                loading={importing}
                disabled={!acknowledged}
                onClick={importPath}
              >
                开始导入
              </Button>
              <Button
                icon={<CloudUploadOutlined />}
                loading={importing}
                disabled={!acknowledged}
                onClick={startImportJob}
              >
                后台导入（大目录）
              </Button>
            </Space>
            {importJob && (
              <Alert
                style={{ marginTop: 16 }}
                type={
                  importJob.status === "failed"
                    ? "error"
                    : importJob.status === "succeeded"
                      ? "success"
                      : "info"
                }
                showIcon
                message={`后台任务：${importJob.status}`}
                description={
                  importJob.status === "failed"
                    ? importJob.error
                    : importJob.status === "succeeded"
                      ? `导入 ${importJob.imported} 个，跳过 ${importJob.skipped} 个`
                      : "任务在后台执行，可关闭页面；完成后刷新数据集即可看到结果。"
                }
              />
            )}
          </Form>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card className="mp-card" title="上传 ZIP 压缩包">
          <Paragraph type="secondary">
            将 DICOM 序列、NRRD/NIfTI、2D 图片或表格打包为 ZIP 上传；平台会解压后自动识别。
          </Paragraph>
          <Upload.Dragger
            accept=".zip"
            multiple={false}
            showUploadList={false}
            disabled={!acknowledged}
            customRequest={async (options) => {
              if (!datasetId) return;
              if (!acknowledged) {
                message.warning("请先确认已自行备份原始数据");
                return;
              }
              const file = options.file as File;
              setImporting(true);
              try {
                const result = await datasetApi.importUpload(datasetId, file, true);
                await afterImport(result);
                options.onSuccess?.(result);
              } catch (error) {
                message.error(getErrorMessage(error));
                options.onError?.(error as Error);
              } finally {
                setImporting(false);
              }
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽 ZIP 到此处上传</p>
            <p className="ant-upload-hint">
              大文件上传可能需要较长时间；超大目录建议放到服务器的 imports 目录后走路径导入
            </p>
          </Upload.Dragger>
        </Card>
      </Col>
      <Col span={24}>
        {report && (
          <Card className="mp-card" title="最近一次导入结果">
            <Alert
              type={report.imported ? "success" : "warning"}
              showIcon
              message={`导入 ${report.imported} 个，跳过 ${report.skipped} 个，错误 ${report.errors.length} 条`}
              description={
                <span>
                  规范化 {report.converted} 个，写入{" "}
                  {(report.stored_bytes / 1024 / 1024).toFixed(1)} MB。原始文件未保留，请自行备份。
                </span>
              }
              icon={<CloudUploadOutlined />}
            />
            {report.errors.length > 0 && (
              <Table
                style={{ marginTop: 16 }}
                rowKey={(record) => `${record.source}-${record.message}`}
                size="small"
                pagination={{ pageSize: 8 }}
                dataSource={report.errors}
                columns={[
                  { title: "来源", dataIndex: "source", width: 260 },
                  { title: "错误", dataIndex: "message" },
                ]}
              />
            )}
          </Card>
        )}
      </Col>
    </Row>
  );

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            style={{ paddingLeft: 0 }}
            onClick={() => navigate("/datasets")}
          >
            返回数据集列表
          </Button>
          <Title className="mp-page-title" style={{ marginTop: 4 }}>
            {dataset.name}
          </Title>
          <Space style={{ marginTop: 8 }} wrap>
            <Text code>{dataset.code}</Text>
            <Tag color="geekblue">{dataset.modality}</Tag>
            <Tag>{dataset.dimension.toUpperCase()}</Tag>
            <Tag color={dataset.data_kind === "table" ? "gold" : "cyan"}>
              {dataset.data_kind === "table"
                ? "表格"
                : dataset.data_kind === "image2d"
                  ? "二维影像"
                  : "三维体数据"}
            </Tag>
            <StatusTag status={dataset.status} />
            <Tag>{dataset.scan_protocol.name}</Tag>
            <Tag>
              {dataset.patient_count} 患者 · {dataset.study_count} 检查 ·{" "}
              {dataset.case_count} 序列
            </Tag>
          </Space>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={refresh}>
            刷新
          </Button>
          {dataset.status === "draft" && (
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={markReady}
              disabled={dataset.case_count === 0}
            >
              标记为就绪
            </Button>
          )}
          {dataset.status !== "archived" && (
            <Popconfirm
              title="归档该数据集？"
              description="已关联任务的数据集不能归档。"
              onConfirm={archive}
            >
              <Button danger>归档</Button>
            </Popconfirm>
          )}
        </Space>
      </div>

      <Card className="mp-card" style={{ marginBottom: 16 }}>
        <Descriptions column={{ xs: 1, sm: 2, lg: 4 }} size="small">
          <Descriptions.Item label="模态">{dataset.modality}</Descriptions.Item>
          <Descriptions.Item label="维度">{dataset.dimension.toUpperCase()}</Descriptions.Item>
          <Descriptions.Item label="数据种类">
            {dataset.data_kind === "table"
              ? "临床表格（Parquet）"
              : dataset.data_kind === "image2d"
                ? "二维影像（PNG）"
                : "三维体数据（NRRD）"}
          </Descriptions.Item>
          <Descriptions.Item label="扫描流程">{dataset.scan_protocol.name}</Descriptions.Item>
          <Descriptions.Item label="层级">
            {dataset.patient_count} 患者 / {dataset.study_count} 检查 / {dataset.case_count} 序列
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {dayjs(dataset.created_at).format("YYYY-MM-DD HH:mm")}
          </Descriptions.Item>
          <Descriptions.Item label="创建来源">
            {dataset.created_by ? (
              <Space size={4} wrap>
                <span>{dataset.created_by.display_name || dataset.created_by.username}</span>
                {dataset.created_by_token_id && <Tag color="purple">API 令牌</Tag>}
                {dataset.created_by_repo_key && (
                  <Tag color="blue">{dataset.created_by_repo_key}</Tag>
                )}
              </Space>
            ) : (
              <Text type="secondary">未知</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="存储路径" span={3}>
            <Text code>{dataset.storage_path}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="说明" span={4}>
            {dataset.description || <Text type="secondary">未填写</Text>}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: "overview", label: "患者 / 检查 / 序列标注", children: overview },
          { key: "import", label: "导入数据", children: importPanel },
        ]}
      />

      <TablePreview
        caseId={previewCase?.id ?? null}
        title={previewCase?.title}
        open={Boolean(previewCase)}
        onClose={() => setPreviewCase(null)}
      />
    </div>
  );
}
