import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React from "react";

import { ApiError, apiJson } from "../api/client";

type ImageItem = {
  id: string;
  illust_id: string;
  page_index: number;
  ext: string;
  width: number | null;
  height: number | null;
  x_restrict: number | null;
  ai_type: number | null;
  user: { id: string | null; name: string | null };
  title: string | null;
  created_at_pixiv: string | null;
};

type ImagesListResponse = {
  ok: true;
  items: ImageItem[];
  next_cursor: string;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const columns: ColumnsType<ImageItem> = [
  { title: "ID", dataIndex: "id", key: "id" },
  { title: "Illust", dataIndex: "illust_id", key: "illust_id" },
  { title: "P", dataIndex: "page_index", key: "page_index" },
  { title: "Ext", dataIndex: "ext", key: "ext" },
  { title: "W", dataIndex: "width", key: "width" },
  { title: "H", dataIndex: "height", key: "height" },
  { title: "R18", dataIndex: "x_restrict", key: "x_restrict" },
  { title: "AI", dataIndex: "ai_type", key: "ai_type" },
  {
    title: "User",
    key: "user",
    render: (_, r) => (r.user?.name ? `${r.user.name}` : ""),
  },
  { title: "Title", dataIndex: "title", key: "title" },
  { title: "Created", dataIndex: "created_at_pixiv", key: "created_at_pixiv" },
];

export function ImagesPage() {
  const q = useQuery({
    queryKey: ["public", "images", { limit: 50, r18: 2 }],
    queryFn: () => apiJson<ImagesListResponse>("/images?limit=50&r18=2"),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Images
      </Typography.Title>

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load images"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data?.request_id}</Typography.Text>
          <Table<ImageItem>
            rowKey={(r) => r.id}
            columns={columns}
            dataSource={q.data?.items || []}
            pagination={false}
            size="small"
            style={{ marginTop: 12 }}
          />
        </Card>
      )}
    </Space>
  );
}
