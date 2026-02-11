import { ConfigProvider } from "antd";
import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AdminLayout } from "./AdminLayout";
import { DashboardPage } from "../pages/DashboardPage";
import { ImportPage } from "../pages/ImportPage";
import { LoginPage } from "../pages/LoginPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";

export function App() {
  return (
    <ConfigProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/admin" replace />} />
          <Route path="/admin/login" element={<LoginPage />} />
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="import" element={<ImportPage />} />
            <Route path="*" element={<PlaceholderPage title="Not Found" />} />
          </Route>
          <Route path="*" element={<PlaceholderPage title="Not Found" />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
