import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input, Space, Switch, Typography } from "antd";
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, apiJson } from "../api/client";

type ImportFormValues = {
  text: string;
  dry_run: boolean;
  hydrate_on_import: boolean;
};

type ImportCreateResponse = {
  ok: true;
  import_id: string;
  job_id: string;
  accepted: number;
  deduped: number;
  errors: Array<{ line: number; url: string; code: string; message: string }>;
  preview: Array<{ illust_id: number; page_index: number; ext: string; url: string }>;
  request_id: string;
};

function requestIdFromError(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  return err.body?.request_id ? String(err.body.request_id) : null;
}

export function ImportPage() {
  const navigate = useNavigate();
  const [form] = Form.useForm<ImportFormValues>();
  const [file, setFile] = useState<File | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [result, setResult] = useState<ImportCreateResponse | null>(null);

  const mutation = useMutation({
    mutationFn: (values: ImportFormValues) => {
      if (file) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("dry_run", values.dry_run ? "true" : "false");
        formData.append("hydrate_on_import", values.hydrate_on_import ? "true" : "false");
        formData.append("source", "manual");
        return apiJson<ImportCreateResponse>("/admin/api/imports", { method: "POST", body: formData });
      }

      return apiJson<ImportCreateResponse>("/admin/api/imports", {
        method: "POST",
        body: JSON.stringify({
          text: values.text,
          dry_run: values.dry_run,
          hydrate_on_import: values.hydrate_on_import,
          source: "manual",
        }),
      });
    },
    onMutate: () => {
      setErrorMessage(null);
      setRequestId(null);
      setResult(null);
    },
    onSuccess: (data, values) => {
      setResult(data);
      setRequestId(data.request_id);
      if (!values.dry_run && data.import_id) {
        navigate(`/admin/import/${data.import_id}`);
      }
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
        setRequestId(requestIdFromError(err));
        return;
      }
      if (err instanceof Error) {
        setErrorMessage(err.message);
        return;
      }
      setErrorMessage("导入失败");
    },
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        导入图片链接
      </Typography.Title>

      {errorMessage ? <Alert type="error" message={errorMessage} showIcon /> : null}
      {requestId ? <Typography.Text type="secondary">请求ID: {requestId}</Typography.Text> : null}

      <Card>
        <Form<ImportFormValues>
          form={form}
          layout="vertical"
          initialValues={{ dry_run: false, hydrate_on_import: false, text: "" }}
          onFinish={(values) => mutation.mutate(values)}
        >
          <Form.Item label="上传文本文件（可选，.txt）">
            <input
              data-testid="import-file-input"
              type="file"
              accept=".txt,text/plain"
              onChange={(e) => setFile(e.target.files && e.target.files[0] ? e.target.files[0] : null)}
            />
            <div style={{ marginTop: 8 }}>
              <Typography.Text type="secondary">
                {file ? `已选择文件：${file.name}` : "未选择文件（可在下方粘贴链接）。"}
              </Typography.Text>
            </div>
          </Form.Item>

          <Form.Item
            label="链接列表"
            name="text"
            rules={[
              {
                validator: async (_, value) => {
                  if (file) return Promise.resolve();
                  if (String(value || "").trim()) return Promise.resolve();
                  return Promise.reject(new Error("请粘贴 Pixiv 原图链接，或上传 .txt 文件"));
                },
              },
            ]}
          >
            <Input.TextArea rows={8} placeholder="每行一个链接" disabled={Boolean(file)} />
          </Form.Item>

          <Space size="large">
            <Form.Item label="仅预览（不入库）" name="dry_run" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="导入后立即补全元数据" name="hydrate_on_import" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>

          <Button type="primary" htmlType="submit" loading={mutation.isPending}>
            开始导入
          </Button>
        </Form>
      </Card>

      {mutation.isPending ? <Alert type="info" showIcon message="正在导入..." /> : null}
      {result ? (
        <Alert
          type="success"
          showIcon
          message={result.import_id ? "导入任务已创建" : "预览完成"}
          description={`接收: ${result.accepted}，去重: ${result.deduped}，错误: ${result.errors.length}`}
        />
      ) : null}
    </Space>
  );
}

