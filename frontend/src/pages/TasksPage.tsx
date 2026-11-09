import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { getErrorMessage, metaApi, taskApi } from "../api";
import type { LabelSchema, Task, TaskTypeSpec } from "../api/types";
import LabelSchemaEditor from "../components/LabelSchemaEditor";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

export default function TasksPage() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskTypes, setTaskTypes] = useState<TaskTypeSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedTaskType, setSelectedTaskType] = useState<TaskTypeSpec | undefined>();
  const [labelSchema, setLabelSchema] = useState<LabelSchema | undefined>();
  const [form] = Form.useForm();

  const load = () => {
    setLoading(true);
    Promise.all([taskApi.list(), metaApi.taskTypes()])
      .then(([taskList, types]) => {
        setTasks(taskList);
        setTaskTypes(types);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const openCreate = () => {
    form.resetFields();
    setSelectedTaskType(undefined);
    setLabelSchema(undefined);
    setOpen(true);
  };

  const onTaskTypeChange = (code: string) => {
    const spec = taskTypes.find((item) => item.code === code);
    setSelectedTaskType(spec);
    setLabelSchema(
      spec ? JSON.parse(JSON.stringify(spec.default_label_schema)) : undefined,
    );
  };

  const submit = async () => {
    const values = await form.validateFields();
    if (!selectedTaskType || !labelSchema) {
      message.error("请选择任务类型并配置标签体系");
      return;
    }
    const entries =
      selectedTaskType.annotation_kind === "mask"
        ? labelSchema.classes ?? []
        : labelSchema.labels ?? [];
    if (entries.length === 0) {
      message.error("至少配置一个类别/标签");
      return;
    }
    if (entries.some((item) => !item.name.trim())) {
      message.error("类别/标签名称不能为空");
      return;
    }
    setSaving(true);
    try {
      const task = await taskApi.create({
        ...values,
        label_schema: labelSchema,
      });
      message.success("任务已创建，请关联同维度数据集");
      setOpen(false);
      navigate(`/tasks/${task.id}`);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const typeName = (code: string) =>
    taskTypes.find((item) => item.code === code)?.name ?? code;

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">任务</Title>
          <div className="mp-page-subtitle">
            任务定义标注类型与标签体系；任务可关联多个同维度数据集，维度不匹配会被拒绝。
          </div>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建任务
          </Button>
        </Space>
      </div>

      <Card className="mp-card">
        <Table
          rowKey="id"
          loading={loading}
          dataSource={tasks}
          rowClassName="mp-clickable-row"
          onRow={(record) => ({
            onClick: () => navigate(`/tasks/${record.id}`),
          })}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          columns={[
            {
              title: "任务",
              dataIndex: "name",
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <a
                    onClick={(event) => {
                      event.stopPropagation();
                      navigate(`/tasks/${record.id}`);
                    }}
                  >
                    {value}
                  </a>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {record.code}
                  </Text>
                </Space>
              ),
            },
            {
              title: "任务类型",
              dataIndex: "task_type",
              width: 170,
              render: (value: string) => <Tag color="blue">{typeName(value)}</Tag>,
            },
            {
              title: "维度",
              dataIndex: "dimension",
              width: 80,
              render: (value: string) => <Tag>{value.toUpperCase()}</Tag>,
            },
            {
              title: "关联数据集",
              dataIndex: "dataset_count",
              width: 110,
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 100,
              render: (value: string) => <StatusTag status={value} />,
            },
            {
              title: "创建时间",
              dataIndex: "created_at",
              width: 160,
              render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm"),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建任务"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={submit}
        confirmLoading={saving}
        destroyOnHidden
        width={760}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="code"
                label="任务编码"
                rules={[{ required: true, message: "请输入编码" }]}
                extra="创建后不可修改"
              >
                <Input placeholder="例如 lung_nodule_seg3d" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="任务名称" rules={[{ required: true, message: "请输入名称" }]}>
                <Input placeholder="例如 肺结节三维分割" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="task_type"
            label="任务类型"
            rules={[{ required: true, message: "请选择任务类型" }]}
          >
            <Select
              placeholder="选择任务类型"
              onChange={onTaskTypeChange}
              options={taskTypes.map((item) => ({
                value: item.code,
                label: `${item.name}（${item.dimension.toUpperCase()}）`,
              }))}
            />
          </Form.Item>
          {selectedTaskType && (
            <div style={{ marginBottom: 16 }}>
              <Text type="secondary">{selectedTaskType.description}</Text>
            </div>
          )}
          <Form.Item label="标签体系" required>
            <LabelSchemaEditor
              taskType={selectedTaskType}
              value={labelSchema}
              onChange={setLabelSchema}
            />
          </Form.Item>
          <Form.Item name="description" label="任务说明">
            <Input.TextArea rows={2} placeholder="任务目标、数据范围等" />
          </Form.Item>
          <Form.Item name="annotation_guide" label="标注指南">
            <Input.TextArea rows={4} placeholder="判定规则、边界约定、允差等，供标注员参考" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
