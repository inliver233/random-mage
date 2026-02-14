import { Button, Layout, Space, Typography } from "antd";
import React from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

export function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const isRoot = location.pathname === "/admin" || location.pathname === "/admin/";

  return (
    <Layout style={{ minHeight: "100vh" }}>
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
          <Button size="small" onClick={() => navigate("/admin/hydration")}>
            补全管理
          </Button>
          <Typography.Title
            level={4}
            style={{ margin: 0, lineHeight: "64px", cursor: "pointer" }}
            onClick={() => navigate("/admin")}
          >
            随机图片管理后台
          </Typography.Title>
        </Space>
      </Layout.Header>
      <Layout.Content style={{ padding: 24 }}>
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}

