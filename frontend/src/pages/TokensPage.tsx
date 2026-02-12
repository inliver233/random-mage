import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Skeleton, Space, Switch, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import React from "react";

import { ApiError, apiJson } from "../api/client";

type TokenItem = {
  id: string;
  label: string | null;
  enabled: boolean;
  refresh_token_masked: string | null;
  weight: number | null;
  error_count: number | null;
  backoff_until: string | null;
  last_ok_at: string | null;
  last_fail_at: string | null;
};

type TokensListResponse = {
  ok: true;
  items: TokenItem[];
  request_id: string;
};

type CreateTokenFormValues = {
  label: string;
  refresh_token: string;
  enabled: boolean;
  weight: number;
};

type CreateTokenResponse = {
  ok: true;
  token_id: string;
  request_id: string;
};

type TestRefreshResponse = {
  ok: true;
  expires_in: number;
  user_id: string | null;
  request_id: string;
};

type ResetFailuresResponse = {
  ok: true;
  token_id: string;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

function messageFromError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Unknown error";
}

const columns = (actions: {
  onTestRefresh: (id: string) => void;
  onResetFailures: (id: string) => void;
  testPendingId: string | null;
  resetPendingId: string | null;
}): ColumnsType<TokenItem> => [
  { title: "Label", dataIndex: "label", key: "label" },
  { title: "Enabled", dataIndex: "enabled", key: "enabled", render: (v) => String(Boolean(v)) },
  { title: "Masked", dataIndex: "refresh_token_masked", key: "refresh_token_masked" },
  { title: "Weight", dataIndex: "weight", key: "weight" },
  { title: "Errors", dataIndex: "error_count", key: "error_count" },
  { title: "Backoff", dataIndex: "backoff_until", key: "backoff_until" },
  { title: "Last OK", dataIndex: "last_ok_at", key: "last_ok_at" },
  { title: "Last Fail", dataIndex: "last_fail_at", key: "last_fail_at" },
  {
    title: "Actions",
    key: "actions",
    render: (_, r) => (
      <Space wrap>
        <Button
          size="small"
          onClick={() => actions.onTestRefresh(r.id)}
          loading={actions.testPendingId === r.id}
        >
          测试刷新
        </Button>
        <Button
          size="small"
          onClick={() => actions.onResetFailures(r.id)}
          loading={actions.resetPendingId === r.id}
        >
          重置失败退避
        </Button>
      </Space>
    ),
  },
];

