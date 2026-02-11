import { Layout, Typography } from "antd";
import React from "react";
import { Outlet } from "react-router-dom";

export function AdminLayout() {
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Header style={{ background: "#fff", padding: "0 24px" }}>
        <Typography.Title level={4} style={{ margin: 0, lineHeight: "64px" }}>
          Random Mage Admin
        </Typography.Title>
      </Layout.Header>
      <Layout.Content style={{ padding: 24 }}>
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}

