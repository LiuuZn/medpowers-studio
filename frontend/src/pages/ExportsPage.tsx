import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { EyeOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { exportApi, getErrorMessage, taskApi } from "../api";
import type { ExportJob, Task, TaskDatasetLink } from "../api/types";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

export default function ExportsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialTaskId = searchParams.get("taskId") ?? undefined;
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [links, setLinks] = useState<TaskDatasetLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();
  const selectedTaskId = Form.useWatch("task_id", form) as string | undefined;

  const load = () => {
    setLoading(true);
    Promise.all([exportApi.list(initialTaskId ? { task_id: initialTaskId } : undefined), taskApi.list()])
      .then(([jobList, taskList]) => {
        setJobs(jobList);
        setTasks(taskList);
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  useEffect(() => {
    if (!selectedTaskId) {
      setLinks([]);
      form.setFieldValue("dataset_ids", undefined);
      return;
    }
    taskApi
      .linkedDatasets(selectedTaskId)
      .then((data) => {
        setLinks(data);
        form.setFieldValue(
          "dataset_ids",
          data.map((item) => item.dataset.id),
        );
      })
      .catch((error) => message.error(getErrorMessage(error)));
  }, [selectedTaskId, form]);

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({
      task_id: initialTaskId,
      include_statuses: ["approved"],
      train: 0.7,
      val: 0.15,
      test: 0.15,
      seed: 42,
      patient_level: true,
    });
    setOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    if (!values.dataset_ids?.length) {
      message.error("请至少选择一个数据集");
      return;
    }
    const total = Number(values.train) + Number(values.val) + Number(values.test);
    if (Math.abs(total - 1) > 0.001) {
      message.error("train / val / test 比例之和必须为 1");
      return;
    }
    setCreating(true);
    try {
      const job = await exportApi.create({
        name: values.name,
        task_id: values.task_id,
        dataset_ids: values.dataset_ids,
        format: "nnunet",
        include_statuses: values.include_statuses,
        split_config: {
          train: Number(values.train),
          val: Number(values.val),
          test: Number(values.test),
          seed: Number(values.seed),
          patient_level: Boolean(values.patient_level),
        },
      });
      if (job.status === "succeeded") {
        message.success(`导出完成，共 ${job.summary.exported_cases ?? 0} 例`);
      } else {
        message.error(job.error || "导出失败");
      }
      setOpen(false);
      load();
      if (job.status === "succeeded") {
        navigate(`/exports/${job.id}`);
      }
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setCreating(false);
    }
  };

  const metric = (job: ExportJob) => {
    const count = job.summary?.exported_cases;
    return typeof count === "number" ? `${count} 例` : "-";
  };

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">训练导出</Title>
          <div className="mp-page-subtitle">
            将已审核标注按任务导出为 nnU-Net 风格训练数据；分割导出 imagesTr/labelsTr，
            关键帧与检测导出任务 JSON。
          </div>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建导出
          </Button>
        </Space>
      </div>

      <Card className="mp-card">
        <Table
          rowKey="id"
          loading={loading}
          dataSource={jobs}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          columns={[
            {
              title: "导出作业",
              dataIndex: "name",
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <a onClick={() => navigate(`/exports/${record.id}`)}>{value}</a>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {record.id.slice(0, 8)}
                  </Text>
                </Space>
              ),
            },
            { title: "任务", dataIndex: "task_name", width: 180 },
            {
              title: "格式",
              dataIndex: "format",
              width: 110,
              render: (value: string) => <Tag color="blue">{value}</Tag>,
            },
            {
              title: "纳入状态",
              dataIndex: "include_statuses",
              width: 180,
              render: (value: string[]) => (
                <Space size={[2, 2]} wrap>
                  {value.map((item) => (
                    <StatusTag key={item} status={item} />
                  ))}
                </Space>
              ),
            },
            { title: "病例数", width: 100, render: (_, record) => metric(record) },
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
            {
              title: "操作",
              width: 110,
              render: (_, record) => (
                <Button
                  size="small"
                  type="primary"
                  ghost
                  icon={<EyeOutlined />}
                  onClick={() => navigate(`/exports/${record.id}`)}
                >
                  详情
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建训练导出"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={submit}
        confirmLoading={creating}
        destroyOnHidden
        width={700}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="仅导出所选状态且已有提交版本标注的病例。默认只导出已通过审核的标注。"
        />
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="作业名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="例如 lung_nodule_seg3d_v1" />
          </Form.Item>
          <Form.Item name="task_id" label="任务" rules={[{ required: true, message: "请选择任务" }]}>
            <Select
              placeholder="选择任务"
              options={tasks.map((item) => ({
                value: item.id,
                label: `${item.name}（${item.dimension.toUpperCase()}）`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="dataset_ids"
            label="数据集"
            rules={[{ required: true, message: "请选择数据集" }]}
          >
            <Select
              mode="multiple"
              placeholder="选择该任务关联的数据集"
              options={links.map((item) => ({
                value: item.dataset.id,
                label: `${item.dataset.name}（${item.dataset.case_count} 例）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="include_statuses" label="纳入标注状态" rules={[{ required: true }]}>
            <Select
              mode="multiple"
              options={[
                { value: "approved", label: "已通过审核（推荐）" },
                { value: "submitted", label: "已提交待审核" },
                { value: "in_progress", label: "标注中（谨慎）" },
              ]}
            />
          </Form.Item>
          <Row gutter={12}>
            <Col span={6}>
              <Form.Item name="train" label="训练集比例">
                <InputNumber min={0} max={1} step={0.05} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="val" label="验证集比例">
                <InputNumber min={0} max={1} step={0.05} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="test" label="测试集比例">
                <InputNumber min={0} max={1} step={0.05} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="seed" label="随机种子">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="patient_level"
            label="按患者分组划分"
            valuePropName="checked"
            extra="开启后同一患者的病例只会进入一个集合，避免数据泄漏"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
