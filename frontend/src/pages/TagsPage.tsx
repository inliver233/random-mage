import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, apiJson } from "../api/client";

type TagItem = {
  name: string;
  translated_name: string | null;
  count_images: number | null;
};

type TagsListResponse = {
  ok: true;
  items: TagItem[];
  next_cursor: string;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const baseColumns: ColumnsType<TagItem> = [
  { title: "Name", dataIndex: "name", key: "name" },
  { title: "Translated", dataIndex: "translated_name", key: "translated_name" },
  { title: "Count", dataIndex: "count_images", key: "count_images" },
];

export function TagsPage() {
  const navigate = useNavigate();

  const q = useQuery({
    queryKey: ["public", "tags", { limit: 50 }],
    queryFn: () => apiJson<TagsListResponse>("/tags?limit=50"),
  });

  const columns: ColumnsType<TagItem> = [
    ...baseColumns,
    {
      title: "Actions",
      key: "actions",
      render: (_, r) => (
        <Button
          size="small"
          onClick={() => navigate(`/admin/random?format=image&included_tags=${encodeURIComponent(r.name)}`)}
        >
          从该标签随机一张
        </Button>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Tags
      </Typography.Title>

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load tags"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : !q.data ? (
        <Skeleton active />
      ) : q.data.items.length === 0 ? (
        <Alert
          type="info"
          showIcon
          message="No tags"
          description="Import images and run hydration to populate tags."
        />
      ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
          <Table<TagItem>
            rowKey={(r) => r.name}
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
