import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import React, { useState } from "react";

type LoginFormValues = {
  username: string;
  password: string;
};

export function LoginPage() {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);

  const onFinish = (_values: LoginFormValues) => {
    setErrorMessage(null);
    setRequestId(null);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <Card style={{ width: 360 }}>
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Admin Login
          </Typography.Title>

          {errorMessage ? (
            <Alert type="error" message={errorMessage} showIcon />
          ) : null}

          {requestId ? (
            <Typography.Text type="secondary">request_id: {requestId}</Typography.Text>
          ) : null}

          <Form<LoginFormValues> layout="vertical" onFinish={onFinish}>
            <Form.Item
              label="Username"
              name="username"
              rules={[{ required: true, message: "Username is required" }]}
            >
              <Input placeholder="Username" autoComplete="username" />
            </Form.Item>

            <Form.Item
              label="Password"
              name="password"
              rules={[{ required: true, message: "Password is required" }]}
            >
              <Input.Password placeholder="Password" autoComplete="current-password" />
            </Form.Item>

            <Button type="primary" htmlType="submit" block>
              登录
            </Button>
          </Form>

          <Alert
            type="info"
            message="TODO"
            description="Login wiring pending (ISSUE-0196)."
            showIcon
          />
        </Space>
      </Card>
    </div>
  );
}

