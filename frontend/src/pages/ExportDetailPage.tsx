import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { downloadBlob, exportApi, getErrorMessage } from "../api";
import type { ExportJob } from "../api/types";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

export default function ExportDetailPage() {
  const { exportId } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<ExportJob | null>(null);
  const [manifest, setManifest] = useState<Record<string, any> | null>(null);
  const [manifestOpen, setManifestOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = () => {
    if (!exportId) return;
    setLoading(true);
    exportApi
      .get(exportId)
      .then(setJob)
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [exportId]);

  const download = async () => {
    if (!exportId) return;
    try {
      const blob = await exportApi.download(exportId);
      downloadBlob(blob, `${job?.name ?? "export"}.zip`);
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const showManifest = async () => {
    if (!exportId) return;
    try {
      const data = await exportApi.manifest(exportId);
      setManifest(data);
      setManifestOpen(true);
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  if (!job) {
    return (
      <div className="mp-page">
        <Card className="mp-card" loading={loading} />
      </div>
    );
  }

  const splitCounts = (job.summary?.split_counts ?? {}) as Record<string, number>;
  const classes = (job.summary?.classes ?? {}) as Record<string, string>;

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            style={{ paddingLeft: 0 }}
            onClick={() => navigate("/exports")}
          >
            返回导出列表
          </Button>
          <Title className="mp-page-title" style={{ marginTop: 4 }}>
            {job.name}
          </Title>
          <Space style={{ marginTop: 8 }} wrap>
            <StatusTag status={job.status} />
            <Tag color="blue">{job.format}</Tag>
            <Tag>{job.task_name}</Tag>
            <Text type="secondary">{dayjs(job.created_at).format("YYYY-MM-DD HH:mm")}</Text>
          </Space>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button icon={<FileTextOutlined />} onClick={showManifest} disabled={!job.manifest_path}>
            查看清单
          </Button>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={download}
            disabled={job.status !== "succeeded"}
          >
            下载 ZIP
          </Button>
        </Space>
      </div>

      {job.status === "failed" && (
        <Alert
          type="error"
          showIcon
          message="导出失败"
          description={job.error}
          style={{ marginBottom: 16 }}
        />
      )}

      <Card className="mp-card" style={{ marginBottom: 16 }}>
        <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} size="small">
          <Descriptions.Item label="任务">{job.task_name}</Descriptions.Item>
          <Descriptions.Item label="导出病例">
            {job.summary?.exported_cases ?? 0}
          </Descriptions.Item>
          <Descriptions.Item label="纳入状态">
            <Space size={[2, 2]} wrap>
              {job.include_statuses.map((item) => (
                <StatusTag key={item} status={item} />
              ))}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="输出目录" span={3}>
            <Text code>{job.output_dir || "-"}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="清单路径" span={3}>
            <Text code>{job.manifest_path || "-"}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="开始时间">
            {job.started_at ? dayjs(job.started_at).format("YYYY-MM-DD HH:mm:ss") : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="结束时间">
            {job.finished_at ? dayjs(job.finished_at).format("YYYY-MM-DD HH:mm:ss") : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="划分种子">
            {String(job.split_config?.seed ?? "-")}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card className="mp-card" title="数据集划分" style={{ marginBottom: 16 }}>
        <Table
          rowKey="split"
          size="small"
          pagination={false}
          dataSource={[
            { split: "train", label: "训练集", count: splitCounts.train ?? 0 },
            { split: "val", label: "验证集", count: splitCounts.val ?? 0 },
            { split: "test", label: "测试集", count: splitCounts.test ?? 0 },
          ]}
          columns={[
            { title: "集合", dataIndex: "label", width: 140 },
            { title: "病例数", dataIndex: "count", width: 120 },
            {
              title: "比例配置",
              render: (_, record) => (
                <Text type="secondary">
                  {String(job.split_config?.[record.split] ?? "-")}
                </Text>
              ),
            },
          ]}
        />
        <div style={{ marginTop: 12 }}>
          <Text type="secondary">
            患者级划分：{job.split_config?.patient_level ? "是" : "否"} · 种子：
            {String(job.split_config?.seed ?? "-")}
          </Text>
        </div>
      </Card>

      <Card className="mp-card" title="标签体系">
        <Space wrap>
          {Object.entries(classes).map(([id, name]) => (
            <Tag key={id} color="blue">
              {id}. {name}
            </Tag>
          ))}
          {!Object.keys(classes).length && <Text type="secondary">无</Text>}
        </Space>
      </Card>

      <Card className="mp-card" title="导出摘要" style={{ marginTop: 16 }}>
        <pre className="mp-json">{JSON.stringify(job.summary, null, 2)}</pre>
      </Card>

      <Modal
        title="导出清单 manifest.json"
        open={manifestOpen}
        onCancel={() => setManifestOpen(false)}
        footer={null}
        width={900}
      >
        <pre className="mp-json">{JSON.stringify(manifest, null, 2)}</pre>
      </Modal>
    </div>
  );
}
