import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { KeyOutlined, PlusOutlined, ReloadOutlined, EditOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { getErrorMessage, userApi } from "../api";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import StatusTag from "../components/StatusTag";

const { Title, Text } = Typography;

const ROLE_OPTIONS = [
  { value: "admin", label: "管理员" },
  { value: "annotator", label: "标注员" },
  { value: "reviewer", label: "审核员" },
];

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);
  const [saving, setSaving] = useState(false);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [resetForm] = Form.useForm();

  const load = () => {
    setLoading(true);
    userApi
      .list()
      .then(setUsers)
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const create = async () => {
    const values = await createForm.validateFields();
    setSaving(true);
    try {
      await userApi.create(values);
      message.success("用户已创建");
      setCreateOpen(false);
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const edit = async () => {
    if (!editing) return;
    const values = await editForm.validateFields();
    setSaving(true);
    try {
      await userApi.update(editing.id, values);
      message.success("用户已更新");
      setEditing(null);
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const resetPassword = async () => {
    if (!resetting) return;
    const values = await resetForm.validateFields();
    setSaving(true);
    try {
      await userApi.resetPassword(resetting.id, values.password);
      message.success("密码已重置");
      setResetting(null);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">用户管理</Title>
          <div className="mp-page-subtitle">
            管理员可维护账号与角色；标注员负责标注，审核员负责审核，管理员拥有全部权限。
          </div>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              createForm.resetFields();
              createForm.setFieldsValue({ role: "annotator" });
              setCreateOpen(true);
            }}
          >
            新建用户
          </Button>
        </Space>
      </div>

      <Card className="mp-card">
        <Table
          rowKey="id"
          loading={loading}
          dataSource={users}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: "用户名", dataIndex: "username", width: 180 },
            {
              title: "显示名称",
              dataIndex: "display_name",
              width: 180,
              render: (value: string) => value || "-",
            },
            {
              title: "角色",
              dataIndex: "role",
              width: 110,
              render: (value: string) => <StatusTag status={value} />,
            },
            {
              title: "状态",
              dataIndex: "is_active",
              width: 90,
              render: (value: boolean) =>
                value ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>,
            },
            {
              title: "创建时间",
              dataIndex: "created_at",
              width: 170,
              render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm"),
            },
            {
              title: "操作",
              width: 240,
              render: (_, record) => (
                <Space>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => {
                      setEditing(record);
                      editForm.setFieldsValue({
                        display_name: record.display_name,
                        role: record.role,
                        is_active: record.is_active,
                      });
                    }}
                  >
                    编辑
                  </Button>
                  <Button
                    size="small"
                    icon={<KeyOutlined />}
                    onClick={() => {
                      setResetting(record);
                      resetForm.resetFields();
                    }}
                  >
                    重置密码
                  </Button>
                  {record.id === currentUser?.id && <Text type="secondary">当前账号</Text>}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建用户"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={create}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, min: 2, message: "请输入至少 2 位用户名" }]}
          >
            <Input placeholder="登录用户名" />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            rules={[{ required: true, min: 6, message: "密码至少 6 位" }]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称">
            <Input placeholder="例如 张医生" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑用户：${editing?.username ?? ""}`}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={edit}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="display_name" label="显示名称">
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码：${resetting?.username ?? ""}`}
        open={resetting !== null}
        onCancel={() => setResetting(null)}
        onOk={resetPassword}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={resetForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="password"
            label="新密码"
            rules={[{ required: true, min: 6, message: "密码至少 6 位" }]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
