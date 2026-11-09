import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  BarChartOutlined,
  DatabaseOutlined,
  EditOutlined,
  ExperimentOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { dashboardApi, metaApi } from "../api";
import type { Dashboard, TaskTypeSpec } from "../api/types";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

export default function DashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<Dashboard | null>(null);
  const [taskTypes, setTaskTypes] = useState<TaskTypeSpec[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    Promise.all([dashboardApi.get(), metaApi.taskTypes()])
      .then(([dashboard, types]) => {
        setData(dashboard);
        setTaskTypes(types);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const typeName = (code: string) =>
    taskTypes.find((item) => item.code === code)?.name ?? code;

  const annotationTotal = data
    ? Object.values(data.annotations).reduce((sum, value) => sum + value, 0)
    : 0;
  const approved = data?.annotations.approved ?? 0;

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">概览</Title>
          <div className="mp-page-subtitle">
            数据集、任务与标注进度总览
          </div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          刷新
        </Button>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <Card className="mp-card mp-stat-card" onClick={() => navigate("/datasets")}>
            <Statistic
              title="数据集"
              value={data?.datasets ?? 0}
              prefix={<DatabaseOutlined style={{ color: "#1677ff" }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card className="mp-card mp-stat-card" onClick={() => navigate("/tasks")}>
            <Statistic
              title="任务"
              value={data?.tasks ?? 0}
              prefix={<ExperimentOutlined style={{ color: "#13c2c2" }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="序列总数"
              value={data?.cases ?? 0}
              prefix={<DatabaseOutlined style={{ color: "#722ed1" }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card className="mp-card mp-stat-card" onClick={() => navigate("/datasets")}>
            <Statistic
              title="已通过标注"
              value={approved}
              suffix={annotationTotal ? `/ ${annotationTotal}` : ""}
              prefix={<EditOutlined style={{ color: "#52c41a" }} />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={16}>
          <Card
            className="mp-card"
            title="任务标注进度"
            extra={
              <Button type="link" onClick={() => navigate("/tasks")}>
                查看全部任务
              </Button>
            }
          >
            <Table
              rowKey="task_id"
              size="middle"
              pagination={false}
              loading={loading}
              dataSource={data?.task_progress ?? []}
              locale={{ emptyText: <Empty description="暂无进行中的任务" /> }}
              columns={[
                {
                  title: "任务",
                  dataIndex: "task_name",
                  render: (value: string, record) => (
                    <Space direction="vertical" size={0}>
                      <a onClick={() => navigate(`/tasks/${record.task_id}`)}>{value}</a>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {typeName(record.task_type)}
                      </Text>
                    </Space>
                  ),
                },
                {
                  title: "序列",
                  dataIndex: "total_cases",
                  width: 80,
                },
                {
                  title: "通过进度",
                  width: 220,
                  render: (_, record) => {
                    const percent = record.total_cases
                      ? Math.round((record.approved / record.total_cases) * 100)
                      : 0;
                    return (
                      <div className="mp-progress-cell">
                        <Progress
                          percent={percent}
                          size="small"
                          status={percent === 100 ? "success" : "active"}
                        />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {record.approved} / {record.total_cases} 已通过
                        </Text>
                      </div>
                    );
                  },
                },
                {
                  title: "状态分布",
                  render: (_, record) => (
                    <Space size={[4, 4]} wrap>
                      <Tag>{`待标注 ${record.pending}`}</Tag>
                      <Tag color="processing">{`标注中 ${record.in_progress}`}</Tag>
                      <Tag color="warning">{`待审核 ${record.submitted}`}</Tag>
                      <Tag color="success">{`通过 ${record.approved}`}</Tag>
                      <Tag color="error">{`驳回 ${record.rejected}`}</Tag>
                    </Space>
                  ),
                },
                {
                  title: "",
                  width: 100,
                  render: (_, record) => (
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      disabled={!record.dataset_id}
                      onClick={() => {
                        if (record.dataset_id) {
                          navigate(
                            `/datasets/${record.dataset_id}?taskId=${record.task_id}`,
                          );
                        }
                      }}
                    >
                      进入标注
                    </Button>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card className="mp-card" title="标注状态分布">
            <Space direction="vertical" size={14} style={{ width: "100%" }}>
              {[
                ["pending", "待标注", "default"],
                ["in_progress", "标注中", "processing"],
                ["submitted", "待审核", "warning"],
                ["approved", "已通过", "success"],
                ["rejected", "已驳回", "error"],
              ].map(([key, label, color]) => {
                const value = data?.annotations[key as keyof typeof data.annotations] ?? 0;
                const percent = annotationTotal
                  ? Math.round((value / annotationTotal) * 100)
                  : 0;
                return (
                  <div key={key}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Text>
                        <StatusTag status={key} label={label as string} />
                      </Text>
                      <Text strong>{value}</Text>
                    </Space>
                    <Progress percent={percent} size="small" showInfo={false} />
                  </div>
                );
              })}
            </Space>
          </Card>
          <Card
            className="mp-card"
            title="最近作业"
            style={{ marginTop: 16 }}
            extra={<BarChartOutlined />}
          >
            <Space direction="vertical" size={10} style={{ width: "100%" }}>
              {(data?.recent_exports ?? []).slice(0, 3).map((job) => (
                <Space key={job.id} style={{ width: "100%", justifyContent: "space-between" }}>
                  <a onClick={() => navigate(`/exports/${job.id}`)}>{job.name}</a>
                  <StatusTag status={job.status} />
                </Space>
              ))}
              {(data?.recent_evaluations ?? []).slice(0, 3).map((job) => (
                <Space key={job.id} style={{ width: "100%", justifyContent: "space-between" }}>
                  <a onClick={() => navigate(`/evaluations/${job.id}`)}>{job.name}</a>
                  <StatusTag status={job.status} />
                </Space>
              ))}
              {!data?.recent_exports.length && !data?.recent_evaluations.length && (
                <Text type="secondary">暂无导出或评估作业</Text>
              )}
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={12}>
          <Card className="mp-card" title="最近导出">
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={data?.recent_exports ?? []}
              locale={{ emptyText: "暂无导出" }}
              columns={[
                {
                  title: "作业",
                  dataIndex: "name",
                  render: (value, record) => (
                    <a onClick={() => navigate(`/exports/${record.id}`)}>{value}</a>
                  ),
                },
                { title: "任务", dataIndex: "task_name" },
                {
                  title: "状态",
                  dataIndex: "status",
                  width: 90,
                  render: (value) => <StatusTag status={value} />,
                },
                {
                  title: "时间",
                  dataIndex: "created_at",
                  width: 150,
                  render: (value) => dayjs(value).format("MM-DD HH:mm"),
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card className="mp-card" title="最近评估">
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={data?.recent_evaluations ?? []}
              locale={{ emptyText: "暂无评估" }}
              columns={[
                {
                  title: "作业",
                  dataIndex: "name",
                  render: (value, record) => (
                    <a onClick={() => navigate(`/evaluations/${record.id}`)}>{value}</a>
                  ),
                },
                { title: "任务", dataIndex: "task_name" },
                {
                  title: "状态",
                  dataIndex: "status",
                  width: 90,
                  render: (value) => <StatusTag status={value} />,
                },
                {
                  title: "时间",
                  dataIndex: "created_at",
                  width: 150,
                  render: (value) => dayjs(value).format("MM-DD HH:mm"),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
