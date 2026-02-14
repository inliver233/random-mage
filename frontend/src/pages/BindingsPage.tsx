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

function formatProxy(proxy: ProxyRef | null): string {
  if (!proxy) return "";
  const host = String(proxy.host || "").includes(":") && !String(proxy.host || "").startsWith("[") ? `[${proxy.host}]` : proxy.host;
  const user = String(proxy.username || "").trim();
  const auth = user ? `${user}@` : "";
  return `${proxy.scheme}://${auth}${host}:${proxy.port}`;
}

function modeLabel(mode: "primary" | "override"): string {
  return mode === "override" ? "覆盖代理" : "主代理";
}

const columns: ColumnsType<BindingItem> = [
  {
    title: "令牌",
    key: "token",
    render: (_, row) => (row.token.label ? `${row.token.label}（#${row.token.id}）` : `#${row.token.id}`),
  },
  {
    title: "代理池",
    key: "pool",
    render: (_, row) => `${row.pool.name}（#${row.pool.id}）`,
  },
  {
    title: "当前生效代理",
    key: "effective",
    render: (_, row) => (row.effective_mode === "override" ? formatProxy(row.override_proxy) : formatProxy(row.primary_proxy)),
  },
  { title: "生效模式", dataIndex: "effective_mode", key: "effective_mode", render: (value) => modeLabel(value) },
  { title: "主代理", key: "primary_proxy", render: (_, row) => formatProxy(row.primary_proxy) },
  { title: "覆盖代理", key: "override_proxy", render: (_, row) => formatProxy(row.override_proxy) || "-" },
  { title: "覆盖过期时间", dataIndex: "override_expires_at", key: "override_expires_at", render: (value) => value || "-" },
];

export function BindingsPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const initialPoolId = useMemo(() => {
    const raw = searchParams.get("pool_id");
    const value = raw ? Number.parseInt(raw, 10) : 1;
    return Number.isFinite(value) && value > 0 ? value : 1;
  }, [searchParams]);

  const [poolId, setPoolId] = useState<number>(initialPoolId);
  const [maxTokensPerProxy, setMaxTokensPerProxy] = useState<number>(2);

  const query = useQuery({
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
      queryClient.invalidateQueries({ queryKey: ["admin", "bindings", { poolId }] });
    },
  });

  const setPoolIdAndSyncUrl = (next: number) => {
    const value = Number.isFinite(next) && next > 0 ? next : 1;
    setPoolId(value);
    const params = new URLSearchParams(searchParams);
    params.set("pool_id", String(value));
    setSearchParams(params, { replace: true });
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        令牌与代理绑定
      </Typography.Title>

      <Card>
        <Space wrap>
          <Typography.Text>代理池ID:</Typography.Text>
          <InputNumber min={1} value={poolId} onChange={(value) => setPoolIdAndSyncUrl(Number(value || 1))} />
          <Typography.Text>单代理最多绑定令牌数:</Typography.Text>
          <InputNumber
            min={1}
            max={1000}
            value={maxTokensPerProxy}
            onChange={(value) => setMaxTokensPerProxy(Number(value || 2))}
          />
          <Button type="primary" onClick={() => recompute.mutate()} loading={recompute.isPending}>
            重新计算绑定
          </Button>
        </Space>

        {recompute.isError ? (
          <Alert
            type="error"
            showIcon
            message="重新计算绑定失败"
            description={requestIdFromError(recompute.error) ? `请求ID: ${requestIdFromError(recompute.error)}` : ""}
            style={{ marginTop: 12 }}
          />
        ) : null}

        {recompute.isSuccess ? (
          <Alert
            type="success"
            showIcon
            message="重新计算绑定完成"
            description={`重算数量: ${recompute.data.recomputed}，请求ID: ${recompute.data.request_id}`}
            style={{ marginTop: 12 }}
          />
        ) : null}
      </Card>

      {query.isLoading ? (
        <Skeleton active />
      ) : query.isError ? (
        <Alert
          type="error"
          showIcon
          message="加载绑定列表失败"
          description={requestIdFromError(query.error) ? `请求ID: ${requestIdFromError(query.error)}` : ""}
        />
      ) : !query.data ? (
        <Skeleton active />
      ) : query.data.items.length === 0 ? (
        <Alert
          type="info"
          showIcon
          message="暂无绑定数据"
          description="请先创建代理池并加入代理节点，然后点击“重新计算绑定”。"
        />
      ) : (
        <Card>
          <Typography.Text type="secondary">请求ID: {query.data.request_id}</Typography.Text>
          <Table<BindingItem>
            rowKey={(row) => row.id}
            columns={columns}
            dataSource={query.data.items}
            pagination={false}
            size="small"
            style={{ marginTop: 12 }}
          />
        </Card>
      )}
    </Space>
  );
}

