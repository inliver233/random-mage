import { ConfigProvider, Layout, Typography } from "antd";
import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { PlaceholderPage } from "../pages/PlaceholderPage";

export function App() {
  return (
    <ConfigProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/admin" replace />} />
          <Route path="/admin/login" element={<PlaceholderPage title="Login" />} />
          <Route
            path="/admin"
            element={
              <Layout style={{ minHeight: "100vh" }}>
                <Layout.Content style={{ padding: 24 }}>
                  <Typography.Title level={3} style={{ marginTop: 0 }}>
                    Random Mage Admin
                  </Typography.Title>
                  <PlaceholderPage title="Dashboard" />
                </Layout.Content>
              </Layout>
            }
          />
          <Route path="*" element={<PlaceholderPage title="Not Found" />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}

