import { Button, Layout, Menu, Space, Typography } from "antd";
import React from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

type NavItem = { key: string; label: string };

const NAV_ITEMS: NavItem[] = [
  { key: "/admin", label: "主页" },
  { key: "/admin/import", label: "导入链接" },
  { key: "/admin/images", label: "图片管理" },
  { key: "/admin/hydration", label: "补全管理" },
  { key: "/admin/jobs", label: "任务队列" },
  { key: "/admin/tokens", label: "令牌管理" },
  { key: "/admin/proxies", label: "代理节点" },
  { key: "/admin/proxy-pools", label: "代理池" },
  { key: "/admin/bindings", label: "绑定关系" },
  { key: "/admin/settings", label: "系统设置" },
  { key: "/admin/audit", label: "审计日志" },
  { key: "/admin/random", label: "随机调试" },
];

function pickSelectedKey(pathname: string): string {
  const path = String(pathname || "").trim() || "/admin";
  const candidates = [...NAV_ITEMS].sort((a, b) => b.key.length - a.key.length);
  for (const item of candidates) {
    if (path === item.key) return item.key;
    if (path.startsWith(item.key + "/")) return item.key;
  }
  return "/admin";
}

export function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const isRoot = location.pathname === "/admin" || location.pathname === "/admin/";
  const selectedKey = pickSelectedKey(location.pathname);

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Sider width={220} theme="light" style={{ borderRight: "1px solid #f0f0f0" }}>
        <div style={{ padding: "16px 16px 8px" }}>
          <Typography.Title level={5} style={{ margin: 0, cursor: "pointer" }} onClick={() => navigate("/admin")}>
            随机图片管理后台
          </Typography.Title>
          <Typography.Text type="secondary">一站式管理面板</Typography.Text>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={NAV_ITEMS.map((it) => ({ key: it.key, label: it.label }))}
          onClick={(e) => navigate(String(e.key))}
        />
      </Layout.Sider>

      <Layout>
        <Layout.Header style={{ background: "#fff", padding: "0 24px" }}>
          <Space align="center" style={{ height: 64 }}>
            {!isRoot ? (
              <Button size="small" onClick={() => navigate(-1)}>
                返回
              </Button>
            ) : null}
            <Button size="small" onClick={() => navigate("/admin")}>
              主页
            </Button>
          </Space>
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
