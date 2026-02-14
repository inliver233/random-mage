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

function statusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "等待中";
    case "running":
      return "运行中";
    case "paused":
      return "已暂停";
    case "canceled":
      return "已取消";
    case "completed":
      return "已完成";
    case "failed":
      return "失败";
    case "dlq":
      return "死信";
    default:
      return status || "未知";
  }
}

function typeLabel(type: string): string {
  switch (type) {
    case "import_images":
      return "导入图片";
    case "hydrate_metadata":
      return "补全元数据";
    case "proxy_probe":
      return "代理探测";
    case "easy_proxies_import":
      return "导入 easy-proxies";
    case "heal_url":
      return "修复 URL";
    default:
      return type || "未知";
  }
}

const columns: ColumnsType<JobItem> = [
  { title: "任务ID", dataIndex: "id", key: "id" },
  { title: "任务类型", dataIndex: "type", key: "type", render: (value) => typeLabel(value) },
  { title: "状态", dataIndex: "status", key: "status", render: (value) => statusLabel(value) },
  {
    title: "重试次数",
    key: "attempt",
    render: (_, row) => `${row.attempt ?? "-"} / ${row.max_attempts ?? "-"}`,
  },
  { title: "下次执行时间", dataIndex: "run_after", key: "run_after" },
  {
    title: "错误",
    key: "error",
    render: (_, row) => (row.last_error_code ? `${row.last_error_code}: ${row.last_error_message ?? ""}` : ""),
  },
  { title: "更新时间", dataIndex: "updated_at", key: "updated_at" },
];

export function JobsPage() {
  const [status, setStatus] = useState<string>("failed");

  const query = useQuery({
    queryKey: ["admin", "jobs", { status, limit: 20 }],
    queryFn: () => apiJson<JobsListResponse>(`/admin/api/jobs?status=${encodeURIComponent(status)}&limit=20`),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        任务队列
      </Typography.Title>

      <Space wrap>
        <Typography.Text>状态筛选:</Typography.Text>
        <Select
          value={status}
          onChange={(value) => setStatus(value)}
          options={[
            { value: "failed", label: "失败" },
            { value: "pending", label: "等待中" },
            { value: "running", label: "运行中" },
            { value: "paused", label: "已暂停" },
            { value: "completed", label: "已完成" },
            { value: "dlq", label: "死信" },
          ]}
          style={{ width: 180 }}
        />
        <Button disabled>重试</Button>
        <Button disabled>取消</Button>
        <Button disabled>移入死信队列</Button>
      </Space>

      <Alert type="info" showIcon message="任务操作按钮暂未启用" description="当前页仅支持查看任务状态，后续会开放页面内重试/取消。" />

      <Card>
        {query.isLoading ? (
          <Skeleton active />
        ) : query.isError ? (
          <Alert
            type="error"
            showIcon
            message="加载任务列表失败"
            description={requestIdFromError(query.error) ? `请求ID: ${requestIdFromError(query.error)}` : ""}
          />
        ) : !query.data ? (
          <Skeleton active />
        ) : query.data.items.length === 0 ? (
          <Alert type="info" showIcon message="暂无任务" description="可先触发导入/补全/代理探测任务。" />
        ) : (
          <>
            <Typography.Text type="secondary">请求ID: {query.data.request_id}</Typography.Text>
            <Table<JobItem>
              rowKey={(row) => row.id}
              columns={columns}
              dataSource={query.data.items}
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
