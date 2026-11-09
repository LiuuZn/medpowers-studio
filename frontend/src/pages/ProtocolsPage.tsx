import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { getErrorMessage, metaApi, protocolApi } from "../api";
import type { ModalitySpec, ScanProtocol } from "../api/types";

const { Title, Text } = Typography;

export default function ProtocolsPage() {
  const [items, setItems] = useState<ScanProtocol[]>([]);
  const [modalities, setModalities] = useState<ModalitySpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ScanProtocol | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = () => {
    setLoading(true);
    Promise.all([protocolApi.list(true), metaApi.modalities()])
      .then(([protocols, modalityList]) => {
        setItems(protocols);
        setModalities(modalityList);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ modality_scope: [], sort_order: 0, is_active: true });
    setOpen(true);
  };

  const openEdit = (item: ScanProtocol) => {
    setEditing(item);
    form.setFieldsValue({
      code: item.code,
      name: item.name,
      description: item.description,
      modality_scope: item.modality_scope,
      sort_order: item.sort_order,
      is_active: item.is_active,
    });
    setOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await protocolApi.update(editing.id, values);
        message.success("扫描流程已更新");
      } else {
        await protocolApi.create(values);
        message.success("扫描流程已创建");
      }
      setOpen(false);
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (item: ScanProtocol) => {
    try {
      await protocolApi.remove(item.id);
      message.success("已删除");
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">扫描流程</Title>
          <div className="mp-page-subtitle">
            后台维护扫描流程字典；数据集创建时单选一个流程。预置标准流程（头部 CT
            扫描、腹部 MR 扫描等）随系统初始化自动创建，可编辑与停用；停用后历史数据集仍保留引用，
            被数据集引用的流程不可删除。
          </div>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建扫描流程
          </Button>
        </Space>
      </div>

      <Card className="mp-card">
        <Table
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          columns={[
            {
              title: "编码",
              dataIndex: "code",
              width: 180,
              render: (value) => <Text code>{value}</Text>,
            },
            { title: "名称", dataIndex: "name", width: 220 },
            {
              title: "适用模态",
              dataIndex: "modality_scope",
              render: (value: string[]) =>
                value.length ? (
                  <Space size={[4, 4]} wrap>
                    {value.map((item) => (
                      <Tag key={item} color="blue">
                        {item}
                      </Tag>
                    ))}
                  </Space>
                ) : (
                  <Tag>全部模态</Tag>
                ),
            },
            { title: "说明", dataIndex: "description", ellipsis: true },
            { title: "排序", dataIndex: "sort_order", width: 80 },
            {
              title: "状态",
              dataIndex: "is_active",
              width: 90,
              render: (value: boolean) =>
                value ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>,
            },
            {
              title: "操作",
              width: 150,
              render: (_, record) => (
                <Space>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => openEdit(record)}
                  >
                    编辑
                  </Button>
                  <Popconfirm
                    title="确认删除该扫描流程？"
                    description="已被数据集使用的流程无法删除，请改为停用。"
                    onConfirm={() => remove(record)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editing ? "编辑扫描流程" : "新建扫描流程"}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={submit}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="code"
            label="编码"
            rules={[{ required: true, message: "请输入编码" }]}
            extra="编码创建后不可修改，建议使用英文/数字/下划线"
          >
            <Input disabled={!!editing} placeholder="例如 CT_CHEST_ROUTINE" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="例如 胸部 CT 平扫" />
          </Form.Item>
          <Form.Item
            name="modality_scope"
            label="适用模态"
            extra="不选择表示适用于全部模态"
          >
            <Select
              mode="multiple"
              placeholder="选择适用的模态"
              options={modalities.map((item) => ({
                value: item.code,
                label: `${item.name}（${item.code}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={3} placeholder="扫描流程说明、适用场景等" />
          </Form.Item>
          <Space size={24}>
            <Form.Item name="sort_order" label="排序">
              <InputNumber min={0} />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  );
}
