import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, InputNumber, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError, apiJson } from "../api/client";

type ProxyRef = {
  id: string;
  scheme: string;
  host: string;
  port: number;
  username: string;
};

type BindingItem = {
  id: string;
  token: { id: string; label: string | null };
  pool: { id: string; name: string };
  primary_proxy: ProxyRef;
  override_proxy: ProxyRef | null;
  override_expires_at: string | null;
  effective_proxy_id: string;
  effective_mode: "primary" | "override";
};

type BindingsListResponse = {
  ok: true;
  items: BindingItem[];
  request_id: string;
};

type RecomputeResponse = {
  ok: true;
  pool_id: string;
  recomputed: number;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

function formatProxy(p: ProxyRef | null): string {
  if (!p) return "";
  const host = String(p.host || "").includes(":") && !String(p.host || "").startsWith("[") ? `[${p.host}]` : p.host;
  const user = String(p.username || "").trim();
  const auth = user ? `${user}@` : "";
  return `${p.scheme}://${auth}${host}:${p.port}`;
}

const columns: ColumnsType<BindingItem> = [
  {
    title: "Token",
    key: "token",
    render: (_, r) => (r.token.label ? `${r.token.label} (#${r.token.id})` : `#${r.token.id}`),
  },
  {
    title: "Pool",
    key: "pool",
    render: (_, r) => `${r.pool.name} (#${r.pool.id})`,
  },
  {
    title: "Effective",
    key: "effective",
    render: (_, r) => (r.effective_mode === "override" ? formatProxy(r.override_proxy) : formatProxy(r.primary_proxy)),
  },
  { title: "Mode", dataIndex: "effective_mode", key: "effective_mode" },
  { title: "Primary", key: "primary_proxy", render: (_, r) => formatProxy(r.primary_proxy) },
  { title: "Override", key: "override_proxy", render: (_, r) => formatProxy(r.override_proxy) || "-" },
  { title: "Override TTL", dataIndex: "override_expires_at", key: "override_expires_at", render: (v) => v || "-" },
];

export function BindingsPage() {
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialPoolId = useMemo(() => {
    const raw = searchParams.get("pool_id");
    const n = raw ? Number.parseInt(raw, 10) : 1;
    return Number.isFinite(n) && n > 0 ? n : 1;
  }, [searchParams]);

  const [poolId, setPoolId] = useState<number>(initialPoolId);
  const [maxTokensPerProxy, setMaxTokensPerProxy] = useState<number>(2);

  const q = useQuery({
    queryKey: ["admin", "bindings", { poolId }],
    queryFn: () => apiJson<BindingsListResponse>(`/admin/api/bindings?pool_id=${poolId}`),
  });

  const recompute = useMutation({
    mutationFn: () =>
      apiJson<RecomputeResponse>("/admin/api/bindings/recompute", {
        method: "POST",
        body: JSON.stringify({ pool_id: poolId, max_tokens_per_proxy: maxTokensPerProxy }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "bindings", { poolId }] });
    },
  });

  const setPoolIdAndSyncUrl = (next: number) => {
    const n = Number.isFinite(next) && next > 0 ? next : 1;
    setPoolId(n);
    const sp = new URLSearchParams(searchParams);
    sp.set("pool_id", String(n));
    setSearchParams(sp, { replace: true });
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Bindings
      </Typography.Title>

      <Card>
        <Space wrap>
          <Typography.Text>Pool ID:</Typography.Text>
          <InputNumber min={1} value={poolId} onChange={(v) => setPoolIdAndSyncUrl(Number(v || 1))} />
          <Typography.Text>Max tokens / proxy:</Typography.Text>
          <InputNumber min={1} max={1000} value={maxTokensPerProxy} onChange={(v) => setMaxTokensPerProxy(Number(v || 2))} />
          <Button type="primary" onClick={() => recompute.mutate()} loading={recompute.isPending}>
            Recompute
          </Button>
        </Space>

        {recompute.isError ? (
          <Alert
            type="error"
            showIcon
            message="Recompute failed"
            description={requestIdFromError(recompute.error) ? `request_id: ${requestIdFromError(recompute.error)}` : ""}
            style={{ marginTop: 12 }}
          />
        ) : null}
        {recompute.isSuccess ? (
          <Alert
            type="success"
            showIcon
            message="Recomputed"
            description={`recomputed: ${recompute.data.recomputed}, request_id: ${recompute.data.request_id}`}
            style={{ marginTop: 12 }}
          />
        ) : null}
      </Card>

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
        <Alert
          type="info"
          showIcon
          message="No bindings"
          description="Create a proxy pool, add endpoints to it, then click Recompute."
        />
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

