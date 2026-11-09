import { useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Avatar,
  Dropdown,
  Layout,
  Menu,
  Space,
  Tag,
  Typography,
} from "antd";
import {
  BarChartOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  ExportOutlined,
  KeyOutlined,
  LogoutOutlined,
  MedicineBoxOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useAuth } from "../auth/AuthContext";

const { Sider, Header, Content, Footer } = Layout;
const { Text } = Typography;

export default function MainLayout() {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  const selectedKey = useMemo(() => {
    const path = location.pathname;
    const candidates = [
      "/datasets",
      "/tasks",
      "/experiments",
      "/exports",
      "/evaluations",
      "/access",
      "/device",
      "/protocols",
      "/users",
    ];
    return candidates.find((item) => path === item || path.startsWith(`${item}/`)) ?? "/";
  }, [location.pathname]);

  const items = [
    { key: "/", icon: <DashboardOutlined />, label: "概览" },
    { key: "/datasets", icon: <DatabaseOutlined />, label: "数据集" },
    { key: "/tasks", icon: <ExperimentOutlined />, label: "任务" },
    { key: "/experiments", icon: <BarChartOutlined />, label: "实验与指标" },
    { key: "/exports", icon: <ExportOutlined />, label: "训练导出" },
    { key: "/evaluations", icon: <BarChartOutlined />, label: "评估" },
    { key: "/access", icon: <KeyOutlined />, label: "访问令牌" },
    ...(isAdmin
      ? [
          {
            key: "config",
            icon: <SettingOutlined />,
            label: "基础配置",
            children: [
              { key: "/protocols", icon: <MedicineBoxOutlined />, label: "扫描流程" },
              { key: "/users", icon: <TeamOutlined />, label: "用户管理" },
            ],
          },
        ]
      : []),
  ];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={232}
        style={{ position: "sticky", top: 0, height: "100vh" }}
      >
        <div className="mp-logo">
          <div className="mp-logo-mark">MP</div>
          {!collapsed && (
            <div>
              <div className="mp-logo-title">MedPowers Studio</div>
              <div className="mp-logo-sub">医疗影像管标训评平台</div>
            </div>
          )}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          defaultOpenKeys={["config"]}
          items={items}
          onClick={({ key }) => {
            if (key.startsWith("/")) navigate(key);
          }}
        />
      </Sider>
      <Layout>
        <Header className="mp-header">
          <div>
            <Text strong style={{ fontSize: 16 }}>
              医疗影像数据 · 标注 · 训练导出 · 评估
            </Text>
          </div>
          <Dropdown
            menu={{
              items: [
                {
                  key: "access",
                  icon: <KeyOutlined />,
                  label: "访问令牌",
                  onClick: () => navigate("/access"),
                },
                {
                  key: "logout",
                  icon: <LogoutOutlined />,
                  label: "退出登录",
                  onClick: logout,
                },
              ],
            }}
            placement="bottomRight"
          >
            <Space style={{ cursor: "pointer" }}>
              <Avatar size={34} icon={<UserOutlined />} style={{ background: "#1677ff" }} />
              <div style={{ lineHeight: 1.3 }}>
                <div style={{ fontWeight: 600 }}>
                  {user?.display_name || user?.username}
                </div>
                <div>
                  <Tag color={user?.role === "admin" ? "gold" : user?.role === "reviewer" ? "purple" : "blue"}>
                    {user?.role === "admin" ? "管理员" : user?.role === "reviewer" ? "审核员" : "标注员"}
                  </Tag>
                </div>
              </div>
            </Space>
          </Dropdown>
        </Header>
        <Content>
          <Outlet />
        </Content>
        {/* 标注工作台使用全屏四宫格，隐藏页脚避免出现页面滚动 */}
        {!location.pathname.includes("/annotate/") && (
          <Footer
            style={{ textAlign: "center", color: "#8c9bab", background: "transparent" }}
          >
            MedPowers Studio · 数据管理与标注平台预览版
          </Footer>
        )}
      </Layout>
    </Layout>
  );
}
