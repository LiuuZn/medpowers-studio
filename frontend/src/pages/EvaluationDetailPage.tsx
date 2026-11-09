import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { ArrowLeftOutlined, DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { downloadBlob, evaluationApi, getErrorMessage } from "../api";
import type { EvaluationJob } from "../api/types";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

export default function EvaluationDetailPage() {
  const { evaluationId } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<EvaluationJob | null>(null);
  const [report, setReport] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    if (!evaluationId) return;
    setLoading(true);
    evaluationApi
      .get(evaluationId)
      .then(async (jobData) => {
        setJob(jobData);
        if (jobData.status === "succeeded") {
          const reportData = await evaluationApi.report(evaluationId);
          setReport(reportData);
        }
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [evaluationId]);

  const labelNames = useMemo(() => {
    const schema =
      report?.task?.label_schema?.classes ?? report?.task?.label_schema?.labels ?? [];
    const map: Record<string, string> = {};
    (schema as { id: number; name: string }[]).forEach((item) => {
      map[String(item.id)] = item.name;
    });
    return map;
  }, [report]);

  if (!job) {
    return (
      <div className="mp-page">
        <Card className="mp-card" loading={loading} />
      </div>
    );
  }

  const aggregate = report?.aggregate ?? {};
  const classes = aggregate.classes ?? {};
  const classKeys = Object.keys(classes);
  const isSeg = classKeys.some((key) => classes[key]?.dice);
  const overall = aggregate.overall;
  const perCase = (report?.per_case ?? []) as Record<string, any>[];

  const downloadReport = () => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    downloadBlob(blob, `evaluation_${job.id}.json`);
  };

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            style={{ paddingLeft: 0 }}
            onClick={() => navigate("/evaluations")}
          >
            返回评估列表
          </Button>
          <Title className="mp-page-title" style={{ marginTop: 4 }}>
            {job.name}
          </Title>
          <Space style={{ marginTop: 8 }} wrap>
            <StatusTag status={job.status} />
            <Tag color="blue">{job.task_name}</Tag>
            <Text type="secondary">{dayjs(job.created_at).format("YYYY-MM-DD HH:mm")}</Text>
          </Space>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            disabled={!report}
            onClick={downloadReport}
          >
            下载报告 JSON
          </Button>
        </Space>
      </div>

      {job.status === "failed" && (
        <Alert
          type="error"
          showIcon
          message="评估失败"
          description={job.error}
          style={{ marginBottom: 16 }}
        />
      )}

      <Card className="mp-card" style={{ marginBottom: 16 }}>
        <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} size="small">
          <Descriptions.Item label="任务">{job.task_name}</Descriptions.Item>
          <Descriptions.Item label="金标准状态">
            <Space size={[2, 2]} wrap>
              {job.gt_statuses.map((item) => (
                <StatusTag key={item} status={item} />
              ))}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="报告路径">
            <Text code>{job.report_path || "-"}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="指标配置" span={3}>
            <Text code>{JSON.stringify(job.metrics_config)}</Text>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {report && isSeg && (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={8}>
              <Card className="mp-card mp-stat-card">
                <Statistic
                  title="平均 Dice"
                  value={aggregate.mean_dice ?? 0}
                  precision={4}
                />
              </Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card className="mp-card mp-stat-card">
                <Statistic title="评估病例数" value={aggregate.case_count ?? 0} />
              </Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card className="mp-card mp-stat-card">
                <Statistic title="类别数" value={classKeys.length} />
              </Card>
            </Col>
          </Row>

          <Card className="mp-card" title="分割指标（按类别）" style={{ marginBottom: 16 }}>
            <Table
              rowKey="label_id"
              size="small"
              pagination={false}
              dataSource={classKeys.map((key) => ({ label_id: key, ...classes[key] }))}
              columns={[
                {
                  title: "类别",
                  dataIndex: "label_id",
                  width: 160,
                  render: (value: string) => `${value}. ${labelNames[value] ?? ""}`,
                },
                {
                  title: "Dice",
                  dataIndex: ["dice", "mean"],
                  width: 120,
                  render: (value: number | null) => (value === null ? "-" : value.toFixed(4)),
                },
                {
                  title: "IoU",
                  dataIndex: ["iou", "mean"],
                  width: 120,
                  render: (value: number | null) => (value === null ? "-" : value.toFixed(4)),
                },
                {
                  title: "Precision",
                  dataIndex: ["precision", "mean"],
                  width: 120,
                  render: (value: number | null) => (value === null ? "-" : value.toFixed(4)),
                },
                {
                  title: "Recall",
                  dataIndex: ["recall", "mean"],
                  width: 120,
                  render: (value: number | null) => (value === null ? "-" : value.toFixed(4)),
                },
                {
                  title: "HD95 (mm)",
                  dataIndex: ["hd95", "mean"],
                  width: 130,
                  render: (value: number | null) => (value === null ? "-" : value.toFixed(2)),
                },
                {
                  title: "样本数",
                  dataIndex: ["dice", "count"],
                  width: 90,
                },
              ]}
            />
          </Card>
        </>
      )}

      {report && !isSeg && (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={8}>
              <Card className="mp-card mp-stat-card">
                <Statistic
                  title="总体 Precision"
                  value={overall?.precision ?? 0}
                  precision={4}
                />
              </Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card className="mp-card mp-stat-card">
                <Statistic title="总体 Recall" value={overall?.recall ?? 0} precision={4} />
              </Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card className="mp-card mp-stat-card">
                <Statistic title="总体 F1" value={overall?.f1 ?? 0} precision={4} />
              </Card>
            </Col>
          </Row>

          <Card className="mp-card" title="指标（按类别）" style={{ marginBottom: 16 }}>
            <Table
              rowKey="label_id"
              size="small"
              pagination={false}
              dataSource={classKeys.map((key) => ({ label_id: key, ...classes[key] }))}
              columns={[
                {
                  title: "类别",
                  dataIndex: "label_id",
                  width: 160,
                  render: (value: string) => `${value}. ${labelNames[value] ?? ""}`,
                },
                { title: "TP", dataIndex: "tp", width: 80 },
                { title: "FP", dataIndex: "fp", width: 80 },
                { title: "FN", dataIndex: "fn", width: 80 },
                {
                  title: "Precision",
                  dataIndex: "precision",
                  width: 110,
                  render: (value: number) => value.toFixed(4),
                },
                {
                  title: "Recall",
                  dataIndex: "recall",
                  width: 110,
                  render: (value: number) => value.toFixed(4),
                },
                {
                  title: "F1",
                  dataIndex: "f1",
                  width: 110,
                  render: (value: number) => value.toFixed(4),
                },
                {
                  title: "Mean IoU",
                  dataIndex: "mean_iou",
                  width: 110,
                  render: (value: number | null) => (value === null ? "-" : value.toFixed(4)),
                },
              ]}
            />
            <div style={{ marginTop: 12 }}>
              <Space split="·">
                <Text type="secondary">容差：{aggregate.tolerance ?? "-"} 层</Text>
                <Text type="secondary">IoU 阈值：{aggregate.iou_threshold ?? "-"}</Text>
                <Text type="secondary">
                  平均绝对误差：{aggregate.mean_abs_error ?? "-"}
                </Text>
              </Space>
            </div>
          </Card>
        </>
      )}

      {report && (
        <Card className="mp-card" title="逐例结果" style={{ marginBottom: 16 }}>
          <Table
            rowKey="case_uid"
            size="small"
            dataSource={perCase}
            pagination={{ pageSize: 20, showSizeChanger: true }}
            columns={[
              { title: "病例 UID", dataIndex: "case_uid", width: 260 },
              {
                title: "状态",
                width: 100,
                render: (_, record) =>
                  record.error ? <Tag color="error">失败</Tag> : <Tag color="success">完成</Tag>,
              },
              {
                title: "结果",
                render: (_, record) => (
                  <Text type="secondary" ellipsis>
                    {record.error
                      ? record.error
                      : JSON.stringify(
                          record.classes ?? {
                            tp: record.tp,
                            fp: record.fp,
                            fn: record.fn,
                            mean_iou: record.mean_iou,
                            mean_abs_error: record.mean_abs_error,
                          },
                        )}
                  </Text>
                ),
              },
            ]}
          />
        </Card>
      )}

      {report && (
        <Card className="mp-card" title="原始报告">
          <pre className="mp-json">{JSON.stringify(report, null, 2)}</pre>
        </Card>
      )}
    </div>
  );
}
