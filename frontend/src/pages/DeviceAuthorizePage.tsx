import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  Result,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { CheckOutlined, CloseOutlined, KeyOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { authApi, getErrorMessage } from "../api";
import type { DeviceAuthorizationInfo, ScopeSpec } from "../api/types";

const { Title, Text, Paragraph } = Typography;

const STATUS_META: Record<
  DeviceAuthorizationInfo["status"],
  { color: string; label: string }
> = {
  pending: { color: "processing", label: "待批准" },
  approved: { color: "green", label: "已批准" },
  denied: { color: "red", label: "已拒绝" },
  expired: { color: "default", label: "已过期" },
  consumed: { color: "blue", label: "已使用" },
};

function formatUserCode(value: string) {
  const clean = value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
  return clean.length > 4 ? `${clean.slice(0, 4)}-${clean.slice(4)}` : clean;
}

export default function DeviceAuthorizePage() {
  const [params] = useSearchParams();
  const [code, setCode] = useState(formatUserCode(params.get("user_code") ?? ""));
  const [info, setInfo] = useState<DeviceAuthorizationInfo | null>(null);
  const [scopeSpecs, setScopeSpecs] = useState<Record<string, ScopeSpec>>({});
  const [loading, setLoading] = useState(false);
  const [deciding, setDeciding] = useState<"approve" | "deny" | null>(null);
  const autoLoaded = useRef(false);

  const lookup = async (value = code) => {
    const normalized = formatUserCode(value);
    if (normalized.length !== 9) {
      message.warning("请输入形如 ABCD-EFGH 的设备码");
      return;
    }
    setLoading(true);
    try {
      const result = await authApi.deviceLookup(normalized);
      setInfo(result);
      setCode(normalized);
    } catch (error) {
      setInfo(null);
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (autoLoaded.current) return;
    const initial = params.get("user_code");
    if (initial) {
      autoLoaded.current = true;
      void lookup(initial);
    }
  }, [params]);

  useEffect(() => {
    authApi
      .scopes()
      .then((list) =>
        setScopeSpecs(Object.fromEntries(list.map((item) => [item.code, item]))),
      )
      .catch(() => setScopeSpecs({}));
  }, []);

  const decide = async (action: "approve" | "deny") => {
    if (!info) return;
    setDeciding(action);
    try {
      const result =
        action === "approve"
          ? await authApi.deviceApprove(code)
          : await authApi.deviceDeny(code);
      setInfo(result);
      message.success(action === "approve" ? "已批准设备授权" : "已拒绝设备授权");
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setDeciding(null);
    }
  };

  const pending = info?.status === "pending";

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Title className="mp-page-title">设备授权</Title>
          <div className="mp-page-subtitle">
            medpowers 插件在训练代码仓库中发起授权后，会显示一个设备码。
            在这里确认设备与权限后，插件即可自动获得访问令牌。
          </div>
        </div>
      </div>

      <Card style={{ maxWidth: 760, margin: "0 auto" }}>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="请确认设备码来自你正在使用的插件"
            description="批准前请核对客户端名称与申请权限。不要批准来源不明的设备码。"
          />

          <Space.Compact style={{ width: "100%" }}>
            <Input
              size="large"
              value={code}
              maxLength={9}
              prefix={<KeyOutlined />}
              placeholder="ABCD-EFGH"
              style={{ fontFamily: "monospace", letterSpacing: 2 }}
              onChange={(event) => setCode(formatUserCode(event.target.value))}
              onPressEnter={() => lookup()}
            />
            <Button size="large" type="primary" loading={loading} onClick={() => lookup()}>
              查询
            </Button>
          </Space.Compact>

          {loading && (
            <div style={{ textAlign: "center", padding: 24 }}>
              <Spin />
            </div>
          )}

          {info && !loading && (
            <Card size="small" title="授权请求" style={{ background: "#fafcff" }}>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="客户端">
                  <Text strong>{info.client_name || "未命名客户端"}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="训练仓库">
                  <Text code>{info.repo_key || "未指定"}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="申请权限">
                  <Space size={[4, 4]} wrap>
                    {info.scopes.map((scope) => (
                      <Tooltip key={scope} title={scopeSpecs[scope]?.description}>
                        <Tag>{scopeSpecs[scope]?.name ?? scope}</Tag>
                      </Tooltip>
                    ))}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="设备码有效期">
                  {dayjs(info.expires_at).format("YYYY-MM-DD HH:mm:ss")}
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={STATUS_META[info.status].color}>
                    {STATUS_META[info.status].label}
                  </Tag>
                </Descriptions.Item>
              </Descriptions>

              {pending ? (
                <Space style={{ marginTop: 12 }}>
                  <Button
                    type="primary"
                    icon={<CheckOutlined />}
                    loading={deciding === "approve"}
                    onClick={() => decide("approve")}
                  >
                    批准
                  </Button>
                  <Button
                    danger
                    icon={<CloseOutlined />}
                    loading={deciding === "deny"}
                    onClick={() => decide("deny")}
                  >
                    拒绝
                  </Button>
                </Space>
              ) : info.status === "approved" ? (
                <Result
                  status="success"
                  title="已批准"
                  subTitle="请回到插件或终端继续，插件会自动领取访问令牌。"
                  style={{ paddingBottom: 0 }}
                />
              ) : info.status === "denied" ? (
                <Result
                  status="warning"
                  title="已拒绝"
                  subTitle="插件将无法获得访问令牌。如属误操作，请让插件重新发起授权。"
                  style={{ paddingBottom: 0 }}
                />
              ) : info.status === "expired" ? (
                <Result
                  status="warning"
                  title="设备码已过期"
                  subTitle="请让插件重新发起授权，生成新的设备码后再操作。"
                  style={{ paddingBottom: 0 }}
                />
              ) : (
                <Result
                  status="info"
                  title="该设备码已被使用"
                  subTitle="令牌已经发放给插件；如需重新授权，请让插件重新发起。"
                  style={{ paddingBottom: 0 }}
                />
              )}
            </Card>
          )}

          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            也可以手动创建长期令牌：<Link to="/access">前往访问令牌页</Link>。
          </Paragraph>
        </Space>
      </Card>
    </div>
  );
}
