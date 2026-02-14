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
  { title: "节点ID", dataIndex: "id", key: "id" },
  { title: "代理地址（掩码）", dataIndex: "uri_masked", key: "uri_masked" },
  { title: "启用", dataIndex: "enabled", key: "enabled", render: (value) => (value ? "是" : "否") },
  {
    title: "状态",
    dataIndex: "status",
    key: "status",
    render: (value: string | null) => {
      const normalized = String(value || "").trim().toLowerCase();
      if (!normalized) return "-";
      if (normalized === "ok") return "正常";
      if (normalized === "fail" || normalized === "failed") return "异常";
      if (normalized === "timeout") return "超时";
      return value;
    },
  },
  {
    title: "所属代理池",
    key: "pools",
    render: (_, row) =>
      (row.pools || []).length
        ? (row.pools || [])
            .map((pool) => `${pool.name}(#${pool.id}) 权重=${pool.weight} ${pool.pool_enabled && pool.member_enabled ? "启用" : "停用"}`)
            .join("，")
        : "-",
  },
  {
    title: "绑定统计",
    key: "bindings",
    render: (_, row) =>
      row.bindings ? `主绑定=${row.bindings.primary_count}，覆盖绑定=${row.bindings.override_count}` : "-",
  },
  { title: "成功/失败", key: "ok_fail", render: (_, row) => `${row.success_count}/${row.failure_count}` },
  { title: "最近成功", dataIndex: "last_ok_at", key: "last_ok_at", render: (value) => value || "-" },
  { title: "最近失败", dataIndex: "last_fail_at", key: "last_fail_at", render: (value) => value || "-" },
  { title: "延迟(ms)", dataIndex: "latency_ms", key: "latency_ms" },
  { title: "黑名单至", dataIndex: "blacklisted_until", key: "blacklisted_until" },
  { title: "最后错误", dataIndex: "last_error", key: "last_error" },
];

