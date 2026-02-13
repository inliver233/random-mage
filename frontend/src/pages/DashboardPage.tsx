import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Row, Skeleton, Space, Typography } from "antd";
import React from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, apiJson } from "../api/client";

type SummaryResponse = {
  ok: true;
  counts: {
    images: { total: number; enabled: number };
    tokens: { total: number; enabled: number };
    proxies: { endpoints_total: number; endpoints_enabled: number };
    proxy_pools: { total: number; enabled: number };
    bindings: { total: number };
    jobs: { counts: Record<string, number> };
    worker: { last_seen_at: string | null };
  };
  request_id: string;
};

type SettingsResponse = {
  ok: true;
  settings: {
    proxy: {
      enabled: boolean;
      fail_closed: boolean;
      route_mode: string;
      allowlist_domains: string[];
      default_pool_id?: string;
    };
    random: Record<string, unknown>;
    security: { hide_origin_url_in_public_json: boolean };
    rate_limit: Record<string, unknown>;
  };
  request_id: string;
};

type JobsResponse = { ok: true; items: unknown[]; next_cursor: string; request_id: string };
type CreateHydrationRunResponse = { ok: true; hydration_run_id: string; job_id: string; request_id: string };

function asApiError(err: unknown): ApiError | null {
  return err instanceof ApiError ? err : null;
}

function requestIdFromError(err: unknown): string | null {
  const apiErr = asApiError(err);
  if (!apiErr?.body?.request_id) return null;
  return String(apiErr.body.request_id);
}

function messageFromError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Unknown error";
}

