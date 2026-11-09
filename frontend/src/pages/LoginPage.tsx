import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import {
  CheckCircleOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  LineChartOutlined,
  LockOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useAuth } from "../auth/AuthContext";
import { getErrorMessage } from "../api";

const { Title, Text, Paragraph } = Typography;

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const requestedNext = params.get("next");
  const target =
    requestedNext && requestedNext.startsWith("/") && !requestedNext.startsWith("//")
      ? requestedNext
      : "/";
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (user) navigate(target, { replace: true });
  }, [user, navigate, target]);

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    setError("");
    try {
      await login(values.username.trim(), values.password);
      navigate(target, { replace: true });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mp-login">
      <div className="mp-login-brand">
        <div className="mp-login-badge">MP</div>
        <Title level={1} style={{ color: "#fff", marginBottom: 12 }}>
          MedPowers Studio
        </Title>
        <Paragraph style={{ color: "rgba(255,255,255,0.78)", fontSize: 17, maxWidth: 520 }}>
          医疗影像数据「管、标、训、评」一体化平台。统一管理数据集与扫描流程，
          按患者 / 检查 / 序列组织影像，在数据集内直接标注，导出训练就绪数据，并对模型结果进行量化评估。
        </Paragraph>
        <Space direction="vertical" size={12} style={{ marginTop: 28 }}>
          <span className="mp-login-feature">
            <DatabaseOutlined /> 数据集管理 · 患者/检查/序列层级
          </span>
          <span className="mp-login-feature">
            <CheckCircleOutlined /> 数据集内嵌标注 · 提交审核 · 版本留痕
          </span>
          <span className="mp-login-feature">
            <ExperimentOutlined /> nnU-Net 风格训练数据导出
          </span>
          <span className="mp-login-feature">
            <LineChartOutlined /> Dice / HD95 / 检测 / 关键帧指标评估
          </span>
        </Space>
      </div>
      <div className="mp-login-panel">
        <Card className="mp-login-card" variant="borderless">
          <Title level={3} style={{ marginBottom: 4 }}>
            登录平台
          </Title>
          <Text type="secondary">请使用管理员分配的账号登录</Text>
          {error && (
            <Alert
              type="error"
              showIcon
              message={error}
              style={{ marginTop: 16 }}
            />
          )}
          <Form layout="vertical" onFinish={onFinish} style={{ marginTop: 24 }} size="large">
            <Form.Item
              name="username"
              label="用户名"
              rules={[{ required: true, message: "请输入用户名" }]}
            >
              <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form>
          <div style={{ marginTop: 18, color: "#8c9bab", fontSize: 12 }}>
            初始管理员账号为 <code>admin</code>，首次登录后请立即在「用户管理」中修改密码。
          </div>
        </Card>
      </div>
    </div>
  );
}
