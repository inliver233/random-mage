import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Form, InputNumber, Select, Skeleton, Space, Switch, Typography } from "antd";
import React, { useEffect, useState } from "react";

import { ApiError, apiJson } from "../api/client";

type SettingsResponse = {
  ok: true;
  settings: Record<string, unknown>;
  request_id: string;
};

type SettingsUpdateResponse = {
  ok: true;
  updated: number;
  request_id: string;
};

type SettingsFormValues = {
  proxy_enabled: boolean;
  proxy_fail_closed: boolean;
  proxy_route_mode: "pixiv_only" | "all" | "allowlist" | "off";
  proxy_allowlist_domains: string[];
  proxy_default_pool_id: number;
  random_default_attempts: number;
  random_default_r18_strict: boolean;
  random_fail_cooldown_ms: number;
  security_hide_origin_url_in_public_json: boolean;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

function asObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function asBool(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number" && (value === 0 || value === 1)) return Boolean(value);
  if (typeof value === "string") {
    const v = value.trim().toLowerCase();
    if (v === "true" || v === "1" || v === "yes" || v === "on") return true;
    if (v === "false" || v === "0" || v === "no" || v === "off") return false;
  }
  return fallback;
}

function asInt(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  if (typeof value === "string") {
    const n = Number.parseInt(value.trim(), 10);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

function asStrList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item !== "string") continue;
    const v = item.trim();
    if (!v || v.length > 200 || seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

export function SettingsPage() {
  const qc = useQueryClient();
  const [form] = Form.useForm<SettingsFormValues>();
  const q = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => apiJson<SettingsResponse>("/admin/api/settings"),
  });

  const [saveErrorMessage, setSaveErrorMessage] = useState<string | null>(null);
  const [saveRequestId, setSaveRequestId] = useState<string | null>(null);
  const [saveUpdated, setSaveUpdated] = useState<number | null>(null);

  useEffect(() => {
    if (!q.data) return;
    const settings = asObject(q.data.settings);
    const proxy = asObject(settings.proxy);
    const random = asObject(settings.random);
    const security = asObject(settings.security);

    const routeModeRaw = String(proxy.route_mode || "pixiv_only").trim().toLowerCase();
    const route_mode: SettingsFormValues["proxy_route_mode"] =
      routeModeRaw === "all" || routeModeRaw === "allowlist" || routeModeRaw === "off" ? routeModeRaw : "pixiv_only";

    form.setFieldsValue({
      proxy_enabled: asBool(proxy.enabled, false),
      proxy_fail_closed: asBool(proxy.fail_closed, false),
      proxy_route_mode: route_mode,
      proxy_allowlist_domains: asStrList(proxy.allowlist_domains),
      proxy_default_pool_id: asInt(proxy.default_pool_id, 0),
      random_default_attempts: asInt(random.default_attempts, 3),
      random_default_r18_strict: asBool(random.default_r18_strict, true),
      random_fail_cooldown_ms: asInt(random.fail_cooldown_ms, 600_000),
      security_hide_origin_url_in_public_json: asBool(security.hide_origin_url_in_public_json, true),
    });
  }, [form, q.data]);

  const save = useMutation({
    mutationFn: (values: SettingsFormValues) =>
      apiJson<SettingsUpdateResponse>("/admin/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          settings: {
            proxy: {
              enabled: values.proxy_enabled,
              fail_closed: values.proxy_fail_closed,
              route_mode: values.proxy_route_mode,
              allowlist_domains: values.proxy_allowlist_domains,
              default_pool_id: values.proxy_default_pool_id > 0 ? values.proxy_default_pool_id : "",
            },
            random: {
              default_attempts: values.random_default_attempts,
              default_r18_strict: values.random_default_r18_strict,
              fail_cooldown_ms: values.random_fail_cooldown_ms,
            },
            security: { hide_origin_url_in_public_json: values.security_hide_origin_url_in_public_json },
          },
        }),
      }),
    onMutate: () => {
      setSaveErrorMessage(null);
      setSaveRequestId(null);
      setSaveUpdated(null);
    },
    onSuccess: (data) => {
      setSaveUpdated(data.updated);
      setSaveRequestId(data.request_id);
      qc.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setSaveErrorMessage(err.message);
        setSaveRequestId(requestIdFromError(err));
        return;
      }
      if (err instanceof Error) {
        setSaveErrorMessage(err.message);
        return;
      }
      setSaveErrorMessage("Save failed");
    },
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Settings
      </Typography.Title>

      <Space wrap>
        <Button type="primary" onClick={() => form.submit()} loading={save.isPending} disabled={!q.data || q.isError || q.isLoading}>
          保存
        </Button>
      </Space>

      {save.isPending ? <Alert type="info" showIcon message="Saving..." /> : null}
      {saveErrorMessage ? <Alert type="error" showIcon message={saveErrorMessage} /> : null}
      {saveUpdated !== null ? <Alert type="success" showIcon message="Saved" description={`updated: ${saveUpdated}`} /> : null}
      {saveRequestId ? <Typography.Text type="secondary">request_id: {saveRequestId}</Typography.Text> : null}

      {q.isLoading ? (
        <Skeleton active />
      ) : q.isError ? (
          <Alert
            type="error"
            showIcon
            message="Failed to load settings"
            description={requestIdFromError(q.error) ? `request_id: ${requestIdFromError(q.error)}` : ""}
          />
        ) : !q.data ? (
          <Skeleton active />
        ) : (
        <Card>
          <Typography.Text type="secondary">request_id: {q.data.request_id}</Typography.Text>
          <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
            <Typography.Title level={5} style={{ marginTop: 12 }}>
              Proxy
            </Typography.Title>
            <Form.Item label="Enabled" name="proxy_enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="Fail closed" name="proxy_fail_closed" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="Route mode" name="proxy_route_mode">
              <Select
                options={[
                  { value: "pixiv_only", label: "pixiv_only" },
                  { value: "all", label: "all" },
                  { value: "allowlist", label: "allowlist" },
                  { value: "off", label: "off" },
                ]}
                style={{ maxWidth: 320 }}
              />
            </Form.Item>
            <Form.Item label="Allowlist domains" name="proxy_allowlist_domains">
              <Select mode="tags" style={{ maxWidth: 520 }} tokenSeparators={[",", "\n", " "]} placeholder="example.com api.example.com" />
            </Form.Item>
            <Form.Item label="Default pool id (0 = none)" name="proxy_default_pool_id">
              <InputNumber min={0} max={1_000_000} style={{ width: 240 }} />
            </Form.Item>

            <Typography.Title level={5} style={{ marginTop: 12 }}>
              Random
            </Typography.Title>
            <Form.Item label="Default attempts" name="random_default_attempts">
              <InputNumber min={0} max={1000} style={{ width: 200 }} />
            </Form.Item>
            <Form.Item label="Default r18 strict" name="random_default_r18_strict" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="Fail cooldown (ms)" name="random_fail_cooldown_ms">
              <InputNumber min={0} max={10_000_000} style={{ width: 240 }} />
            </Form.Item>

            <Typography.Title level={5} style={{ marginTop: 12 }}>
              Security
            </Typography.Title>
            <Form.Item label="Hide origin URL in public JSON" name="security_hide_origin_url_in_public_json" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Form>
        </Card>
      )}
    </Space>
  );
}
