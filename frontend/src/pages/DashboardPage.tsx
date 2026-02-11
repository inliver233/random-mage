import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, Row, Skeleton, Space, Typography } from "antd";
import React from "react";

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

function asApiError(err: unknown): ApiError | null {
  return err instanceof ApiError ? err : null;
}

function requestIdFromError(err: unknown): string | null {
  const apiErr = asApiError(err);
  if (!apiErr?.body?.request_id) return null;
  return String(apiErr.body.request_id);
}

export function DashboardPage() {
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
              description={requestIdFromError(settings.error) ? `request_id: ${requestIdFromError(settings.error)}` : ""}
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
  );
}

