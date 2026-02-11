import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React from "react";

import { ApiError, apiJson } from "../api/client";

type TokenItem = {
  id: string;
  label: string | null;
  enabled: boolean;
  refresh_token_masked: string | null;
  weight: number | null;
  error_count: number | null;
  backoff_until: string | null;
  last_ok_at: string | null;
  last_fail_at: string | null;
};

type TokensListResponse = {
  ok: true;
  items: TokenItem[];
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const columns: ColumnsType<TokenItem> = [
  { title: "Label", dataIndex: "label", key: "label" },
  { title: "Enabled", dataIndex: "enabled", key: "enabled", render: (v) => String(Boolean(v)) },
  { title: "Masked", dataIndex: "refresh_token_masked", key: "refresh_token_masked" },
  { title: "Weight", dataIndex: "weight", key: "weight" },
  { title: "Errors", dataIndex: "error_count", key: "error_count" },
  { title: "Backoff", dataIndex: "backoff_until", key: "backoff_until" },
  { title: "Last OK", dataIndex: "last_ok_at", key: "last_ok_at" },
  { title: "Last Fail", dataIndex: "last_fail_at", key: "last_fail_at" },
];

export function TokensPage() {
  const q = useQuery({
    queryKey: ["admin", "tokens"],
    queryFn: () => apiJson<TokensListResponse>("/admin/api/tokens"),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Tokens
      </Typography.Title>

      <Space wrap>
        <Button disabled>新增 Token</Button>
        <Button disabled>测试刷新</Button>
        <Button disabled>启用/禁用</Button>
        <Button disabled>重置失败退避</Button>
      </Space>

      <Alert
        type="info"
        showIcon
        message="Actions pending"
        description="Token create/test/reset wiring is tracked in later UI action issues."
      />

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load tokens"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : !q.data ? (
        <Skeleton active />
      ) : q.data.items.length === 0 ? (
        <Alert type="info" showIcon message="No tokens" description="Add at least one token to enable Pixiv API jobs." />
      ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
          <Table<TokenItem>
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

