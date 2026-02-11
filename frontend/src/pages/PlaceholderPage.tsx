import { Alert } from "antd";
import React from "react";

export function PlaceholderPage({ title }: { title: string }) {
  return <Alert message={title} description="TODO" type="info" showIcon />;
}

