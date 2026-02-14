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
  { title: "图片ID", dataIndex: "id", key: "id" },
  { title: "作品ID", dataIndex: "illust_id", key: "illust_id" },
  { title: "页码", dataIndex: "page_index", key: "page_index" },
  { title: "格式", dataIndex: "ext", key: "ext" },
  { title: "宽", dataIndex: "width", key: "width" },
  { title: "高", dataIndex: "height", key: "height" },
  { title: "R18", dataIndex: "x_restrict", key: "x_restrict" },
  { title: "AI", dataIndex: "ai_type", key: "ai_type" },
  { title: "作者", key: "user", render: (_, row) => (row.user?.name ? row.user.name : "") },
  { title: "标题", dataIndex: "title", key: "title" },
  { title: "Pixiv 发布时间", dataIndex: "created_at_pixiv", key: "created_at_pixiv" },
];

export function ImagesPage() {
  const query = useQuery({
    queryKey: ["public", "images", { limit: 50, r18: 2 }],
    queryFn: () => apiJson<ImagesListResponse>("/images?limit=50&r18=2"),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        图片列表
      </Typography.Title>

      {query.isLoading ? (
        <Skeleton active />
      ) : query.isError ? (
        <Alert
          type="error"
          showIcon
          message="加载图片列表失败"
          description={requestIdFromError(query.error) ? `请求ID: ${requestIdFromError(query.error)}` : ""}
        />
      ) : (
        <Card>
          <Typography.Text type="secondary">请求ID: {query.data?.request_id}</Typography.Text>
          <Table<ImageItem>
            rowKey={(row) => row.id}
            columns={columns}
            dataSource={query.data?.items || []}
            pagination={false}
            size="small"
            style={{ marginTop: 12 }}
          />
        </Card>
      )}
    </Space>
  );
}

