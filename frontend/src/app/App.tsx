import { ConfigProvider } from "antd";
import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AdminLayout } from "./AdminLayout";
import { DashboardPage } from "../pages/DashboardPage";
import { ImportPage } from "../pages/ImportPage";
import { ImportDetailPage } from "../pages/ImportDetailPage";
import { ImagesPage } from "../pages/ImagesPage";
import { LoginPage } from "../pages/LoginPage";
import { PlaygroundPage } from "../pages/PlaygroundPage";
import { TagsPage } from "../pages/TagsPage";
import { AuthorsPage } from "../pages/AuthorsPage";
import { TokensPage } from "../pages/TokensPage";
import { ProxiesPage } from "../pages/ProxiesPage";
import { BindingsPage } from "../pages/BindingsPage";
import { JobsPage } from "../pages/JobsPage";
import { SettingsPage } from "../pages/SettingsPage";
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
            <Route path="import/:id" element={<ImportDetailPage />} />
            <Route path="random" element={<PlaygroundPage />} />
            <Route path="images" element={<ImagesPage />} />
            <Route path="tags" element={<TagsPage />} />
            <Route path="authors" element={<AuthorsPage />} />
            <Route path="tokens" element={<TokensPage />} />
            <Route path="proxies" element={<ProxiesPage />} />
            <Route path="bindings" element={<BindingsPage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<PlaceholderPage title="Not Found" />} />
          </Route>
          <Route path="*" element={<PlaceholderPage title="Not Found" />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
