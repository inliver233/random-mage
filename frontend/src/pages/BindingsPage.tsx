import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, InputNumber, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React, { useState } from "react";

import { ApiError, apiJson } from "../api/client";

type BindingItem = {
  id: string;
  token_id: string;
  proxy_id: string;
  is_primary: boolean;
  override_proxy_id: string | null;
  override_expires_at: string | null;
  reason: string | null;
};

type BindingsListResponse = {
  ok: true;
  items: BindingItem[];
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const columns: ColumnsType<BindingItem> = [
  { title: "Token", dataIndex: "token_id", key: "token_id" },
  { title: "Proxy", dataIndex: "proxy_id", key: "proxy_id" },
  { title: "Primary", dataIndex: "is_primary", key: "is_primary", render: (v) => String(Boolean(v)) },
  { title: "Override", dataIndex: "override_proxy_id", key: "override_proxy_id" },
  { title: "Override TTL", dataIndex: "override_expires_at", key: "override_expires_at" },
  { title: "Reason", dataIndex: "reason", key: "reason" },
];

export function BindingsPage() {
  const [poolId, setPoolId] = useState<number>(1);

  const q = useQuery({
    queryKey: ["admin", "bindings", { poolId }],
    queryFn: () => apiJson<BindingsListResponse>(`/admin/api/bindings?pool_id=${poolId}`),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Bindings
      </Typography.Title>

      <Space wrap>
        <Typography.Text>Pool ID:</Typography.Text>
        <InputNumber min={1} value={poolId} onChange={(v) => setPoolId(Number(v || 1))} />
        <Button disabled>Recompute</Button>
      </Space>

      <Alert
        type="info"
        showIcon
        message="Actions pending"
        description="Binding recompute / override actions are wired in later UI action issues."
      />

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load bindings"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : !q.data ? (
        <Skeleton active />
      ) : q.data.items.length === 0 ? (
        <Alert type="info" showIcon message="No bindings" description="Create proxy pools and recompute bindings." />
      ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
          <Table<BindingItem>
            rowKey={(r) => r.id}
            columns={columns}
            dataSource={q.data.items}
            pagination={false}
            size="small"
            style={{ marginTop: 12 }}
          />
        </Card>
      )}
    </Space>
  );
}