export function ProxiesPage() {
  const queryClient = useQueryClient();

  const query = useQuery({
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
      queryClient.invalidateQueries({ queryKey: ["admin", "proxies", "endpoints"] });
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
      setManualErrorMessage("手动导入失败");
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
      setProbeRequestId(data.request_id);
      setProbeJobId(data.job_id);
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
      setProbeErrorMessage("探测任务入队失败");
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
      queryClient.invalidateQueries({ queryKey: ["admin", "proxies", "endpoints"] });
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
      setEasyErrorMessage("从 easy-proxies 导入失败");
    },
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        代理管理
      </Typography.Title>

      <Card title="手动导入代理节点">
        {manualErrorMessage ? <Alert type="error" showIcon message={manualErrorMessage} /> : null}
        {manualRequestId ? <Typography.Text type="secondary">请求ID: {manualRequestId}</Typography.Text> : null}

        <Form<ManualImportFormValues>
          form={manualForm}
          layout="vertical"
          initialValues={{ text: "", source: "manual", conflict_policy: "overwrite" }}
          onFinish={(values) => manualImport.mutate(values)}
        >
          <Form.Item label="代理地址（每行一个）" name="text" rules={[{ required: true, message: "请输入代理地址" }]}>
            <Input.TextArea rows={6} placeholder="http://user:pass@1.2.3.4:8080" />
          </Form.Item>
          <Form.Item label="冲突策略" name="conflict_policy">
            <Select
              options={[
                { value: "overwrite", label: "覆盖同地址节点" },
                { value: "skip", label: "跳过同地址节点" },
              ]}
              style={{ minWidth: 220 }}
            />
          </Form.Item>

          <Button type="primary" htmlType="submit" loading={manualImport.isPending}>
            导入
          </Button>
        </Form>

        {manualImport.isPending ? <Alert type="info" showIcon message="正在导入代理节点..." style={{ marginTop: 12 }} /> : null}
        {manualResult ? (
          <Alert
            type="success"
            showIcon
            message="手动导入完成"
            description={`新增: ${manualResult.created}，更新: ${manualResult.updated}，跳过: ${manualResult.skipped}，错误: ${manualResult.errors.length}`}
            style={{ marginTop: 12 }}
          />
        ) : null}

        <Alert
          type="info"
          showIcon
          message="安全说明"
          description="代理密码仅写入不回显，列表中只显示脱敏后的地址。"
          style={{ marginTop: 12 }}
        />
      </Card>

      <Card title="从外部代理服务导入">
        {easyErrorMessage ? <Alert type="error" showIcon message={easyErrorMessage} /> : null}
        {easyRequestId ? <Typography.Text type="secondary">请求ID: {easyRequestId}</Typography.Text> : null}

        <Form<EasyProxiesImportFormValues>
          form={easyForm}
          layout="vertical"
          initialValues={{ base_url: "", password: "", conflict_policy: "skip_non_easy_proxies" }}
          onFinish={(values) => easyImport.mutate(values)}
        >
          <Form.Item label="服务地址" name="base_url" rules={[{ required: true, message: "请输入 easy-proxies 地址" }]}>
            <Input placeholder="http://easy-proxies:9090" />
          </Form.Item>
          <Form.Item label="访问密码" name="password" rules={[{ required: true, message: "请输入访问密码" }]}>
            <Input.Password placeholder="必填" />
          </Form.Item>
          <Form.Item label="冲突策略" name="conflict_policy">
            <Select
              options={[
                { value: "overwrite", label: "覆盖同地址节点" },
                { value: "skip_non_easy_proxies", label: "仅覆盖 easy-proxies 导入的节点" },
              ]}
            />
          </Form.Item>

          <Button type="primary" htmlType="submit" loading={easyImport.isPending}>
            开始导入
          </Button>
        </Form>

        {easyImport.isPending ? <Alert type="info" showIcon message="正在从外部代理服务导入..." style={{ marginTop: 12 }} /> : null}
        {easyResult ? (
          <Alert
            type="success"
            showIcon
            message="外部代理服务导入完成"
            description={`新增: ${easyResult.created}，更新: ${easyResult.updated}，跳过: ${easyResult.skipped}，错误: ${easyResult.errors.length}`}
            style={{ marginTop: 12 }}
          />
        ) : null}
      </Card>

      <Card title="代理节点列表">
        <Space wrap style={{ marginBottom: 12 }}>
          <Button type="primary" onClick={() => probe.mutate()} loading={probe.isPending}>
            启动健康探测任务
          </Button>
          <Button onClick={() => query.refetch()} loading={query.isFetching}>
            刷新列表
          </Button>
        </Space>

        {probe.isPending ? <Alert type="info" showIcon message="探测任务入队中..." style={{ marginBottom: 12 }} /> : null}
        {probeErrorMessage ? <Alert type="error" showIcon message={probeErrorMessage} style={{ marginBottom: 12 }} /> : null}
        {probeJobId ? (
          <Alert
            type="success"
            showIcon
            message="探测任务已入队"
            description={`任务ID: ${probeJobId}`}
            style={{ marginBottom: 12 }}
          />
        ) : null}
        {probeRequestId ? <Typography.Text type="secondary">请求ID: {probeRequestId}</Typography.Text> : null}

        {query.isLoading ? (
          <Skeleton active />
        ) : query.isError ? (
          <Alert
            type="error"
            showIcon
            message="加载代理节点失败"
            description={requestIdFromError(query.error) ? `请求ID: ${requestIdFromError(query.error)}` : ""}
          />
        ) : !query.data ? (
          <Skeleton active />
        ) : query.data.items.length === 0 ? (
          <Alert type="info" showIcon message="暂无代理节点" description="请先导入代理节点以启用代理路由。" />
        ) : (
          <>
            <Typography.Text type="secondary">请求ID: {query.data.request_id}</Typography.Text>
            <Table<ProxyEndpointItem>
              rowKey={(row) => row.id}
              columns={columns}
              dataSource={query.data.items}
              pagination={false}
              size="small"
              scroll={{ x: 1500 }}
              style={{ marginTop: 12 }}
            />
          </>
        )}
      </Card>
    </Space>
  );
}
