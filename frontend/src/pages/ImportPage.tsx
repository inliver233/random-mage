import { Alert, Button, Card, Form, Input, Space, Switch, Typography } from "antd";
import React, { useState } from "react";

type ImportFormValues = {
  text: string;
  dry_run: boolean;
  hydrate_on_import: boolean;
};

export function ImportPage() {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);

  const onFinish = (_values: ImportFormValues) => {
    setErrorMessage(null);
    setRequestId(null);
  };

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
          layout="vertical"
          initialValues={{ dry_run: false, hydrate_on_import: false, text: "" }}
          onFinish={onFinish}
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

      <Alert type="info" message="TODO" description="Import wiring pending (ISSUE-0203)." showIcon />
    </Space>
  );
}

