import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Select, Skeleton, Space, Switch, Typography } from "antd";
import React, { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { ApiError, type ApiErrorBody, apiFetch, apiJson } from "../api/client";

type PlaygroundFormValues = {
  format: "image" | "json" | "redirect";
  attempts: number;
  seed: string;
  strategy: "default" | "quality" | "random";
  quality_samples: number | null;
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

  if (values.strategy !== "default") sp.set("strategy", values.strategy);
  if (values.strategy === "quality" && values.quality_samples != null) sp.set("quality_samples", String(values.quality_samples));

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
      throw new Error("当前浏览器不支持 URL.createObjectURL");
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
    note: proxy ? "未获取到 Location 响应头，已回退为结构化返回中的代理链接。" : "未获取到 Location 响应头。",
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
  const location = useLocation();
  const [form] = Form.useForm<PlaygroundFormValues>();

  const m = useMutation({ mutationFn: fetchPlayground });

  useEffect(() => {
    const sp = new URLSearchParams(location.search);
    const format = sp.get("format");
    const includedTags = sp.get("included_tags");

    const updates: Partial<PlaygroundFormValues> = {};
    if (format === "image" || format === "json" || format === "redirect") updates.format = format;
    if (includedTags != null) updates.included_tags = includedTags;

    if (Object.keys(updates).length > 0) form.setFieldsValue(updates);
  }, [form, location.search]);

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
        随机接口调试
      </Typography.Title>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="筛选条件">
            <Form<PlaygroundFormValues>
              form={form}
              layout="vertical"
              initialValues={{
                format: "json",
                attempts: 3,
                seed: "",
                strategy: "default",
                quality_samples: 5,
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
              <Form.Item label="返回格式" name="format">
                <Select
                  options={[
                    { value: "image", label: "图片流" },
                    { value: "json", label: "JSON" },
                    { value: "redirect", label: "重定向" },
                  ]}
                />
              </Form.Item>

              <Form.Item label="尝试次数" name="attempts">
                <InputNumber min={1} max={10} style={{ width: "100%" }} />
              </Form.Item>

              <Form.Item label="随机种子" name="seed">
                <Input placeholder="可选" />
              </Form.Item>

              <Form.Item label="随机策略" name="strategy">
                <Select
                  options={[
                    { value: "default", label: "使用服务端默认" },
                    { value: "quality", label: "质量优先（更偏向高收藏/高清）" },
                    { value: "random", label: "纯随机（random_key）" },
                  ]}
                />
              </Form.Item>

              <Form.Item noStyle shouldUpdate={(prev, next) => prev.strategy !== next.strategy}>
                {({ getFieldValue }) => (
                  <Form.Item label="质量抽样数量（quality）" name="quality_samples">
                    <InputNumber min={1} max={20} style={{ width: "100%" }} disabled={getFieldValue("strategy") !== "quality"} />
                  </Form.Item>
                )}
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

              <Form.Item label="严格 R18 过滤" name="r18_strict" valuePropName="checked">
                <Switch />
              </Form.Item>

              <Form.Item label="画面方向" name="orientation">
                <Select
                  options={[
                    { value: "any", label: "不限" },
                    { value: "portrait", label: "竖图" },
                    { value: "landscape", label: "横图" },
                    { value: "square", label: "方图" },
                  ]}
                />
              </Form.Item>

              <Form.Item label="最小宽度" name="min_width">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item label="最小高度" name="min_height">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item label="最小像素" name="min_pixels">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>

              <Form.Item label="包含标签（用 | 分隔）" name="included_tags">
                <Input placeholder="标签1|标签2" />
              </Form.Item>
              <Form.Item label="排除标签（用 | 分隔）" name="excluded_tags">
                <Input placeholder="标签1|标签2" />
              </Form.Item>

              <Form.Item label="作者ID" name="user_id">
                <InputNumber min={1} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item label="作品ID" name="illust_id">
                <InputNumber min={1} style={{ width: "100%" }} />
              </Form.Item>

              <Form.Item label="AI 类型" name="ai_type">
                <Select
                  options={[
                    { value: "any", label: "不限" },
                    { value: "0", label: "0" },
                    { value: "1", label: "1" },
                  ]}
                />
              </Form.Item>

              <Form.Item label="创建时间起点（ISO）" name="created_from">
                <Input placeholder="2024-01-01T00:00:00Z" />
              </Form.Item>
              <Form.Item label="创建时间终点（ISO）" name="created_to">
                <Input placeholder="2024-12-31T23:59:59Z" />
              </Form.Item>

              <Button type="primary" htmlType="submit" loading={m.isPending} style={{ width: "100%" }}>
                开始请求
              </Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="返回结果">
            {m.isPending ? (
              <Skeleton active />
            ) : m.isError ? (
              <Alert
                type="error"
                showIcon
                message={m.error instanceof Error ? m.error.message : "请求失败"}
                description={requestIdFromError(m.error) ? `请求ID: ${requestIdFromError(m.error)}` : ""}
              />
            ) : m.isSuccess ? (
              <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Typography.Text type="secondary">请求ID: {m.data.request_id || "-"}</Typography.Text>
                <Typography.Text type="secondary">请求链接: {m.data.url}</Typography.Text>

                {m.data.kind === "json" ? (
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    {JSON.stringify(m.data.payload, null, 2)}
                  </pre>
                ) : m.data.kind === "image" ? (
                  <>
                    <img src={m.data.src} alt="随机图片" style={{ maxWidth: "100%", borderRadius: 6 }} />
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(m.data.headers, null, 2)}</pre>
                  </>
                ) : (
                  <>
                    <Typography.Text>
                      跳转地址: {m.data.location ? m.data.location : "（未提供）"}
                    </Typography.Text>
                    {m.data.note ? <Alert type="info" showIcon message={m.data.note} /> : null}
                  </>
                )}
              </Space>
            ) : (
              <Alert
                type="info"
                showIcon
                message="就绪"
                description="设置筛选条件后，点击“开始请求”即可测试 /random。"
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={6}>
          <Card title="快捷工具">
            <Space direction="vertical" style={{ width: "100%" }}>
              <Button onClick={onCopyUrl} disabled={!url}>
                复制链接
              </Button>
              <Button onClick={onCopyCurl} disabled={!url}>
                复制命令
              </Button>
              <Button onClick={onOpen} disabled={!url}>
                新窗口打开
              </Button>
              <Alert type="info" showIcon message="说明" description="重定向模式会受浏览器 fetch 规则限制。" />
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  );
}

