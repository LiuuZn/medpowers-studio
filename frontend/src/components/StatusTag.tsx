import { Tag } from "antd";

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  draft: { color: "default", label: "草稿" },
  ready: { color: "success", label: "就绪" },
  active: { color: "success", label: "进行中" },
  archived: { color: "default", label: "已归档" },
  pending: { color: "default", label: "待标注" },
  in_progress: { color: "processing", label: "标注中" },
  submitted: { color: "warning", label: "待审核" },
  approved: { color: "success", label: "已通过" },
  review_requested: { color: "warning", label: "待复核" },
  rejected: { color: "error", label: "已驳回" },
  queued: { color: "default", label: "排队中" },
  planned: { color: "default", label: "已规划" },
  running: { color: "processing", label: "执行中" },
  succeeded: { color: "success", label: "成功" },
  done: { color: "success", label: "已完成" },
  interrupted: { color: "warning", label: "已中断" },
  cancelled: { color: "default", label: "已取消" },
  failed: { color: "error", label: "失败" },
  admin: { color: "gold", label: "管理员" },
  annotator: { color: "blue", label: "标注员" },
  reviewer: { color: "purple", label: "审核员" },
};

export default function StatusTag({
  status,
  label,
}: {
  status: string;
  label?: string;
}) {
  const item = STATUS_MAP[status] ?? { color: "default", label: status };
  return <Tag color={item.color}>{label ?? item.label}</Tag>;
}
