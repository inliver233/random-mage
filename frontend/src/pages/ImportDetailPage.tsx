import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Descriptions, Progress, Skeleton, Space, Typography } from "antd";
import React from "react";
import { useParams } from "react-router-dom";

import { ApiError, apiJson } from "../api/client";

type ImportDetailResponse = {
  ok: true;
  item: {
    import: {
      id: string;
      created_at: string;
      created_by: string;
      source: string;
      total: number;
      accepted: number;
      success: number;
      failed: number;
    };
    job:
      | {
          id: string;
          type: string;
          status: string;
          attempt: number;
          max_attempts: number;
          last_error: string | null;
        }
      | null;
    detail: Record<string, unknown>;
  };
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

export function ImportDetailPage() {
  const params = useParams();
  const idRaw = String(params.id || "").trim();
  const id = idRaw && /^\d+$/.test(idRaw) ? idRaw : "";

  const q = useQuery({
    queryKey: ["admin", "imports", id],
    enabled: Boolean(id),
    queryFn: () => apiJson<ImportDetailResponse>(`/admin/api/imports/${id}`),
    refetchInterval: (query) => {
      const data = query.state.data as ImportDetailResponse | undefined;
      const status = String(data?.item.job?.status || "");
      return status === "pending" || status === "running" ? 1000 : false;
    },
  });

  if (!id) {
    return <Alert type="error" showIcon message="Invalid import id" />;
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Import #{id}
      </Typography.Title>

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load import"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : (
        <>
          <Typography.Text type="secondary">request_id: {q.data?.request_id}</Typography.Text>

          {q.data?.item.job && (q.data.item.job.status === "pending" || q.data.item.job.status === "running") ? (
            <Alert type="info" showIcon message="Import in progress (auto refresh every 1s)" />
          ) : null}

          <Card title="Summary">
            <Descriptions size="small" column={2}>
              <Descriptions.Item label="created_at">{q.data?.item.import.created_at}</Descriptions.Item>
              <Descriptions.Item label="created_by">{q.data?.item.import.created_by}</Descriptions.Item>
              <Descriptions.Item label="source">{q.data?.item.import.source}</Descriptions.Item>
              <Descriptions.Item label="total">{q.data?.item.import.total}</Descriptions.Item>
              <Descriptions.Item label="accepted">{q.data?.item.import.accepted}</Descriptions.Item>
              <Descriptions.Item label="success">{q.data?.item.import.success}</Descriptions.Item>
              <Descriptions.Item label="failed">{q.data?.item.import.failed}</Descriptions.Item>
            </Descriptions>

            {q.data?.item.job ? (
              <div style={{ marginTop: 12 }}>
                <Progress
                  percent={(() => {
                    const accepted = Number(q.data?.item.import.accepted || 0);
                    const total = Number(q.data?.item.import.total || 0);
                    const denom = accepted > 0 ? accepted : total > 0 ? total : 0;
                    const success = Number(q.data?.item.import.success || 0);
                    if (denom <= 0) return 0;
                    const pct = Math.round((success / denom) * 100);
                    return Math.max(0, Math.min(100, pct));
                  })()}
                  status={
                    q.data.item.job.status === "completed"
                      ? "success"
                      : q.data.item.job.status === "failed" || q.data.item.job.status === "dlq"
                        ? "exception"
                        : "active"
                  }
                />
              </div>
            ) : null}
          </Card>

          <Card title="Job">
            {q.data?.item.job ? (
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="id">{q.data.item.job.id}</Descriptions.Item>
                <Descriptions.Item label="type">{q.data.item.job.type}</Descriptions.Item>
                <Descriptions.Item label="status">{q.data.item.job.status}</Descriptions.Item>
                <Descriptions.Item label="attempt">{q.data.item.job.attempt}</Descriptions.Item>
                <Descriptions.Item label="max_attempts">{q.data.item.job.max_attempts}</Descriptions.Item>
                <Descriptions.Item label="last_error">{q.data.item.job.last_error || ""}</Descriptions.Item>
              </Descriptions>
            ) : (
              <Alert type="info" showIcon message="No job attached" />
            )}
          </Card>

          <Card title="Detail JSON">
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(q.data?.item.detail || {}, null, 2)}
            </pre>
          </Card>
        </>
      )}
    </Space>
  );
}
