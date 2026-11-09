import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DatabaseOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { datasetApi, getErrorMessage, metaApi, protocolApi } from "../api";
import type { Dataset, ModalitySpec, ScanProtocol } from "../api/types";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

export default function DatasetsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Dataset[]>([]);
  const [protocols, setProtocols] = useState<ScanProtocol[]>([]);
  const [modalities, setModalities] = useState<ModalitySpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [modalityFilter, setModalityFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [form] = Form.useForm();
  const selectedModality = Form.useWatch("modality", form) as string | undefined;

  const load = () => {
    setLoading(true);
    Promise.all([
      datasetApi.list({
        search: search || undefined,
        modality: modalityFilter,
        status: statusFilter,
      }),
      protocolApi.list(false),
      metaApi.modalities(),
    ])
      .then(([datasets, protocolList, modalityList]) => {
        setItems(datasets);
        setProtocols(protocolList);
        setModalities(modalityList);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, [search, modalityFilter, statusFilter]);

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({ modality: "CT" });
    setOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const dataset = await datasetApi.create(values);
      message.success("数据集已创建，下一步导入病例");
      setOpen(false);
      navigate(`/datasets/${dataset.id}`);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const archive = async (dataset: Dataset) => {
    try {
      await datasetApi.archive(dataset.id);
      message.success("数据集已归档");
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const modalitySpec = modalities.find((item) => item.code === selectedModality);
  const compatibleProtocols = protocols.filter(
    (item) =>
      !item.modality_scope.length ||
      (selectedModality ? item.modality_scope.includes(selectedModality) : false),
  );

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">数据集</Title>
          <div className="mp-page-subtitle">
            按模态组织病例影像，每个数据集绑定一个扫描流程；就绪后可被同维度任务关联。
          </div>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建数据集
          </Button>
        </Space>
      </div>

      <Card className="mp-card">
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          <Col xs={24} md={10}>
            <Input.Search
              allowClear
              placeholder="搜索数据集名称或编码"
              onSearch={setSearch}
              enterButton
            />
          </Col>
          <Col xs={12} md={5}>
            <Select
              allowClear
              style={{ width: "100%" }}
              placeholder="模态"
              value={modalityFilter}
              onChange={setModalityFilter}
              options={modalities.map((item) => ({
                value: item.code,
                label: item.name,
              }))}
            />
          </Col>
          <Col xs={12} md={5}>
            <Select
              allowClear
              style={{ width: "100%" }}
              placeholder="状态"
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "draft", label: "草稿" },
                { value: "ready", label: "就绪" },
                { value: "archived", label: "已归档" },
              ]}
            />
          </Col>
        </Row>

        <Table
          rowKey="id"
          loading={loading}
          dataSource={items}
          rowClassName="mp-clickable-row"
          onRow={(record) => ({
            onClick: () => navigate(`/datasets/${record.id}`),
          })}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          locale={{
            emptyText: (
              <div className="mp-empty">
                <InboxOutlined style={{ fontSize: 36, color: "#b6c4d4" }} />
                <div style={{ marginTop: 10 }}>还没有数据集，先创建一个并导入病例</div>
                <Button type="primary" style={{ marginTop: 12 }} onClick={openCreate}>
                  新建数据集
                </Button>
              </div>
            ),
          }}
          columns={[
            {
              title: "数据集",
              dataIndex: "name",
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <a
                    onClick={(event) => {
                      event.stopPropagation();
                      navigate(`/datasets/${record.id}`);
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
              title: "模态 / 维度",
              dataIndex: "modality",
              width: 150,
              render: (value: string, record) => (
                <Space>
                  <Tag color={value === "CT" ? "geekblue" : value === "MR" ? "purple" : "cyan"}>
                    {value}
                  </Tag>
                  <Tag>{record.dimension.toUpperCase()}</Tag>
                </Space>
              ),
            },
            {
              title: "扫描流程",
              dataIndex: ["scan_protocol", "name"],
              width: 200,
            },
            {
              title: "患者 / 序列",
              dataIndex: "case_count",
              width: 120,
              render: (_: number, record) => (
                <Space>
                  <DatabaseOutlined style={{ color: "#1677ff" }} />
                  {record.patient_count} / {record.case_count}
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
              width: 100,
              render: (_, record) =>
                record.status !== "archived" ? (
                  <span onClick={(event) => event.stopPropagation()}>
                    <Popconfirm
                      title="归档该数据集？"
                      description="已关联任务的数据集不能归档。"
                      onConfirm={() => archive(record)}
                    >
                      <Button size="small" danger>
                        归档
                      </Button>
                    </Popconfirm>
                  </span>
                ) : null,
            },
          ]}
        />
      </Card>

      <Modal
        title="新建数据集"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={submit}
        confirmLoading={saving}
        destroyOnHidden
        width={620}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="code"
                label="数据集编码"
                rules={[{ required: true, message: "请输入编码" }]}
                extra="创建后不可修改"
              >
                <Input placeholder="例如 ct_chest_2026" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="name"
                label="数据集名称"
                rules={[{ required: true, message: "请输入名称" }]}
              >
                <Input placeholder="例如 胸部 CT 平扫数据集" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="modality"
                label="模态"
                rules={[{ required: true, message: "请选择模态" }]}
              >
                <Select
                  options={modalities.map((item) => ({
                    value: item.code,
                    label: `${item.name}（${item.dimension.toUpperCase()}）`,
                  }))}
                  onChange={() => form.setFieldValue("scan_protocol_id", undefined)}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="维度（由模态自动推导）">
                <Input
                  disabled
                  value={modalitySpec ? modalitySpec.dimension.toUpperCase() : ""}
                  placeholder="选择模态后显示"
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="scan_protocol_id"
            label="扫描流程"
            rules={[{ required: true, message: "请选择扫描流程" }]}
            extra="每个数据集只能选择一个扫描流程；优先使用预置标准流程，不适用时管理员可在基础配置 → 扫描流程中自定义新增"
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择扫描流程（可输入名称或编码搜索）"
              options={compatibleProtocols.map((item) => ({
                value: item.id,
                label: `${item.name}（${item.code}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={3} placeholder="数据来源、用途、纳入排除标准等" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
