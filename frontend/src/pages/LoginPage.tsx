import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, apiJson } from "../api/client";
import { setAdminToken } from "../auth/tokenStorage";

type LoginFormValues = {
  username: string;
  password: string;
};

type LoginResponse = {
  ok: true;
  token: string;
  request_id: string;
};

export function LoginPage() {
  const navigate = useNavigate();
  const [form] = Form.useForm<LoginFormValues>();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: LoginFormValues) => {
    setLoading(true);
    setErrorMessage(null);
    setRequestId(null);

    try {
      const resp = await apiJson<LoginResponse>("/admin/api/login", {
        method: "POST",
        body: JSON.stringify({ username: values.username, password: values.password }),
      });

      setAdminToken(resp.token);
      setRequestId(resp.request_id);
      form.resetFields(["password"]);
      navigate("/admin", { replace: true });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
        setRequestId(err.body?.request_id ? String(err.body.request_id) : null);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("Login failed");
      }
    } finally {
      setLoading(false);
    }
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

          <Form<LoginFormValues> form={form} layout="vertical" onFinish={onFinish}>
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

            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form>
        </Space>
      </Card>
    </div>
  );
}
