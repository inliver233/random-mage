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
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [result, setResult] = useState<ImportCreateResponse | null>(null);

  const m = useMutation({
    mutationFn: (values: ImportFormValues) =>
      apiJson<ImportCreateResponse>("/admin/api/imports", {
        method: "POST",
        body: JSON.stringify({
          text: values.text,
          dry_run: values.dry_run,
          hydrate_on_import: values.hydrate_on_import,
          source: "manual",
        }),
      }),
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
      setErrorMessage("Import failed");
    },
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Import
      </Typography.Title>

      {errorMessage ? <Alert type="error" message={errorMessage} showIcon /> : null}
      {requestId ? (
        <Typography.Text type="secondary">request_id: {requestId}</Typography.Text>
      ) : null}

      <Card>
        <Form<ImportFormValues>
          form={form}
          layout="vertical"
          initialValues={{ dry_run: false, hydrate_on_import: false, text: "" }}
          onFinish={(v) => m.mutate(v)}
        >
          <Form.Item
            label="URLs"
            name="text"
            rules={[{ required: true, message: "Please paste Pixiv original URLs" }]}
          >
            <Input.TextArea rows={8} placeholder="One URL per line" />
          </Form.Item>

          <Space size="large">
            <Form.Item label="Dry run" name="dry_run" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="Hydrate on import" name="hydrate_on_import" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>

          <Button type="primary" htmlType="submit">
            导入
          </Button>
        </Form>
      </Card>

      {m.isPending ? <Alert type="info" showIcon message="Importing..." /> : null}
      {result ? (
        <Alert
          type="success"
          showIcon
          message={result.import_id ? "Import created" : "Dry run preview"}
          description={`accepted: ${result.accepted}, deduped: ${result.deduped}, errors: ${result.errors.length}`}
        />
      ) : null}
    </Space>
  );
}
