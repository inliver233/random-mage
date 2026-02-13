import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input, Select, Skeleton, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React, { useState } from "react";

import { ApiError, apiJson } from "../api/client";

type ProxyEndpointItem = {
  id: string;
  uri_masked: string;
  enabled: boolean;
  latency_ms: number | null;
  status: string | null;
  blacklisted_until: string | null;
  last_error: string | null;
  success_count: number;
  failure_count: number;
  last_ok_at: string | null;
  last_fail_at: string | null;
  pools: Array<{
    id: string;
    name: string;
    pool_enabled: boolean;
    member_enabled: boolean;
    weight: number;
  }>;
  bindings: { primary_count: number; override_count: number };
};

type ProxiesEndpointsResponse = {
  ok: true;
  items: ProxyEndpointItem[];
  request_id: string;
};

type ManualImportFormValues = {
  text: string;
  source: "manual";
  conflict_policy: "overwrite" | "skip";
};

type ManualImportResponse = {
  ok: true;
  created: number;
  updated: number;
  skipped: number;
  errors: Array<{ line: number; code: string; message: string }>;
  request_id: string;
};

type EasyProxiesImportFormValues = {
  base_url: string;
  password: string;
  conflict_policy: "overwrite" | "skip_non_easy_proxies";
};

type EasyProxiesImportResponse = {
  ok: true;
  created: number;
  updated: number;
  skipped: number;
  errors: Array<{ code: string; message: string }>;
  request_id: string;
};

