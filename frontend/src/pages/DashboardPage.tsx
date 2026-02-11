import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Row, Skeleton, Space, Typography } from "antd";
import React from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, apiJson } from "../api/client";

type SettingsResponse = {
  ok: true;
  settings: {
    proxy: { enabled: boolean; fail_closed: boolean; route_mode: string; allowlist_domains: string[] };
    random: Record<string, unknown>;
    security: { hide_origin_url_in_public_json: boolean };
    rate_limit: Record<string, unknown>;
  };
  request_id: string;
};

type TokensResponse = { ok: true; items: unknown[]; request_id: string };
type ProxiesResponse = { ok: true; items: unknown[]; request_id: string };
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

  const tokens = useQuery({
    queryKey: ["admin", "tokens"],
    queryFn: () => apiJson<TokensResponse>("/admin/api/tokens"),
  });

  const proxies = useQuery({
    queryKey: ["admin", "proxies", "endpoints"],
    queryFn: () => apiJson<ProxiesResponse>("/admin/api/proxies/endpoints"),
  });

  const failedJobs = useQuery({
    queryKey: ["admin", "jobs", "failed"],
    queryFn: () => apiJson<JobsResponse>("/admin/api/jobs?status=failed&limit=10"),
  });

  const proxyEnabled = settings.data?.settings.proxy.enabled ?? false;
  const tokenCount = tokens.data?.items.length ?? 0;
  const proxyCount = proxies.data?.items.length ?? 0;
  const failedJobCount = failedJobs.data?.items.length ?? 0;

  return (
    <>
      <Space wrap style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={() => navigate("/admin/import")}>
          去导入
        </Button>
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
          <Card title="Settings">
            {settings.isLoading ? (
              <Skeleton active />
            ) : settings.isError ? (
              <Alert
                type="error"
                showIcon
                message="Failed to load settings"
                description={
                  requestIdFromError(settings.error) ? `request_id: ${requestIdFromError(settings.error)}` : ""
                }
              />
            ) : (
              <Space direction="vertical">
                <Typography.Text>proxy.enabled: {String(proxyEnabled)}</Typography.Text>
                <Typography.Text type="secondary">request_id: {settings.data?.request_id}</Typography.Text>
              </Space>
            )}
          </Card>
        </Col>

      <Col xs={24} md={12} xl={6}>
        <Card title="Tokens">
          {tokens.isLoading ? (
            <Skeleton active />
          ) : tokens.isError ? (
            <Alert
              type="error"
              showIcon
              message="Failed to load tokens"
              description={requestIdFromError(tokens.error) ? `request_id: ${requestIdFromError(tokens.error)}` : ""}
            />
          ) : (
            <Space direction="vertical">
              <Typography.Text>count: {tokenCount}</Typography.Text>
              <Typography.Text type="secondary">request_id: {tokens.data?.request_id}</Typography.Text>
            </Space>
          )}
        </Card>
      </Col>

      <Col xs={24} md={12} xl={6}>
        <Card title="Proxies">
          {proxies.isLoading ? (
            <Skeleton active />
          ) : proxies.isError ? (
            <Alert
              type="error"
              showIcon
              message="Failed to load proxies"
              description={requestIdFromError(proxies.error) ? `request_id: ${requestIdFromError(proxies.error)}` : ""}
            />
          ) : (
            <Space direction="vertical">
              <Typography.Text>count: {proxyCount}</Typography.Text>
              <Typography.Text type="secondary">request_id: {proxies.data?.request_id}</Typography.Text>
            </Space>
          )}
        </Card>
      </Col>

      <Col xs={24} md={12} xl={6}>
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
              <Typography.Text type="secondary">request_id: {failedJobs.data?.request_id}</Typography.Text>
            </Space>
          )}
        </Card>
      </Col>
      </Row>
    </>
  );
}
