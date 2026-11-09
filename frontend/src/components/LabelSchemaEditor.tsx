import { Button, ColorPicker, Input, Space, Tag, Typography } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import type { LabelClass, LabelSchema, TaskTypeSpec } from "../api/types";

const { Text } = Typography;

const PALETTE = ["#ff4d4f", "#fa8c16", "#fadb14", "#52c41a", "#13c2c2", "#1677ff", "#722ed1"];

export default function LabelSchemaEditor({
  taskType,
  value,
  onChange,
}: {
  taskType: TaskTypeSpec | undefined;
  value: LabelSchema | undefined;
  onChange: (value: LabelSchema) => void;
}) {
  if (!taskType) {
    return <Text type="secondary">请先选择任务类型</Text>;
  }
  const isMask = taskType.annotation_kind === "mask";
  const items: LabelClass[] = isMask ? value?.classes ?? [] : value?.labels ?? [];

  const update = (next: LabelClass[]) => {
    onChange(isMask ? { classes: next } : { labels: next });
  };

  const add = () => {
    const nextId = items.length ? Math.max(...items.map((item) => item.id)) + 1 : 1;
    const item: LabelClass = {
      id: nextId,
      name: isMask ? `类别 ${nextId}` : `标签 ${nextId}`,
      color: PALETTE[nextId % PALETTE.length],
    };
    update([...items, item]);
  };

  const remove = (id: number) => {
    update(items.filter((item) => item.id !== id));
  };

  const change = (id: number, patch: Partial<LabelClass>) => {
    update(items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">
          {isMask
            ? "id=0 固定为背景；前景类别 id 从 1 开始连续编号，标注掩码值即类别 id。"
            : "标签用于关键帧或检测框；id 从 1 开始，名称在同任务内唯一。"}
        </Text>
      </div>
      <Space direction="vertical" style={{ width: "100%" }} size={8}>
        {items.map((item) => (
          <Space key={item.id} style={{ width: "100%" }} align="center">
            <Tag color={item.color} style={{ minWidth: 54, textAlign: "center" }}>
              {item.id}
            </Tag>
            <Input
              value={item.name}
              style={{ width: 220 }}
              onChange={(event) => change(item.id, { name: event.target.value })}
              placeholder="类别名称"
            />
            <ColorPicker
              value={item.color}
              onChange={(color) => change(item.id, { color: color.toHexString() })}
              showText
              size="small"
            />
            {(!isMask || item.id !== 0) && (
              <Button
                danger
                size="small"
                icon={<DeleteOutlined />}
                onClick={() => remove(item.id)}
              />
            )}
            {isMask && item.id === 0 && <Tag>背景</Tag>}
          </Space>
        ))}
      </Space>
      <Button style={{ marginTop: 10 }} icon={<PlusOutlined />} onClick={add}>
        添加{isMask ? "类别" : "标签"}
      </Button>
    </div>
  );
}
