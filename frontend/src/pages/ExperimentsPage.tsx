import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Card,
  Col,
  Empty,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { getErrorMessage, studioApi } from "../api";
import type {
  ExternalEvaluation,
  MetricPoint,
  StudioExperiment,
  StudioReadiness,
  StudioTaskSummary,
} from "../api/types";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

function Sparkline({ points }: { points: MetricPoint[] }) {
  const ordered = useMemo(
    () => [...points].sort((a, b) => a.step - b.step),
    [points],
  );
  if (ordered.length === 0) return <Empty description="暂无可绘制的指标点" />;
  const values = ordered.map((item) => item.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 640;
  const height = 180;
  const pad = 16;
  const step = ordered.length > 1 ? (width - pad * 2) / (ordered.length - 1) : 0;
  const coords = ordered.map((item, index) => {
    const x = pad + index * step;
    const y = height - pad - ((item.value - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: 180 }}>
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#d9e2ec" />
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#d9e2ec" />
        <polyline
          fill="none"
          stroke="#1677ff"
          strokeWidth={2}
          points={coords.join(" ")}
        />
        {coords.length <= 80 &&
          coords.map((point, index) => {
            const [x, y] = point.split(",");
            return <circle key={index} cx={x} cy={y} r={2.5} fill="#1677ff" />;
          })}
      </svg>
      <Space size="large">
        <Text type="secondary">step {ordered[0].step} → {ordered[ordered.length - 1].step}</Text>
        <Text type="secondary">min {min.toFixed(6)} / max {max.toFixed(6)}</Text>
        <Text strong>latest {values[values.length - 1].toFixed(6)}</Text>
      </Space>
    </div>
  );
}

export default function ExperimentsPage() {
  const [tasks, setTasks] = useState<StudioTaskSummary[]>([]);
  const [taskCode, setTaskCode] = useState<string>();
  const [readiness, setReadiness] = useState<StudioReadiness | null>(null);
  const [experiments, setExperiments] = useState<StudioExperiment[]>([]);
  const [experiment, setExperiment] = useState<StudioExperiment | null>(null);
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [evaluations, setEvaluations] = useState<ExternalEvaluation[]>([]);
  const [metricName, setMetricName] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const loadTasks = async () => {
    try {
      const result = await studioApi.tasks();
      setTasks(result);
      if (!taskCode && result.length) setTaskCode(result[0].code);
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  useEffect(() => {
    loadTasks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!taskCode) return;
    setLoading(true);
    Promise.all([studioApi.readiness(taskCode), studioApi.taskExperiments(taskCode)])
      .then(([ready, list]) => {
        setReadiness(ready);
        setExperiments(list);
        const first = list[0] ?? null;
        setExperiment(first);
        if (!first) {
          setMetrics([]);
          setEvaluations([]);
        }
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  }, [taskCode, refreshNonce]);

  useEffect(() => {
    if (!experiment) return;
    setLoading(true);
    Promise.all([
      studioApi.metrics(experiment.exp_id, experiment.repo_key),
      studioApi.evaluations(experiment.exp_id, experiment.repo_key),
    ])
      .then(([points, evalList]) => {
        setMetrics(points);
        setEvaluations(evalList);
        const names = Array.from(new Set(points.map((item) => item.name))).sort();
        setMetricName((current) => (current && names.includes(current) ? current : names[0]));
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  }, [experiment, refreshNonce]);

  const metricNames = useMemo(
    () => Array.from(new Set(metrics.map((item) => item.name))).sort(),
    [metrics],
  );
  const currentPoints = useMemo(
    () => metrics.filter((item) => item.name === metricName),
    [metrics, metricName],
  );

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">实验与指标</Title>
          <div className="mp-page-subtitle">
            训练仓库经 medpowers 插件推送的只读镜像；git 中的 EXP 记录是权威。
          </div>
        </div>
        <Tag icon={<ReloadOutlined />} onClick={() => setRefreshNonce((value) => value + 1)}>
          刷新
        </Tag>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Space size="large" wrap>
          <span>
            <Text type="secondary">任务 / 模型：</Text>
            <Select
              style={{ minWidth: 240 }}
              value={taskCode}
              loading={loading}
              onChange={setTaskCode}
              options={tasks.map((task) => ({
                value: task.code,
                label: `${task.code} · ${task.task_type}`,
              }))}
              placeholder="选择任务"
            />
          </span>
          {tasks.length === 0 && <Text type="secondary">还没有任务；训练仓库推送实验前需先创建任务。</Text>}
        </Space>
      </Card>

      {readiness && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card>
                <Statistic title="总病例" value={readiness.total_cases} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="approved 金标准" value={readiness.counts.approved ?? 0} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="待复核"
                  value={readiness.counts.review_requested ?? 0}
                  valueStyle={{ color: "#d48806" }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="标注契约"
                  value={readiness.annotation_contract_complete ? "完整" : "未完整"}
                  valueStyle={{ color: readiness.annotation_contract_complete ? "#389e0d" : "#cf1322" }}
                />
              </Card>
            </Col>
          </Row>
          {readiness.qc_issues.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="数据/标注 QC 提示"
              description={readiness.qc_issues
                .map((issue) => `${issue.message}：${issue.count}`)
                .join("；")}
            />
          )}
        </>
      )}

      <Row gutter={16}>
        <Col span={9}>
          <Card title="实验镜像" size="small">
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={experiments}
              pagination={false}
              locale={{ emptyText: "还没有实验镜像（训练进程推送后出现）" }}
              rowClassName={(record) =>
                record.id === experiment?.id ? "mp-row-active" : ""
              }
              onRow={(record) => ({ onClick: () => setExperiment(record) })}
              columns={[
                { title: "实验", dataIndex: "exp_id", width: 100 },
                {
                  title: "状态",
                  dataIndex: "status",
                  width: 100,
                  render: (value: string) => <StatusTag status={value} />,
                },
                {
                  title: "标题/机器",
                  render: (_, record) => (
                    <Space direction="vertical" size={0}>
                      <Text>{record.title || "—"}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {record.machine || "—"} · {record.repo_key}
                      </Text>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
        <Col span={15}>
          <Card
            title={experiment ? `${experiment.exp_id} 指标` : "指标"}
            size="small"
            extra={
              metricNames.length > 0 && (
                <Select
                  style={{ minWidth: 220 }}
                  value={metricName}
                  onChange={setMetricName}
                  options={metricNames.map((name) => ({ value: name, label: name }))}
                />
              )
            }
          >
            {currentPoints.length > 0 ? (
              <>
                <Sparkline points={currentPoints} />
                <Table
                  rowKey={(row) => `${row.name}-${row.split}-${row.class}-${row.step}`}
                  size="small"
                  style={{ marginTop: 12 }}
                  dataSource={[...currentPoints].sort((a, b) => b.step - a.step).slice(0, 10)}
                  pagination={false}
                  columns={[
                    { title: "step", dataIndex: "step", width: 80 },
                    { title: "epoch", dataIndex: "epoch", width: 80 },
                    { title: "split", dataIndex: "split", width: 80 },
                    { title: "class", dataIndex: "class", width: 80 },
                    {
                      title: "value",
                      dataIndex: "value",
                      render: (value: number) => <Text code>{value}</Text>,
                    },
                  ]}
                />
              </>
            ) : (
              <Empty description={experiment ? "该实验还没有指标" : "选择左侧实验查看指标"} />
            )}
          </Card>
        </Col>
      </Row>

      <Card title="评测结果" size="small" style={{ marginTop: 16 }}>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={evaluations}
          pagination={false}
          locale={{ emptyText: "还没有评测结果" }}
          columns={[
            { title: "eval_id", dataIndex: "eval_id", width: 180 },
            {
              title: "来源",
              dataIndex: "source",
              width: 100,
              render: (value: string) => (
                <Tag color={value === "studio" ? "green" : "blue"}>
                  {value === "studio" ? "Studio" : "外部推送"}
                </Tag>
              ),
            },
            { title: "数据版本", dataIndex: "dataset_version", width: 160 },
            {
              title: "汇总",
              dataIndex: "summary",
              render: (value: Record<string, unknown>) => (
                <Text code style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(value)}
                </Text>
              ),
            },
            {
              title: "时间",
              dataIndex: "created_at",
              width: 170,
              render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm"),
            },
          ]}
        />
      </Card>
    </div>
  );
}
