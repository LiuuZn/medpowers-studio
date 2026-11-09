import { useEffect, useMemo, useState } from "react";
import { Alert, Drawer, Space, Table, Tag, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { caseApi, getErrorMessage } from "../api";
import type { TableInfo, TablePage } from "../api/types";

const { Text } = Typography;

interface TablePreviewProps {
  caseId: string | null;
  title?: string;
  open: boolean;
  onClose: () => void;
}

interface RowRecord {
  key: number;
  values: (string | number | boolean | null)[];
}

export default function TablePreview({ caseId, title, open, onClose }: TablePreviewProps) {
  const [info, setInfo] = useState<TableInfo | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [data, setData] = useState<TablePage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !caseId) return;
    setPage(1);
    setPageSize(50);
    setError(null);
    caseApi
      .tableInfo(caseId)
      .then(setInfo)
      .catch((err) => setError(getErrorMessage(err)));
  }, [open, caseId]);

  useEffect(() => {
    if (!open || !caseId) return;
    setLoading(true);
    setError(null);
    caseApi
      .tablePage(caseId, { offset: (page - 1) * pageSize, limit: pageSize })
      .then(setData)
      .catch((err) => setError(getErrorMessage(err)))
      .finally(() => setLoading(false));
  }, [open, caseId, page, pageSize]);

  const columns = useMemo<TableColumnsType<RowRecord>>(() => {
    if (!info) return [];
    return info.columns.map((column, index) => ({
      title: (
        <Space direction="vertical" size={0}>
          <Text strong>{column.name}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {column.type}
          </Text>
        </Space>
      ),
      dataIndex: ["values", index],
      key: `${column.name}-${index}`,
      ellipsis: true,
      width: 180,
    }));
  }, [info]);

  const rows: RowRecord[] = (data?.rows ?? []).map((values, index) => ({
    key: (page - 1) * pageSize + index,
    values,
  }));

  return (
    <Drawer
      title={title || "表格预览"}
      width="80%"
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      {info && (
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag color="blue">{info.row_count} 行</Tag>
          <Tag color="geekblue">{info.column_count} 列</Tag>
          <Text type="secondary">Parquet 规范化存储 · 分页读取</Text>
        </Space>
      )}
      <Table<RowRecord>
        size="small"
        rowKey="key"
        loading={loading}
        columns={columns}
        dataSource={rows}
        scroll={{ x: "max-content" }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100, 200],
          onChange: (nextPage, nextSize) => {
            setPage(nextPage);
            setPageSize(nextSize);
          },
        }}
      />
    </Drawer>
  );
}
