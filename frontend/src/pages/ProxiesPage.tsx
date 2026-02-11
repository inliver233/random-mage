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
};

type ProxiesEndpointsResponse = {
  ok: true;
  items: ProxyEndpointItem[];
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

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

const columns: ColumnsType<ProxyEndpointItem> = [
  { title: "ID", dataIndex: "id", key: "id" },
  { title: "URI", dataIndex: "uri_masked", key: "uri_masked" },
  { title: "Enabled", dataIndex: "enabled", key: "enabled", render: (v) => String(Boolean(v)) },
  { title: "Status", dataIndex: "status", key: "status" },
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

  const [easyErrorMessage, setEasyErrorMessage] = useState<string | null>(null);
  const [easyRequestId, setEasyRequestId] = useState<string | null>(null);
  const [easyResult, setEasyResult] = useState<EasyProxiesImportResponse | null>(null);
  const [easyForm] = Form.useForm<EasyProxiesImportFormValues>();

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
        <Form layout="vertical" initialValues={{ source: "manual", conflict_policy: "overwrite", text: "" }}>
          <Form.Item label="Text (one URI per line)" name="text">
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
                  { value: "skip_non_source", label: "skip_non_source" },
                  { value: "skip_non_manual", label: "skip_non_manual" },
                  { value: "skip_non_easy_proxies", label: "skip_non_easy_proxies" },
                ]}
                style={{ minWidth: 220 }}
              />
            </Form.Item>
          </Space>
          <Button type="primary" disabled>
            导入
          </Button>
        </Form>
        <Alert type="info" showIcon message="TODO" description="Import wiring pending (see UI action issues)." style={{ marginTop: 12 }} />
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
          <Button disabled>探测健康（入队）</Button>
          <Button disabled>刷新代理</Button>
        </Space>

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
              style={{ marginTop: 12 }}
            />
          </>
        )}
      </Card>
    </Space>
  );
}
