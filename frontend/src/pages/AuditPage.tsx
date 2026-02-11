import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React from "react";

import { ApiError, apiJson } from "../api/client";

type AuditItem = {
  id: string;
  created_at: string;
  actor: string | null;
  action: string;
  resource: string;
  record_id: string | null;
  request_id: string | null;
  detail_json: Record<string, unknown> | null;
};

type AuditListResponse = {
  ok: true;
  items: AuditItem[];
  next_cursor: string;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const columns: ColumnsType<AuditItem> = [
  { title: "Created", dataIndex: "created_at", key: "created_at" },
  { title: "Actor", dataIndex: "actor", key: "actor" },
  { title: "Action", dataIndex: "action", key: "action" },
  { title: "Resource", dataIndex: "resource", key: "resource" },
  { title: "Record", dataIndex: "record_id", key: "record_id" },
  { title: "Req", dataIndex: "request_id", key: "request_id" },
  {
    title: "Detail",
    key: "detail_json",
    render: (_, r) => (
      <pre style={{ margin: 0, maxWidth: 360, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {r.detail_json ? JSON.stringify(r.detail_json) : ""}
      </pre>
    ),
  },
];

export function AuditPage() {
  const q = useQuery({
    queryKey: ["admin", "audit", { limit: 50 }],
    queryFn: () => apiJson<AuditListResponse>("/admin/api/audit?limit=50"),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Audit
      </Typography.Title>

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load audit logs"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : !q.data ? (
        <Skeleton active />
      ) : q.data.items.length === 0 ? (
        <Alert type="info" showIcon message="No audit logs" description="Audit records will appear after admin actions." />
      ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
          <Table<AuditItem>
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

