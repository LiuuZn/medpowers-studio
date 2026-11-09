import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  CopyOutlined,
  KeyOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { Link } from "react-router-dom";
import { authApi, getErrorMessage } from "../api";
import type { ApiToken, ApiTokenCreated, ScopeSpec } from "../api/types";

const { Title, Text, Paragraph } = Typography;

const STATUS_META: Record<ApiToken["status"], { color: string; label: string }> = {
  active: { color: "green", label: "有效" },
  expired: { color: "default", label: "已过期" },
  revoked: { color: "red", label: "已撤销" },
};

const EXPIRY_OPTIONS = [
  { value: 30, label: "30 天" },
  { value: 90, label: "90 天" },
  { value: 180, label: "180 天" },
  { value: 365, label: "365 天" },
];

function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard
      .writeText(text)
      .then(() => message.success("已复制"))
      .catch(() => message.error("复制失败，请手动选择复制"));
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
  message.success("已复制");
}

export default function AccessTokensPage() {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [scopes, setScopes] = useState<ScopeSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);
  const [form] = Form.useForm<{
    name: string;
    repo_key: string;
    scopes: string[];
    expires_in_days: number;
  }>();

  const baseUrl = window.location.origin;

  const load = () => {
    setLoading(true);
    Promise.all([authApi.tokens(), authApi.scopes()])
      .then(([tokenList, scopeList]) => {
        setTokens(tokenList);
        setScopes(scopeList);
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({ repo_key: "", scopes: ["studio:read"], expires_in_days: 90 });
    setCreateOpen(true);
  };

  const create = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const result = await authApi.createToken(values);
      setCreateOpen(false);
      setCreated(result);
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const revoke = async (token: ApiToken) => {
    try {
      await authApi.revokeToken(token.id);
      message.success("令牌已撤销");
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const remove = async (token: ApiToken) => {
    try {
      await authApi.deleteToken(token.id);
      message.success("令牌记录已删除");
      load();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const scopeLabel = (code: string) =>
    scopes.find((item) => item.code === code)?.name ?? code;

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">访问令牌</Title>
          <div className="mp-page-subtitle">
            训练代码仓库和 medpowers 插件使用 API 访问令牌读取数据集、导出训练数据。
            令牌按权限范围（scope）受限，可随时撤销。
          </div>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建令牌
          </Button>
        </Space>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Text strong>
            <LinkOutlined /> 连接信息
          </Text>
          <Input
            readOnly
            value={baseUrl}
            addonAfter={
              <Button
                type="link"
                size="small"
                icon={<CopyOutlined />}
                onClick={() => copyText(baseUrl)}
              >
                复制
              </Button>
            }
          />
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            插件侧建议读取环境变量 <Text code>MEDPOWERS_STUDIO_URL</Text> 与{" "}
            <Text code>MEDPOWERS_STUDIO_TOKEN</Text>；请求头使用{" "}
            <Text code>Authorization: Bearer &lt;token&gt;</Text>。完整接口契约见{" "}
            <Text code>docs/api-access.md</Text>。
          </Paragraph>
        </Space>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="插件设备码授权"
        description={
          <span>
            工具安装后一般会显示一个形如 <Text code>ABCD-EFGH</Text> 的设备码。登录本平台后前往{" "}
            <Link to="/device">设备授权页</Link> 输入并批准，即可自动把令牌交给插件，无需手动复制。
          </span>
        }
      />

      <Card>
        <Table<ApiToken>
          rowKey="id"
          loading={loading}
          dataSource={tokens}
          pagination={false}
          size="middle"
          locale={{ emptyText: "还没有访问令牌" }}
          columns={[
            {
              title: "名称",
              dataIndex: "name",
              render: (_, token) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{token.name}</Text>
                  <Text type="secondary" style={{ fontFamily: "monospace" }}>
                    {token.prefix}…
                  </Text>
                </Space>
              ),
            },
            {
              title: "仓库",
              dataIndex: "repo_key",
              width: 140,
              render: (value: string) => value || "—",
            },
            {
              title: "权限",
              dataIndex: "scopes",
              render: (value: string[]) => (
                <Space size={[4, 4]} wrap>
                  {value.map((code) => (
                    <Tag key={code}>{scopeLabel(code)}</Tag>
                  ))}
                </Space>
              ),
            },
            {
              title: "来源",
              dataIndex: "source",
              width: 160,
              render: (value: string, token) =>
                value === "device" ? `设备授权 · ${token.client_name || "-"}` : "网页创建",
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 90,
              render: (value: ApiToken["status"]) => (
                <Tag color={STATUS_META[value].color}>{STATUS_META[value].label}</Tag>
              ),
            },
            {
              title: "到期时间",
              dataIndex: "expires_at",
              width: 170,
              render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm"),
            },
            {
              title: "最近使用",
              dataIndex: "last_used_at",
              width: 170,
              render: (value: string | null) =>
                value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "从未使用",
            },
            {
              title: "操作",
              width: 150,
              render: (_, token) => (
                <Space size={0}>
                  {token.status === "active" && (
                    <Popconfirm
                      title="撤销这个令牌？"
                      description="使用该令牌的插件会立即失去访问权限。"
                      okText="撤销"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => revoke(token)}
                    >
                      <Button type="link" danger size="small">
                        撤销
                      </Button>
                    </Popconfirm>
                  )}
                  <Popconfirm
                    title="删除这个令牌记录？"
                    description="删除后不可恢复；如果令牌仍然有效，会立即失效。"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => remove(token)}
                  >
                    <Button type="link" danger size="small">
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建访问令牌"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={create}
        okText="创建"
        confirmLoading={saving}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ scopes: ["studio:read"], expires_in_days: 90 }}
        >
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入令牌名称" }]}
            extra="用于识别使用场景，例如「训练仓库-分割实验」。"
          >
            <Input placeholder="训练仓库-分割实验" maxLength={80} />
          </Form.Item>
          <Form.Item
            name="repo_key"
            label="训练仓库标识（repo_key）"
            extra="同一训练仓库多机共用；实验镜像按它归属。留空表示通用令牌（不能推送实验）。"
          >
            <Input placeholder="spine_locator" maxLength={80} />
          </Form.Item>
          <Form.Item
            name="scopes"
            label="权限范围"
            rules={[{ required: true, message: "至少选择一个权限" }]}
          >
            <Checkbox.Group
              style={{ display: "flex", flexDirection: "column", gap: 10 }}
              options={scopes.map((scope) => ({
                value: scope.code,
                label: (
                  <span>
                    <Text strong>{scope.name}</Text>{" "}
                    <Text type="secondary">（{scope.code}）</Text>
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {scope.description}
                      </Text>
                    </div>
                  </span>
                ),
              }))}
            />
          </Form.Item>
          <Form.Item name="expires_in_days" label="有效期">
            <Select options={EXPIRY_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="令牌已创建"
        open={created !== null}
        onCancel={() => setCreated(null)}
        footer={[
          <Button
            key="copy"
            type="primary"
            icon={<CopyOutlined />}
            onClick={() => created && copyText(created.token)}
          >
            复制令牌
          </Button>,
          <Button key="close" onClick={() => setCreated(null)}>
            我已保存
          </Button>,
        ]}
      >
        <Alert
          type="warning"
          showIcon
          message="令牌只显示这一次"
          description="关闭窗口后无法再次查看，只能撤销后重新创建。请勿把令牌提交到 Git 仓库。"
        />
        <Input.TextArea
          readOnly
          value={created?.token}
          autoSize={{ minRows: 3, maxRows: 5 }}
          style={{ marginTop: 16, fontFamily: "monospace" }}
        />
        {created && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">
              <KeyOutlined /> 仓库：{created.info.repo_key || "通用"}；
              权限：{created.info.scopes.map(scopeLabel).join("、")}；
              到期：{dayjs(created.info.expires_at).format("YYYY-MM-DD HH:mm")}
            </Text>
          </div>
        )}
      </Modal>
    </div>
  );
}
