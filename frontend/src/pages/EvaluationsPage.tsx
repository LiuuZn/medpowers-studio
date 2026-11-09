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
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadFile } from "antd";
import { InboxOutlined, PlusOutlined, ReloadOutlined, EyeOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { evaluationApi, getErrorMessage, taskApi } from "../api";
import type { EvaluationJob, Task, TaskDatasetLink } from "../api/types";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

export default function EvaluationsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialTaskId = searchParams.get("taskId") ?? undefined;
  const [jobs, setJobs] = useState<EvaluationJob[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [links, setLinks] = useState<TaskDatasetLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [form] = Form.useForm();
  const selectedTaskId = Form.useWatch("task_id", form) as string | undefined;

  const load = () => {
    setLoading(true);
    Promise.all([
      evaluationApi.list(initialTaskId ? { task_id: initialTaskId } : undefined),
      taskApi.list(),
    ])
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
      gt_statuses: ["approved"],
      iou_threshold: 0.5,
      keyframe_tolerance: 1,
    });
    setFileList([]);
    setOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    if (!fileList.length || !fileList[0].originFileObj) {
      message.error("请上传预测结果 ZIP 包");
      return;
    }
    setCreating(true);
    try {
      const job = await evaluationApi.create({
        name: values.name,
        taskId: values.task_id,
        datasetIds: values.dataset_ids,
        gtStatuses: values.gt_statuses,
        metricsConfig: {
          iou_threshold: Number(values.iou_threshold),
          keyframe_tolerance: Number(values.keyframe_tolerance),
        },
        file: fileList[0].originFileObj as File,
      });
      if (job.status === "succeeded") {
        message.success("评估完成");
        navigate(`/evaluations/${job.id}`);
      } else {
        message.error(job.error || "评估失败");
      }
      setOpen(false);
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setCreating(false);
    }
  };

  const metric = (job: EvaluationJob) => {
    if (typeof job.summary?.mean_dice === "number") {
      return `Dice ${job.summary.mean_dice.toFixed(4)}`;
    }
    if (typeof job.summary?.overall?.f1 === "number") {
      return `F1 ${job.summary.overall.f1.toFixed(4)}`;
    }
    return "-";
  };

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">评估</Title>
          <div className="mp-page-subtitle">
            上传模型预测结果，与已审核标注比对，输出逐例与汇总指标。
          </div>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建评估
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
              title: "评估作业",
              dataIndex: "name",
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <a onClick={() => navigate(`/evaluations/${record.id}`)}>{value}</a>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {record.id.slice(0, 8)}
                  </Text>
                </Space>
              ),
            },
            { title: "任务", dataIndex: "task_name", width: 180 },
            {
              title: "关键指标",
              width: 150,
              render: (_, record) => <Text strong>{metric(record)}</Text>,
            },
            {
              title: "金标准状态",
              dataIndex: "gt_statuses",
              width: 180,
              render: (value: string[]) => (
                <Space size={[2, 2]} wrap>
                  {value.map((item) => (
                    <StatusTag key={item} status={item} />
                  ))}
                </Space>
              ),
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
            {
              title: "操作",
              width: 110,
              render: (_, record) => (
                <Button
                  size="small"
                  type="primary"
                  ghost
                  icon={<EyeOutlined />}
                  onClick={() => navigate(`/evaluations/${record.id}`)}
                >
                  详情
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建评估"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={submit}
        confirmLoading={creating}
        destroyOnHidden
        width={720}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="预测结果请打包为 ZIP。分割任务使用 <case_uid>.nrrd（3D）或 .png（2D）；关键帧与检测任务使用 predictions.json，按 case_uid 组织。表格数据暂不参与评估。"
        />
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="作业名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="例如 lung_nodule_v1_eval" />
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
          <Form.Item name="gt_statuses" label="金标准状态" rules={[{ required: true }]}>
            <Select
              mode="multiple"
              options={[
                { value: "approved", label: "已通过审核（推荐）" },
                { value: "submitted", label: "已提交待审核" },
              ]}
            />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="iou_threshold"
                label="检测 IoU 阈值"
                extra="仅三维检测任务使用"
              >
                <InputNumber min={0} max={1} step={0.05} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="keyframe_tolerance"
                label="关键帧容差（层）"
                extra="仅关键帧任务使用"
              >
                <InputNumber min={0} step={1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="预测结果 ZIP" required>
            <Upload.Dragger
              accept=".zip"
              maxCount={1}
              fileList={fileList}
              beforeUpload={() => false}
              onChange={({ fileList: next }) => setFileList(next.slice(-1))}
              onRemove={() => {
                setFileList([]);
                return true;
              }}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽预测 ZIP 到此处</p>
              <p className="ant-upload-hint">上传后会立即执行评估</p>
            </Upload.Dragger>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
