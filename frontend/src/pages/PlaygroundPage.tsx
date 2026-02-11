import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Select, Skeleton, Space, Switch, Typography } from "antd";
import React, { useEffect } from "react";

import { ApiError, type ApiErrorBody, apiFetch, apiJson } from "../api/client";

type PlaygroundFormValues = {
  format: "image" | "json" | "redirect";
  attempts: number;
  seed: string;
  r18: 0 | 1 | 2;
  r18_strict: boolean;
  orientation: "any" | "portrait" | "landscape" | "square";
  min_width: number | null;
  min_height: number | null;
  min_pixels: number | null;
  included_tags: string;
  excluded_tags: string;
  user_id: number | null;
  illust_id: number | null;
  ai_type: "any" | "0" | "1";
  created_from: string;
  created_to: string;
};

type RandomJsonResponse = {
  ok: true;
  request_id: string;
  data: { urls?: { proxy?: string } };
};

type PlaygroundResult =
  | { kind: "json"; url: string; request_id: string; payload: RandomJsonResponse }
  | { kind: "image"; url: string; request_id: string | null; src: string; headers: Record<string, string> }
  | { kind: "redirect"; url: string; request_id: string | null; location: string | null; note: string | null };

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

function buildRandomUrl(values: PlaygroundFormValues): string {
  const sp = new URLSearchParams();

  sp.set("attempts", String(values.attempts));
  if (values.seed.trim()) sp.set("seed", values.seed.trim());

  sp.set("r18", String(values.r18));
  sp.set("r18_strict", values.r18_strict ? "1" : "0");
  if (values.orientation !== "any") sp.set("orientation", values.orientation);

  if (values.min_width != null) sp.set("min_width", String(values.min_width));
  if (values.min_height != null) sp.set("min_height", String(values.min_height));
  if (values.min_pixels != null) sp.set("min_pixels", String(values.min_pixels));

  if (values.included_tags.trim()) sp.set("included_tags", values.included_tags.trim());
  if (values.excluded_tags.trim()) sp.set("excluded_tags", values.excluded_tags.trim());

  if (values.user_id != null) sp.set("user_id", String(values.user_id));
  if (values.illust_id != null) sp.set("illust_id", String(values.illust_id));

  if (values.ai_type !== "any") sp.set("ai_type", values.ai_type);
  if (values.created_from.trim()) sp.set("created_from", values.created_from.trim());
  if (values.created_to.trim()) sp.set("created_to", values.created_to.trim());

  if (values.format === "redirect") {
    sp.set("redirect", "1");
    sp.set("format", "image");
  } else {
    sp.set("format", values.format);
  }

  const qs = sp.toString();
  return qs ? `/random?${qs}` : "/random";
}

function pickHeaders(headers: Headers, keys: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const key of keys) {
    const v = headers.get(key);
    if (v) out[key] = v;
  }
  return out;
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    v.ok === false &&
    typeof v.code === "string" &&
    typeof v.message === "string" &&
    typeof v.request_id === "string" &&
    !!v.details &&
    typeof v.details === "object"
  );
}

async function parseApiErrorFromResponse(resp: Response): Promise<ApiError> {
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.toLowerCase().includes("application/json")) {
    try {
      const raw = (await resp.json()) as unknown;
      const body = isApiErrorBody(raw) ? raw : null;
      const message = body?.message?.trim() ? body.message : `HTTP ${resp.status}`;
      return new ApiError(message, { status: resp.status, body });
    } catch {
      // fall through
    }
  }
  return new ApiError(`HTTP ${resp.status}`, { status: resp.status });
}

async function fetchPlayground(values: PlaygroundFormValues): Promise<PlaygroundResult> {
  const url = buildRandomUrl(values);

  if (values.format === "json") {
    const payload = await apiJson<RandomJsonResponse>(url);
    return { kind: "json", url, request_id: payload.request_id, payload };
  }

  if (values.format === "image") {
    const resp = await apiFetch(url, { method: "GET" });
    const reqId = resp.headers.get("x-request-id") || resp.headers.get("x-request_id") || null;
    if (!resp.ok) throw await parseApiErrorFromResponse(resp);

    const blob = await resp.blob();
    if (!("createObjectURL" in URL)) {
      throw new Error("Browser does not support URL.createObjectURL");
    }
    const src = URL.createObjectURL(blob);
    const headers = pickHeaders(resp.headers, [
      "content-type",
      "cache-control",
      "content-disposition",
      "x-origin-url",
      "x-request-id",
    ]);

    return { kind: "image", url, request_id: reqId, src, headers };
  }

  const resp = await apiFetch(url, { method: "GET", redirect: "manual" });
  const reqId = resp.headers.get("x-request-id") || resp.headers.get("x-request_id") || null;
  const location = resp.headers.get("location");
  if (location) return { kind: "redirect", url, request_id: reqId, location, note: null };

  const fallbackUrl = url.replace(/[?&]redirect=1(&|$)/, "$1");
  const payload = await apiJson<RandomJsonResponse>(fallbackUrl.replace(/([?&])format=image(&|$)/, "$1format=json$2"));
  const proxy = payload.data?.urls?.proxy || null;
  return {
    kind: "redirect",
    url,
    request_id: reqId ?? payload.request_id,
    location: proxy,
    note: proxy ? "Location header not available; showing proxy URL from JSON." : "Location header not available.",
  };
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const el = document.createElement("textarea");
  el.value = text;
  el.setAttribute("readonly", "");
  el.style.position = "fixed";
  el.style.left = "-9999px";
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
}

