import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Select, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React, { useState } from "react";

import { ApiError, apiJson } from "../api/client";

type JobItem = {
  id: string;
  type: string;
  status: string;
  attempt: number | null;
  max_attempts: number | null;
  run_after: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  updated_at: string | null;
};

type JobsListResponse = {
  ok: true;
  items: JobItem[];
  next_cursor: string;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const columns: ColumnsType<JobItem> = [
  { title: "ID", dataIndex: "id", key: "id" },
  { title: "Type", dataIndex: "type", key: "type" },
  { title: "Status", dataIndex: "status", key: "status" },
  {
    title: "Attempt",
    key: "attempt",
    render: (_, r) => `${r.attempt ?? "-"} / ${r.max_attempts ?? "-"}`,
  },
  { title: "Run after", dataIndex: "run_after", key: "run_after" },
  { title: "Error", key: "error", render: (_, r) => (r.last_error_code ? `${r.last_error_code}: ${r.last_error_message ?? ""}` : "") },
  { title: "Updated", dataIndex: "updated_at", key: "updated_at" },
];

export function JobsPage() {
  const [status, setStatus] = useState<string>("failed");

  const q = useQuery({
    queryKey: ["admin", "jobs", { status, limit: 20 }],
    queryFn: () => apiJson<JobsListResponse>(`/admin/api/jobs?status=${encodeURIComponent(status)}&limit=20`),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Jobs
      </Typography.Title>

      <Space wrap>
        <Typography.Text>Status:</Typography.Text>
        <Select
          value={status}
          onChange={(v) => setStatus(v)}
          options={[
            { value: "failed", label: "failed" },
            { value: "pending", label: "pending" },
            { value: "running", label: "running" },
            { value: "done", label: "done" },
            { value: "dlq", label: "dlq" },
          ]}
          style={{ width: 160 }}
        />
        <Button disabled>Retry</Button>
        <Button disabled>Cancel</Button>
        <Button disabled>Move to DLQ</Button>
      </Space>

      <Alert type="info" showIcon message="Actions pending" description="Job retry/cancel actions are wired in later UI action issues." />

      <Card>
        {q.isLoading ? (
          <Skeleton active />
        ) : q.isError ? (
          <Alert
            type="error"
            showIcon
            message="Failed to load jobs"
            description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
          />
        ) : !q.data ? (
          <Skeleton active />
        ) : q.data.items.length === 0 ? (
          <Alert type="info" showIcon message="No jobs" description="Trigger import/hydration/proxy probe to create jobs." />
        ) : (
          <>
            <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
            <Table<JobItem>
              rowKey={(r) => r.id}
              columns={columns}
              dataSource={q.data.items}
              pagination={false}
              size="small"
              style={{ marginTop: 12 }}
            />
          </>
        )}
      </Card>
    </Space>
  );
}

