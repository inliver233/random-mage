import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React from "react";

import { ApiError, apiJson } from "../api/client";

type AuthorItem = {
  user_id: string;
  user_name: string | null;
  count_images: number | null;
};

type AuthorsListResponse = {
  ok: true;
  items: AuthorItem[];
  next_cursor: string;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const columns: ColumnsType<AuthorItem> = [
  { title: "User ID", dataIndex: "user_id", key: "user_id" },
  { title: "Name", dataIndex: "user_name", key: "user_name" },
  { title: "Count", dataIndex: "count_images", key: "count_images" },
];

export function AuthorsPage() {
  const q = useQuery({
    queryKey: ["public", "authors", { limit: 50 }],
    queryFn: () => apiJson<AuthorsListResponse>("/authors?limit=50"),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Authors
      </Typography.Title>

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load authors"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : !q.data ? (
        <Skeleton active />
      ) : q.data.items.length === 0 ? (
        <Alert type="info" showIcon message="No authors" description="Import images to populate authors." />
      ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
          <Table<AuthorItem>
            rowKey={(r) => r.user_id}
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