export function PlaygroundPage() {
  const [form] = Form.useForm<PlaygroundFormValues>();

  const m = useMutation({ mutationFn: fetchPlayground });

  useEffect(() => {
    if (m.data?.kind !== "image") return;
    const src = m.data.src;
    return () => {
      URL.revokeObjectURL(src);
    };
  }, [m.data]);

  const url = m.data?.url || null;

  const onCopyUrl = async () => {
    if (!url) return;
    await copyText(url);
  };

  const onCopyCurl = async () => {
    if (!url) return;
    await copyText(`curl -i ${JSON.stringify(url)}`);
  };

  const onOpen = () => {
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Random Playground
      </Typography.Title>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="Filters">
            <Form<PlaygroundFormValues>
              form={form}
              layout="vertical"
              initialValues={{
                format: "json",
                attempts: 3,
                seed: "",
                r18: 0,
                r18_strict: true,
                orientation: "any",
                min_width: null,
                min_height: null,
                min_pixels: null,
                included_tags: "",
                excluded_tags: "",
                user_id: null,
                illust_id: null,
                ai_type: "any",
                created_from: "",
                created_to: "",
              }}
              onFinish={(v) => m.mutate(v)}
            >
              <Form.Item label="Format" name="format">
                <Select
                  options={[
                    { value: "image", label: "image" },
                    { value: "json", label: "json" },
                    { value: "redirect", label: "redirect" },
                  ]}
                />
              </Form.Item>

              <Form.Item label="Attempts" name="attempts">
                <InputNumber min={1} max={10} style={{ width: "100%" }} />
              </Form.Item>

              <Form.Item label="Seed" name="seed">
                <Input placeholder="optional" />
              </Form.Item>

              <Form.Item label="R18" name="r18">
                <Select
                  options={[
                    { value: 0, label: "0" },
                    { value: 1, label: "1" },
                    { value: 2, label: "2" },
                  ]}
                />
              </Form.Item>

              <Form.Item label="R18 strict" name="r18_strict" valuePropName="checked">
                <Switch />
              </Form.Item>

              <Form.Item label="Orientation" name="orientation">
                <Select
                  options={[
                    { value: "any", label: "any" },
                    { value: "portrait", label: "portrait" },
                    { value: "landscape", label: "landscape" },
                    { value: "square", label: "square" },
                  ]}
                />
              </Form.Item>

              <Form.Item label="Min width" name="min_width">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item label="Min height" name="min_height">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item label="Min pixels" name="min_pixels">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>

              <Form.Item label="Included tags (use |)" name="included_tags">
                <Input placeholder="tag1|tag2" />
              </Form.Item>
              <Form.Item label="Excluded tags (use |)" name="excluded_tags">
                <Input placeholder="tag1|tag2" />
              </Form.Item>

              <Form.Item label="User ID" name="user_id">
                <InputNumber min={1} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item label="Illust ID" name="illust_id">
                <InputNumber min={1} style={{ width: "100%" }} />
              </Form.Item>

              <Form.Item label="AI type" name="ai_type">
                <Select
                  options={[
                    { value: "any", label: "any" },
                    { value: "0", label: "0" },
                    { value: "1", label: "1" },
                  ]}
                />
              </Form.Item>

              <Form.Item label="Created from (ISO)" name="created_from">
                <Input placeholder="2024-01-01T00:00:00Z" />
              </Form.Item>
              <Form.Item label="Created to (ISO)" name="created_to">
                <Input placeholder="2024-12-31T23:59:59Z" />
              </Form.Item>

              <Button type="primary" htmlType="submit" loading={m.isPending} style={{ width: "100%" }}>
                Run
              </Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="Result">
            {m.isPending ? (
              <Skeleton active />
            ) : m.isError ? (
              <Alert
                type="error"
                showIcon
                message={m.error instanceof Error ? m.error.message : "Failed to run"}
                description={requestIdFromError(m.error) ? `request_id: ${requestIdFromError(m.error)}` : ""}
              />
            ) : m.isSuccess ? (
              <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Typography.Text type="secondary">request_id: {m.data.request_id || "-"}</Typography.Text>
                <Typography.Text type="secondary">url: {m.data.url}</Typography.Text>

                {m.data.kind === "json" ? (
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    {JSON.stringify(m.data.payload, null, 2)}
                  </pre>
                ) : m.data.kind === "image" ? (
                  <>
                    <img src={m.data.src} alt="random" style={{ maxWidth: "100%", borderRadius: 6 }} />
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(m.data.headers, null, 2)}</pre>
                  </>
                ) : (
                  <>
                    <Typography.Text>
                      Location: {m.data.location ? m.data.location : "(not available)"}
                    </Typography.Text>
                    {m.data.note ? <Alert type="info" showIcon message={m.data.note} /> : null}
                  </>
                )}
              </Space>
            ) : (
              <Alert
                type="info"
                showIcon
                message="Ready"
                description="Pick filters and click Run to sample /random."
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={6}>
          <Card title="Tools">
            <Space direction="vertical" style={{ width: "100%" }}>
              <Button onClick={onCopyUrl} disabled={!url}>
                Copy URL
              </Button>
              <Button onClick={onCopyCurl} disabled={!url}>
                Copy curl
              </Button>
              <Button onClick={onOpen} disabled={!url}>
                Open in new window
              </Button>
              <Alert type="info" showIcon message="Note" description="Redirect mode may be limited by browser fetch rules." />
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