type ProxiesProbeResponse = {
  ok: true;
  job_id: string;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const columns: ColumnsType<ProxyEndpointItem> = [
  { title: "ID", dataIndex: "id", key: "id" },
  { title: "URI", dataIndex: "uri_masked", key: "uri_masked" },
  { title: "Enabled", dataIndex: "enabled", key: "enabled", render: (v) => String(Boolean(v)) },
  { title: "Status", dataIndex: "status", key: "status" },
  {
    title: "Pools",
    key: "pools",
    render: (_, r) =>
      (r.pools || []).length
        ? (r.pools || [])
            .map((p) => `${p.name}(#${p.id}) w=${p.weight} ${p.pool_enabled && p.member_enabled ? "on" : "off"}`)
            .join(", ")
        : "-",
  },
  {
    title: "Bindings",
    key: "bindings",
    render: (_, r) =>
      r.bindings ? `primary=${r.bindings.primary_count}, override=${r.bindings.override_count}` : "-",
  },
  { title: "OK/Fail", key: "ok_fail", render: (_, r) => `${r.success_count}/${r.failure_count}` },
  { title: "Last OK", dataIndex: "last_ok_at", key: "last_ok_at", render: (v) => v || "-" },
  { title: "Last Fail", dataIndex: "last_fail_at", key: "last_fail_at", render: (v) => v || "-" },
  { title: "Latency(ms)", dataIndex: "latency_ms", key: "latency_ms" },
  { title: "Blacklisted", dataIndex: "blacklisted_until", key: "blacklisted_until" },
  { title: "Last error", dataIndex: "last_error", key: "last_error" },
];

export function ProxiesPage() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "proxies", "endpoints"],
    queryFn: () => apiJson<ProxiesEndpointsResponse>("/admin/api/proxies/endpoints"),
  });

  const [manualErrorMessage, setManualErrorMessage] = useState<string | null>(null);
  const [manualRequestId, setManualRequestId] = useState<string | null>(null);
  const [manualResult, setManualResult] = useState<ManualImportResponse | null>(null);
  const [manualForm] = Form.useForm<ManualImportFormValues>();

  const [probeErrorMessage, setProbeErrorMessage] = useState<string | null>(null);
  const [probeRequestId, setProbeRequestId] = useState<string | null>(null);
  const [probeJobId, setProbeJobId] = useState<string | null>(null);

  const [easyErrorMessage, setEasyErrorMessage] = useState<string | null>(null);
  const [easyRequestId, setEasyRequestId] = useState<string | null>(null);
  const [easyResult, setEasyResult] = useState<EasyProxiesImportResponse | null>(null);
  const [easyForm] = Form.useForm<EasyProxiesImportFormValues>();

  const manualImport = useMutation({
    mutationFn: (values: ManualImportFormValues) =>
      apiJson<ManualImportResponse>("/admin/api/proxies/endpoints/import", {
        method: "POST",
        body: JSON.stringify(values),
      }),
    onMutate: () => {
      setManualErrorMessage(null);
      setManualRequestId(null);
      setManualResult(null);
    },
    onSuccess: (data) => {
      setManualResult(data);
      setManualRequestId(data.request_id);
      manualForm.setFieldValue("text", "");
      qc.invalidateQueries({ queryKey: ["admin", "proxies", "endpoints"] });
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setManualErrorMessage(err.message);
        setManualRequestId(requestIdFromError(err));
        return;
      }
      if (err instanceof Error) {
        setManualErrorMessage(err.message);
        return;
      }
      setManualErrorMessage("Import failed");
    },
  });

  const probe = useMutation({
    mutationFn: () => apiJson<ProxiesProbeResponse>("/admin/api/proxies/probe", { method: "POST" }),
    onMutate: () => {
      setProbeErrorMessage(null);
      setProbeRequestId(null);
      setProbeJobId(null);
    },
    onSuccess: (data) => {
      setProbeJobId(data.job_id);
      setProbeRequestId(data.request_id);
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setProbeErrorMessage(err.message);
        setProbeRequestId(requestIdFromError(err));
        return;
      }
      if (err instanceof Error) {
        setProbeErrorMessage(err.message);
        return;
      }
      setProbeErrorMessage("Probe enqueue failed");
    },
  });

  const easyImport = useMutation({
    mutationFn: (values: EasyProxiesImportFormValues) =>
      apiJson<EasyProxiesImportResponse>("/admin/api/proxies/easy-proxies/import", {
        method: "POST",
        body: JSON.stringify(values),
      }),
    onMutate: () => {
      setEasyErrorMessage(null);
      setEasyRequestId(null);
      setEasyResult(null);
    },
    onSuccess: (data) => {
      setEasyResult(data);
      setEasyRequestId(data.request_id);
      easyForm.setFieldValue("password", "");
      qc.invalidateQueries({ queryKey: ["admin", "proxies", "endpoints"] });
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setEasyErrorMessage(err.message);
        setEasyRequestId(requestIdFromError(err));
        return;
      }
      if (err instanceof Error) {
        setEasyErrorMessage(err.message);
        return;
      }
      setEasyErrorMessage("easy_proxies import failed");
    },
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Proxies
      </Typography.Title>

      <Card title="Import (manual)">
        {manualErrorMessage ? <Alert type="error" showIcon message={manualErrorMessage} /> : null}
        {manualRequestId ? <Typography.Text type="secondary">request_id: {manualRequestId}</Typography.Text> : null}

        <Form<ManualImportFormValues>
          form={manualForm}
          layout="vertical"
          initialValues={{ source: "manual", conflict_policy: "overwrite", text: "" }}
          onFinish={(v) => manualImport.mutate(v)}
        >
          <Form.Item
            label="Text (one URI per line)"
            name="text"
            rules={[{ required: true, message: "text is required" }]}
          >
            <Input.TextArea rows={6} placeholder="http://user:pass@1.2.3.4:8080" />
          </Form.Item>
          <Space wrap>
            <Form.Item label="Source" name="source">
              <Select options={[{ value: "manual", label: "manual" }]} style={{ minWidth: 160 }} />
            </Form.Item>
            <Form.Item label="Conflict policy" name="conflict_policy">
              <Select
                options={[
                  { value: "overwrite", label: "overwrite" },
                  { value: "skip", label: "skip" },
                ]}
                style={{ minWidth: 220 }}
              />
            </Form.Item>
          </Space>
          <Button type="primary" htmlType="submit" loading={manualImport.isPending}>
            导入
          </Button>
        </Form>
        {manualImport.isPending ? <Alert type="info" showIcon message="Importing..." style={{ marginTop: 12 }} /> : null}
        {manualResult ? (
          <Alert
            type="success"
            showIcon
            message="Imported"
            description={`created: ${manualResult.created}, updated: ${manualResult.updated}, skipped: ${manualResult.skipped}, errors: ${manualResult.errors.length}`}
            style={{ marginTop: 12 }}
          />
        ) : null}
        <Alert
          type="info"
          showIcon
          message="Security"
          description="Proxy passwords are write-only: stored encrypted and never displayed; list shows masked URIs."
          style={{ marginTop: 12 }}
        />
      </Card>

      <Card title="easy_proxies">
        {easyErrorMessage ? <Alert type="error" showIcon message={easyErrorMessage} /> : null}
        {easyRequestId ? <Typography.Text type="secondary">request_id: {easyRequestId}</Typography.Text> : null}

        <Form<EasyProxiesImportFormValues>
          form={easyForm}
          layout="vertical"
          initialValues={{ base_url: "", password: "", conflict_policy: "skip_non_easy_proxies" }}
          onFinish={(v) => easyImport.mutate(v)}
        >
          <Form.Item label="Base URL" name="base_url" rules={[{ required: true, message: "base_url is required" }]}>
            <Input placeholder="http://easy-proxies:9090" />
          </Form.Item>
          <Form.Item label="Password" name="password" rules={[{ required: true, message: "password is required" }]}>
            <Input.Password placeholder="required" />
          </Form.Item>
          <Form.Item label="Conflict policy" name="conflict_policy">
            <Select
              options={[
                { value: "overwrite", label: "overwrite" },
                { value: "skip_non_easy_proxies", label: "skip_non_easy_proxies" },
              ]}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={easyImport.isPending}>
            从 easy_proxies 导入
          </Button>
        </Form>
        {easyImport.isPending ? <Alert type="info" showIcon message="Importing from easy_proxies..." style={{ marginTop: 12 }} /> : null}
        {easyResult ? (
          <Alert
            type="success"
            showIcon
            message="easy_proxies imported"
            description={`created: ${easyResult.created}, updated: ${easyResult.updated}, skipped: ${easyResult.skipped}, errors: ${easyResult.errors.length}`}
            style={{ marginTop: 12 }}
          />
        ) : null}
      </Card>

      <Card title="Endpoints">
        <Space wrap style={{ marginBottom: 12 }}>
          <Button type="primary" onClick={() => probe.mutate()} loading={probe.isPending}>
            探测健康（入队）
          </Button>
          <Button onClick={() => q.refetch()} loading={q.isFetching}>
            刷新列表
          </Button>
        </Space>
        {probe.isPending ? <Alert type="info" showIcon message="Enqueueing probe job..." style={{ marginBottom: 12 }} /> : null}
        {probeErrorMessage ? <Alert type="error" showIcon message={probeErrorMessage} style={{ marginBottom: 12 }} /> : null}
        {probeJobId ? (
          <Alert
            type="success"
            showIcon
            message="probe enqueued"
            description={`job_id: ${probeJobId}`}
            style={{ marginBottom: 12 }}
          />
        ) : null}
        {probeRequestId ? <Typography.Text type="secondary">request_id: {probeRequestId}</Typography.Text> : null}

        {q.isLoading ? (
          <Skeleton active />
        ) : q.isError ? (
          <Alert
            type="error"
            showIcon
            message="Failed to load proxy endpoints"
            description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
          />
        ) : !q.data ? (
          <Skeleton active />
        ) : q.data.items.length === 0 ? (
          <Alert type="info" showIcon message="No endpoints" description="Import proxy endpoints to enable proxy routing." />
        ) : (
          <>
            <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
            <Table<ProxyEndpointItem>
              rowKey={(r) => r.id}
              columns={columns}
              dataSource={q.data.items}
              pagination={false}
              size="small"
              scroll={{ x: 1400 }}
              style={{ marginTop: 12 }}
            />
          </>
        )}
      </Card>
    </Space>
  );
}
