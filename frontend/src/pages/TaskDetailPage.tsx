import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  ExportOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { datasetApi, getErrorMessage, metaApi, taskApi } from "../api";
import type {
  Dataset,
  Task,
  TaskDatasetLink,
  TaskStats,
  TaskTypeSpec,
} from "../api/types";
import StatusTag from "../components/StatusTag";

const { Title, Text, Paragraph } = Typography;

export default function TaskDetailPage() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [links, setLinks] = useState<TaskDatasetLink[]>([]);
  const [stats, setStats] = useState<TaskStats | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [taskTypes, setTaskTypes] = useState<TaskTypeSpec[]>([]);
  const [open, setOpen] = useState(false);
  const [selectedDataset, setSelectedDataset] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);

  const load = () => {
    if (!taskId) return;
    setLoading(true);
    Promise.all([
      taskApi.get(taskId),
      taskApi.linkedDatasets(taskId),
      taskApi.stats(taskId),
      datasetApi.list({ status: "ready" }),
      metaApi.taskTypes(),
    ])
      .then(([taskData, linkData, statsData, datasetData, types]) => {
        setTask(taskData);
        setLinks(linkData);
        setStats(statsData);
        setDatasets(datasetData);
        setTaskTypes(types);
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [taskId]);

  if (!task) {
    return (
      <div className="mp-page">
        <Card className="mp-card" loading={loading} />
      </div>
    );
  }

  const typeSpec = taskTypes.find((item) => item.code === task.task_type);
  const labels = task.label_schema.classes ?? task.label_schema.labels ?? [];
  const linkedIds = new Set(links.map((item) => item.dataset.id));
  const availableDatasets = datasets.filter(
    (item) => item.dimension === task.dimension && !linkedIds.has(item.id),
  );
  const approvedPercent = stats?.total_cases
    ? Math.round((stats.approved / stats.total_cases) * 100)
    : 0;

  const linkDataset = async () => {
    if (!taskId || !selectedDataset) return;
    try {
      await taskApi.linkDataset(taskId, selectedDataset);
      message.success("数据集已关联");
      setOpen(false);
      setSelectedDataset(undefined);
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const unlink = async (datasetId: string) => {
    if (!taskId) return;
    try {
      await taskApi.unlinkDataset(taskId, datasetId);
      message.success("已解除关联");
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const archive = async () => {
    if (!taskId) return;
    try {
      const updated = await taskApi.update(taskId, { status: "archived" });
      setTask(updated);
      message.success("任务已归档");
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            style={{ paddingLeft: 0 }}
            onClick={() => navigate("/tasks")}
          >
            返回任务列表
          </Button>
          <Title className="mp-page-title" style={{ marginTop: 4 }}>
            {task.name}
          </Title>
          <Space style={{ marginTop: 8 }} wrap>
            <Text code>{task.code}</Text>
            <Tag color="blue">{typeSpec?.name ?? task.task_type}</Tag>
            <Tag>{task.dimension.toUpperCase()}</Tag>
            <StatusTag status={task.status} />
            <Tag>{links.length} 个数据集</Tag>
          </Space>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button
            icon={<ExportOutlined />}
            disabled={task.status === "archived"}
            onClick={() => navigate(`/exports?taskId=${task.id}`)}
          >
            创建导出
          </Button>
          {task.status !== "archived" && (
            <Popconfirm
              title="归档该任务？"
              description="归档后不能继续标注。"
              onConfirm={archive}
            >
              <Button danger>归档</Button>
            </Popconfirm>
          )}
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={4}>
          <Card className="mp-card mp-stat-card">
            <Statistic title="序列总数" value={stats?.total_cases ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={4}>
          <Card className="mp-card mp-stat-card">
            <Statistic title="待标注" value={stats?.pending ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={4}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="标注中"
              value={stats?.in_progress ?? 0}
              valueStyle={{ color: "#1677ff" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={4}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="待审核"
              value={stats?.submitted ?? 0}
              valueStyle={{ color: "#fa8c16" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={4}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="已通过"
              value={stats?.approved ?? 0}
              valueStyle={{ color: "#52c41a" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={4}>
          <Card className="mp-card mp-stat-card">
            <Statistic
              title="已驳回"
              value={stats?.rejected ?? 0}
              valueStyle={{ color: "#ff4d4f" }}
            />
          </Card>
        </Col>
      </Row>

      <Card className="mp-card" style={{ marginTop: 16 }}>
        <Row gutter={[24, 16]} align="middle">
          <Col flex="auto">
            <div style={{ marginBottom: 6 }}>
              <Text strong>标注完成度</Text>{" "}
              <Text type="secondary">
                {stats?.approved ?? 0} / {stats?.total_cases ?? 0} 条序列通过审核
              </Text>
            </div>
            <Progress percent={approvedPercent} status={approvedPercent === 100 ? "success" : "active"} />
          </Col>
          <Col>
            <Space wrap>
              {labels.map((item) => (
                <Tag key={item.id} color={item.color}>
                  {item.id}. {item.name}
                </Tag>
              ))}
            </Space>
          </Col>
        </Row>
      </Card>

      <Card className="mp-card" style={{ marginTop: 16 }} title="任务信息">
        <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} size="small">
          <Descriptions.Item label="任务类型">{typeSpec?.name ?? task.task_type}</Descriptions.Item>
          <Descriptions.Item label="维度">{task.dimension.toUpperCase()}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {dayjs(task.created_at).format("YYYY-MM-DD HH:mm")}
          </Descriptions.Item>
          <Descriptions.Item label="任务说明" span={3}>
            {task.description || <Text type="secondary">未填写</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="标注指南" span={3}>
            {task.annotation_guide ? (
              <Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
                {task.annotation_guide}
              </Paragraph>
            ) : (
              <Text type="secondary">未填写</Text>
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        className="mp-card"
        style={{ marginTop: 16 }}
        title="关联数据集"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={task.status === "archived" || availableDatasets.length === 0}
            onClick={() => setOpen(true)}
          >
            关联数据集
          </Button>
        }
      >
        <Table
          rowKey={(record) => record.id}
          loading={loading}
          dataSource={links}
          pagination={false}
          locale={{
            emptyText: (
              <Empty description="尚未关联数据集">
                <Button
                  type="primary"
                  icon={<LinkOutlined />}
                  disabled={availableDatasets.length === 0}
                  onClick={() => setOpen(true)}
                >
                  关联同维度数据集
                </Button>
              </Empty>
            ),
          }}
          columns={[
            {
              title: "数据集",
              render: (_, record) => (
                <Space direction="vertical" size={0}>
                  <a
                    onClick={() =>
                      navigate(`/datasets/${record.dataset.id}?taskId=${task.id}`)
                    }
                  >
                    {record.dataset.name}
                  </a>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {record.dataset.code}
                  </Text>
                </Space>
              ),
            },
            {
              title: "模态",
              width: 100,
              render: (_, record) => <Tag color="geekblue">{record.dataset.modality}</Tag>,
            },
            {
              title: "维度",
              width: 90,
              render: (_, record) => <Tag>{record.dataset.dimension.toUpperCase()}</Tag>,
            },
            {
              title: "序列数",
              width: 100,
              render: (_, record) => record.dataset.case_count,
            },
            {
              title: "关联时间",
              dataIndex: "created_at",
              width: 160,
              render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm"),
            },
            {
              title: "操作",
              width: 230,
              render: (_, record) => (
                <Space>
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    onClick={() =>
                      navigate(`/datasets/${record.dataset.id}?taskId=${task.id}`)
                    }
                  >
                    标注 / 查看
                  </Button>
                  <Popconfirm
                    title="解除该数据集关联？"
                    description="已有标注的数据集不能解除关联。"
                    onConfirm={() => unlink(record.dataset.id)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />}>
                      解除关联
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="关联数据集"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={linkDataset}
        okButtonProps={{ disabled: !selectedDataset }}
        destroyOnHidden
      >
        <div style={{ marginTop: 16 }}>
          <Select
            style={{ width: "100%" }}
            placeholder="选择同维度且已就绪的数据集"
            value={selectedDataset}
            onChange={setSelectedDataset}
            options={availableDatasets.map((item) => ({
              value: item.id,
              label: `${item.name}（${item.modality} · ${item.case_count} 例）`,
            }))}
          />
          {availableDatasets.length === 0 && (
            <Text type="secondary" style={{ display: "block", marginTop: 10 }}>
              没有可关联的数据集：需要先创建同维度数据集、导入病例并标记为就绪。
            </Text>
          )}
        </div>
      </Modal>
    </div>
  );
}