export function DashboardPage() {
  const navigate = useNavigate();

  const createHydration = useMutation({
    mutationFn: () =>
      apiJson<CreateHydrationRunResponse>("/admin/api/hydration-runs", {
        method: "POST",
        body: JSON.stringify({}),
      }),
  });

  const settings = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => apiJson<SettingsResponse>("/admin/api/settings"),
  });

  const summary = useQuery({
    queryKey: ["admin", "summary"],
    queryFn: () => apiJson<SummaryResponse>("/admin/api/summary"),
  });

  const failedJobs = useQuery({
    queryKey: ["admin", "jobs", "failed"],
    queryFn: () => apiJson<JobsResponse>("/admin/api/jobs?status=failed&limit=10"),
  });

  const proxyEnabled = settings.data?.settings.proxy.enabled ?? false;
  const defaultPoolId = settings.data?.settings.proxy.default_pool_id ?? "";

  const counts = summary.data?.counts;
  const imageCount = counts?.images.total ?? 0;
  const imageEnabledCount = counts?.images.enabled ?? 0;
  const tokenCount = counts?.tokens.total ?? 0;
  const tokenEnabledCount = counts?.tokens.enabled ?? 0;
  const proxyCount = counts?.proxies.endpoints_total ?? 0;
  const proxyEnabledCount = counts?.proxies.endpoints_enabled ?? 0;
  const proxyPoolCount = counts?.proxy_pools.total ?? 0;
  const proxyPoolEnabledCount = counts?.proxy_pools.enabled ?? 0;
  const bindingCount = counts?.bindings.total ?? 0;

  const jobsCounts = counts?.jobs.counts ?? {};
  const pendingJobs = jobsCounts["pending"] ?? 0;
  const runningJobs = jobsCounts["running"] ?? 0;
  const failedJobsTotal = jobsCounts["failed"] ?? 0;
  const workerLastSeenAt = counts?.worker.last_seen_at ?? null;

  const failedJobCount = failedJobs.data?.items.length ?? 0;

  return (
    <>
      <Space wrap style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={() => navigate("/admin/import")}>
          去导入
        </Button>
        <Button onClick={() => navigate("/admin/tokens")}>去添加 Token</Button>
        <Button onClick={() => navigate("/admin/proxies")}>去添加 代理</Button>
        <Button onClick={() => navigate("/admin/random")}>打开 Playground</Button>
        <Button onClick={() => createHydration.mutate()} loading={createHydration.isPending}>
          创建补全任务
        </Button>
      </Space>

      {createHydration.isSuccess ? (
        <Alert
          type="success"
          showIcon
          message="Hydration run created"
          description={`hydration_run_id: ${createHydration.data.hydration_run_id}, job_id: ${createHydration.data.job_id}, request_id: ${createHydration.data.request_id}`}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {createHydration.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to create hydration run"
          description={
            requestIdFromError(createHydration.error)
              ? `request_id: ${requestIdFromError(createHydration.error)} (${messageFromError(createHydration.error)})`
              : messageFromError(createHydration.error)
          }
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12} xl={6}>
          <Card title="Worker / Queue">
            {summary.isLoading ? (
              <Skeleton active />
            ) : summary.isError ? (
              <Alert
                type="error"
                showIcon
                message="Failed to load summary"
                description={requestIdFromError(summary.error) ? `request_id: ${requestIdFromError(summary.error)}` : ""}
              />
            ) : (
              <Space direction="vertical">
                <Typography.Text>worker.last_seen_at: {workerLastSeenAt ? workerLastSeenAt : "(none)"}</Typography.Text>
                <Typography.Text>jobs.pending: {pendingJobs}</Typography.Text>
                <Typography.Text>jobs.running: {runningJobs}</Typography.Text>
                <Typography.Text>jobs.failed: {failedJobsTotal}</Typography.Text>
              </Space>
            )}
          </Card>
        </Col>

        <Col xs={24} md={12} xl={6}>
          <Card title="Images">
            {summary.isLoading ? (
              <Skeleton active />
            ) : summary.isError ? (
              <Alert
                type="error"
                showIcon
                message="Failed to load summary"
                description={requestIdFromError(summary.error) ? `request_id: ${requestIdFromError(summary.error)}` : ""}
              />
            ) : (
              <Space direction="vertical">
                <Typography.Text>total: {imageCount}</Typography.Text>
                <Typography.Text>enabled: {imageEnabledCount}</Typography.Text>
                <Button size="small" onClick={() => navigate("/admin/images")}>
                  打开 Images
                </Button>
              </Space>
            )}
          </Card>
        </Col>

        <Col xs={24} md={12} xl={6}>
          <Card title="Tokens">
            {summary.isLoading ? (
              <Skeleton active />
            ) : summary.isError ? (
              <Alert
                type="error"
                showIcon
                message="Failed to load summary"
                description={requestIdFromError(summary.error) ? `request_id: ${requestIdFromError(summary.error)}` : ""}
              />
            ) : (
              <Space direction="vertical">
                <Typography.Text>total: {tokenCount}</Typography.Text>
                <Typography.Text>enabled: {tokenEnabledCount}</Typography.Text>
                <Button size="small" onClick={() => navigate("/admin/tokens")}>
                  打开 Tokens
                </Button>
              </Space>
            )}
          </Card>
        </Col>

        <Col xs={24} md={12} xl={6}>
          <Card title="Proxies">
            {settings.isLoading || summary.isLoading ? (
              <Skeleton active />
            ) : settings.isError ? (
              <Alert
                type="error"
                showIcon
                message="Failed to load settings"
                description={requestIdFromError(settings.error) ? `request_id: ${requestIdFromError(settings.error)}` : ""}
              />
            ) : summary.isError ? (
              <Alert
                type="error"
                showIcon
                message="Failed to load summary"
                description={requestIdFromError(summary.error) ? `request_id: ${requestIdFromError(summary.error)}` : ""}
              />
            ) : (
              <Space direction="vertical">
                <Typography.Text>proxy.enabled: {String(proxyEnabled)}</Typography.Text>
                <Typography.Text>default_pool_id: {defaultPoolId || "(none)"}</Typography.Text>
                <Typography.Text>endpoints: {proxyEnabledCount}/{proxyCount} enabled</Typography.Text>
                <Typography.Text>pools: {proxyPoolEnabledCount}/{proxyPoolCount} enabled</Typography.Text>
                <Typography.Text>bindings: {bindingCount}</Typography.Text>
                <Button size="small" onClick={() => navigate("/admin/proxies")}>
                  打开 Proxies
                </Button>
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Failed Jobs (latest 10)">
            {failedJobs.isLoading ? (
              <Skeleton active />
            ) : failedJobs.isError ? (
              <Alert
                type="error"
                showIcon
                message="Failed to load jobs"
                description={
                  requestIdFromError(failedJobs.error) ? `request_id: ${requestIdFromError(failedJobs.error)}` : ""
                }
              />
            ) : (
              <Space direction="vertical">
                <Typography.Text>count: {failedJobCount}</Typography.Text>
                <Button size="small" onClick={() => navigate("/admin/jobs")}>
                  打开 Jobs
                </Button>
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </>
  );
}