export function TokensPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = React.useState(false);
  const [createForm] = Form.useForm<CreateTokenFormValues>();

  const [actionMessage, setActionMessage] = React.useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = React.useState<string | null>(null);
  const [actionErrorMessage, setActionErrorMessage] = React.useState<string | null>(null);
  const [actionErrorRequestId, setActionErrorRequestId] = React.useState<string | null>(null);

  const q = useQuery({
    queryKey: ["admin", "tokens"],
    queryFn: () => apiJson<TokensListResponse>("/admin/api/tokens"),
  });

  const createToken = useMutation({
    mutationFn: (values: CreateTokenFormValues) =>
      apiJson<CreateTokenResponse>("/admin/api/tokens", {
        method: "POST",
        body: JSON.stringify({
          label: values.label || null,
          refresh_token: values.refresh_token,
          enabled: Boolean(values.enabled),
          weight: values.weight,
        }),
      }),
    onMutate: () => {
      setActionMessage(null);
      setActionRequestId(null);
      setActionErrorMessage(null);
      setActionErrorRequestId(null);
    },
    onSuccess: (data) => {
      setCreateOpen(false);
      setActionMessage(`Token created: ${data.token_id}`);
      setActionRequestId(data.request_id);
      createForm.resetFields();
      qc.invalidateQueries({ queryKey: ["admin", "tokens"] });
    },
    onError: (err) => {
      setActionErrorMessage(messageFromError(err));
      setActionErrorRequestId(requestIdFromError(err));
    },
  });

  const testRefresh = useMutation({
    mutationFn: (tokenId: string) =>
      apiJson<TestRefreshResponse>(`/admin/api/tokens/${encodeURIComponent(tokenId)}/test-refresh`, { method: "POST" }),
    onMutate: () => {
      setActionMessage(null);
      setActionRequestId(null);
      setActionErrorMessage(null);
      setActionErrorRequestId(null);
    },
    onSuccess: (data) => {
      setActionMessage(`Token refresh OK (expires_in=${data.expires_in})`);
      setActionRequestId(data.request_id);
      qc.invalidateQueries({ queryKey: ["admin", "tokens"] });
    },
    onError: (err) => {
      setActionErrorMessage(messageFromError(err));
      setActionErrorRequestId(requestIdFromError(err));
      qc.invalidateQueries({ queryKey: ["admin", "tokens"] });
    },
  });

  const resetFailures = useMutation({
    mutationFn: (tokenId: string) =>
      apiJson<ResetFailuresResponse>(`/admin/api/tokens/${encodeURIComponent(tokenId)}/reset-failures`, { method: "POST" }),
    onMutate: () => {
      setActionMessage(null);
      setActionRequestId(null);
      setActionErrorMessage(null);
      setActionErrorRequestId(null);
    },
    onSuccess: (data) => {
      setActionMessage(`Token failures reset: ${data.token_id}`);
      setActionRequestId(data.request_id);
      qc.invalidateQueries({ queryKey: ["admin", "tokens"] });
    },
    onError: (err) => {
      setActionErrorMessage(messageFromError(err));
      setActionErrorRequestId(requestIdFromError(err));
    },
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Tokens
      </Typography.Title>

      {actionMessage ? <Alert type="success" showIcon message={actionMessage} /> : null}
      {actionRequestId ? <Typography.Text type="secondary">request_id: {actionRequestId}</Typography.Text> : null}
      {actionErrorMessage ? <Alert type="error" showIcon message={actionErrorMessage} /> : null}
      {actionErrorRequestId ? <Typography.Text type="secondary">request_id: {actionErrorRequestId}</Typography.Text> : null}

      <Space wrap>
        <Button type="primary" onClick={() => setCreateOpen(true)}>
          新增 Token
        </Button>
      </Space>

      <Modal
        title="新增 Token"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        footer={null}
        destroyOnClose
      >
        <Form<CreateTokenFormValues>
          form={createForm}
          layout="vertical"
          initialValues={{ label: "", refresh_token: "", enabled: true, weight: 1.0 }}
          onFinish={(v) => createToken.mutate(v)}
        >
          <Form.Item label="Label" name="label">
            <Input placeholder="acc1 (optional)" />
          </Form.Item>
          <Form.Item
            label="Refresh token"
            name="refresh_token"
            rules={[{ required: true, message: "refresh token is required" }]}
          >
            <Input.Password placeholder="required" />
          </Form.Item>
          <Form.Item label="Enabled" name="enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="Weight" name="weight" rules={[{ required: true, message: "weight is required" }]}>
            <InputNumber min={0} max={100} step={0.1} style={{ width: 180 }} />
          </Form.Item>
          <Alert
            type="info"
            showIcon
            message="Security"
            description="refresh_token is write-only: it will never be displayed again after saving."
          />

          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button
              onClick={() => {
                setCreateOpen(false);
                createForm.resetFields();
              }}
              disabled={createToken.isPending}
            >
              取消
            </Button>
            <Button type="primary" htmlType="submit" loading={createToken.isPending}>
              创建
            </Button>
          </Space>
        </Form>
      </Modal>

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
        <Alert
          type="error"
          showIcon
          message="Failed to load tokens"
          description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
        />
      ) : !q.data ? (
        <Skeleton active />
      ) : q.data.items.length === 0 ? (
        <Alert type="info" showIcon message="No tokens" description="Add at least one token to enable Pixiv API jobs." />
      ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
          <Table<TokenItem>
            rowKey={(r) => r.id}
            columns={columns({
              onTestRefresh: (id) => testRefresh.mutate(id),
              onResetFailures: (id) => resetFailures.mutate(id),
              testPendingId: testRefresh.isPending ? testRefresh.variables ?? null : null,
              resetPendingId: resetFailures.isPending ? resetFailures.variables ?? null : null,
            })}
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
