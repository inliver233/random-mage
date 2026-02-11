import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Skeleton, Space, Typography } from "antd";
import React from "react";

import { ApiError, apiJson } from "../api/client";

type SettingsResponse = {
  ok: true;
  settings: Record<string, unknown>;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

export function SettingsPage() {
  const q = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => apiJson<SettingsResponse>("/admin/api/settings"),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Settings
      </Typography.Title>

      <Space wrap>
        <Button disabled>Save</Button>
      </Space>

      <Alert
        type="info"
        showIcon
        message="Editing pending"
        description="Settings edit wiring is tracked in later UI action issues."
      />

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load settings"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : !q.data ? (
        <Skeleton active />
      ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
          <pre style={{ margin: 0, marginTop: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {JSON.stringify(q.data.settings, null, 2)}
          </pre>
        </Card>
      )}
    </Space>
  );
}

