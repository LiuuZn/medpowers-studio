import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Divider,
  Empty,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Slider,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import {
  ArrowLeftOutlined,
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  ReloadOutlined,
  SaveOutlined,
  SendOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import {
  annotationApi,
  caseApi,
  getErrorMessage,
  metaApi,
  taskApi,
} from "../api";
import type {
  Annotation,
  CaseItem,
  DetBox,
  KeyFrame,
  SliceInfo,
  Task,
  TaskTypeSpec,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import BoxCanvas from "../components/BoxCanvas";
import type { DraftRect } from "../components/BoxCanvas";
import SegCanvas from "../components/SegCanvas";
import SliceViewport from "../components/SliceViewport";
import type { SliceAxis } from "../components/SliceViewport";
import StatusTag from "../components/StatusTag";

const { Title, Text, Paragraph } = Typography;

function sliceDims(info: SliceInfo, axis: string) {
  if (info.dimension === "2d") {
    return { width: info.width, height: info.height, slices: 1 };
  }
  if (axis === "coronal") {
    return { width: info.width, height: info.slices, slices: info.height };
  }
  if (axis === "sagittal") {
    return { width: info.height, height: info.slices, slices: info.width };
  }
  return { width: info.width, height: info.height, slices: info.slices };
}

async function blobToMask(blob: Blob, width: number, height: number): Promise<Uint8Array> {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("浏览器不支持 Canvas");
  ctx.drawImage(bitmap, 0, 0, width, height);
  const data = ctx.getImageData(0, 0, width, height).data;
  const labels = new Uint8Array(width * height);
  for (let i = 0; i < labels.length; i += 1) {
    labels[i] = data[i * 4];
  }
  bitmap.close();
  return labels;
}

async function maskToBlob(labels: Uint8Array, width: number, height: number): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("浏览器不支持 Canvas");
  const imageData = ctx.createImageData(width, height);
  for (let i = 0; i < labels.length; i += 1) {
    const value = labels[i];
    const offset = i * 4;
    imageData.data[offset] = value;
    imageData.data[offset + 1] = value;
    imageData.data[offset + 2] = value;
    imageData.data[offset + 3] = 255;
  }
  ctx.putImageData(imageData, 0, 0);
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("生成掩码图片失败"))),
      "image/png",
    );
  });
}

export default function AnnotationWorkspacePage() {
  const { datasetId, taskId, caseId } = useParams();
  const navigate = useNavigate();
  const { canAnnotate, canReview, isAdmin } = useAuth();

  const [task, setTask] = useState<Task | null>(null);
  const [caseItem, setCaseItem] = useState<CaseItem | null>(null);
  const [annotation, setAnnotation] = useState<Annotation | null>(null);
  const [sliceInfo, setSliceInfo] = useState<SliceInfo | null>(null);
  const [taskType, setTaskType] = useState<TaskTypeSpec | undefined>();
  const [loading, setLoading] = useState(true);

  const [axis, setAxis] = useState("axial");
  const [index, setIndex] = useState(0);
  const [windowValue, setWindowValue] = useState<number | undefined>();
  const [levelValue, setLevelValue] = useState<number | undefined>();
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(false);

  const [maskLabels, setMaskLabels] = useState<Uint8Array | null>(null);
  const [maskDirty, setMaskDirty] = useState(false);
  const [tool, setTool] = useState<"brush" | "eraser">("brush");
  const [brushSize, setBrushSize] = useState(12);
  const [activeLabel, setActiveLabel] = useState(1);

  const [frames, setFrames] = useState<KeyFrame[]>([]);
  const [framesDirty, setFramesDirty] = useState(false);
  const [crosshair, setCrosshair] = useState({ x: 0, y: 0, z: 0 });
  const [boxes, setBoxes] = useState<DetBox[]>([]);
  const [boxLabel, setBoxLabel] = useState(1);
  const [selectedBox, setSelectedBox] = useState<number | null>(null);
  const [draftRect, setDraftRect] = useState<DraftRect | null>(null);

  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [reviewDecision, setReviewDecision] = useState<"approved" | "rejected" | null>(null);
  const [reviewComment, setReviewComment] = useState("");

  const kind = taskType?.annotation_kind;
  const dims = useMemo(
    () => (sliceInfo ? sliceDims(sliceInfo, axis) : { width: 0, height: 0, slices: 1 }),
    [sliceInfo, axis],
  );
  const status = annotation?.status ?? "pending";
  const editable =
    canAnnotate &&
    task?.status !== "archived" &&
    ["pending", "in_progress", "rejected"].includes(status);
  const labels = task?.label_schema.classes ?? task?.label_schema.labels ?? [];
  const foregroundLabels = labels.filter((item) => item.id !== 0);
  const labelColors = Object.fromEntries(labels.map((item) => [item.id, item.color]));
  const labelNames = Object.fromEntries(labels.map((item) => [item.id, item.name]));

  useEffect(() => {
    if (!taskId || !caseId) return;
    setLoading(true);
    Promise.all([
      taskApi.get(taskId),
      caseApi.get(caseId),
      annotationApi.get(taskId, caseId),
      caseApi.sliceInfo(caseId),
      metaApi.taskTypes(),
    ])
      .then(([taskData, caseData, annotationData, info, types]) => {
        setTask(taskData);
        setCaseItem(caseData);
        setAnnotation(annotationData);
        setSliceInfo(info);
        const spec = types.find((item) => item.code === taskData.task_type);
        setTaskType(spec);
        setWindowValue(info.default_window ?? undefined);
        setLevelValue(info.default_level ?? undefined);
        const itemLabels = taskData.label_schema.classes ?? taskData.label_schema.labels ?? [];
        const first = itemLabels.find((item) => item.id !== 0)?.id ?? 1;
        setActiveLabel(first);
        setBoxLabel(first);
        if (spec?.annotation_kind === "keyframe") {
          const loadedFrames = (annotationData.data.frames as KeyFrame[] | undefined) ?? [];
          setFrames(loadedFrames);
          setFramesDirty(false);
          const primary = loadedFrames.find((item) => item.label_id === 1) ?? loadedFrames[0];
          const z = primary ? primary.z_index : Math.floor(info.slices / 2);
          setCrosshair({
            x: Math.floor(info.width / 2),
            y: Math.floor(info.height / 2),
            z: Math.max(0, Math.min(info.slices - 1, z)),
          });
        }
        if (spec?.annotation_kind === "boxes") {
          setBoxes((annotationData.data.boxes as DetBox[] | undefined) ?? []);
        }
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  }, [taskId, caseId]);

  useEffect(() => {
    if (!caseId || !sliceInfo || kind === "keyframe") {
      if (kind === "keyframe") setImageUrl(null);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setImageLoading(true);
    caseApi
      .sliceBlob(caseId, {
        axis,
        index,
        window: windowValue,
        level: levelValue,
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setImageLoading(false));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [caseId, sliceInfo, kind, axis, index, windowValue, levelValue]);

  useEffect(() => {
    if (!taskId || !caseId || !sliceInfo || kind !== "mask" || axis !== "axial") {
      setMaskLabels(null);
      return;
    }
    let cancelled = false;
    const { width, height } = dims;
    annotationApi
      .maskSliceBlob(taskId, caseId, index)
      .then(async (blob) => {
        if (cancelled) return;
        if (!blob) {
          setMaskLabels(new Uint8Array(width * height));
          setMaskDirty(false);
          return;
        }
        const mask = await blobToMask(blob, width, height);
        if (!cancelled) {
          setMaskLabels(mask);
          setMaskDirty(false);
        }
      })
      .catch((error) => message.error(getErrorMessage(error)));
    return () => {
      cancelled = true;
    };
  }, [taskId, caseId, sliceInfo, kind, axis, index, dims.width, dims.height, annotation?.version]);

  const saveMask = async (): Promise<Annotation | null> => {
    if (!taskId || !caseId || !maskLabels || !task || kind !== "mask") return null;
    setSaving(true);
    try {
      const blob = await maskToBlob(maskLabels, dims.width, dims.height);
      const saved =
        task.task_type === "seg3d"
          ? await annotationApi.saveMaskSlice(taskId, caseId, index, blob)
          : await annotationApi.saveMask(taskId, caseId, blob);
      setAnnotation(saved);
      setMaskDirty(false);
      message.success("当前掩码已保存");
      return saved;
    } catch (error) {
      message.error(getErrorMessage(error));
      return null;
    } finally {
      setSaving(false);
    }
  };

  const saveData = async (): Promise<Annotation | null> => {
    if (!taskId || !caseId || !task) return null;
    setSaving(true);
    try {
      const payload =
        kind === "keyframe"
          ? { frames }
          : {
              boxes: boxes.map((box) => ({
                label_id: box.label_id,
                center_voxel: box.center_voxel,
                size_voxel: box.size_voxel,
              })),
            };
      const saved = await annotationApi.saveData(taskId, caseId, payload);
      setAnnotation(saved);
      if (kind === "keyframe") {
        setFrames((saved.data.frames as KeyFrame[] | undefined) ?? []);
        setFramesDirty(false);
      }
      if (kind === "boxes") {
        setBoxes((saved.data.boxes as DetBox[] | undefined) ?? []);
      }
      message.success("标注已保存");
      return saved;
    } catch (error) {
      message.error(getErrorMessage(error));
      return null;
    } finally {
      setSaving(false);
    }
  };

  const changeIndex = async (next: number) => {
    const clamped = Math.max(0, Math.min(dims.slices - 1, next));
    if (clamped === index) return;
    if (kind === "mask" && maskDirty && editable) {
      const saved = await saveMask();
      if (!saved) return;
    }
    setIndex(clamped);
  };

  const changeAxis = async (next: string) => {
    if (next === axis) return;
    if (kind === "mask" && maskDirty && editable) {
      const saved = await saveMask();
      if (!saved) return;
    }
    setAxis(next);
    setIndex(0);
  };

  // 检测任务 ← → 翻层，方便连续阅片
  useEffect(() => {
    if (kind !== "boxes") return;
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target as HTMLElement | null;
      if (
        target?.closest(
          "input, textarea, select, [contenteditable='true'], .ant-select, .ant-slider",
        )
      ) {
        return;
      }
      if (!sliceInfo || sliceInfo.dimension !== "3d") return;
      event.preventDefault();
      void changeIndex(index + (event.key === "ArrowRight" ? 1 : -1));
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [kind, sliceInfo, index, dims.slices, editable, maskDirty]);

  // 关键帧任务：← → 调整轴位层，三个视窗联动
  useEffect(() => {
    if (kind !== "keyframe" || !sliceInfo || sliceInfo.dimension !== "3d") return;
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target as HTMLElement | null;
      if (
        target?.closest(
          "input, textarea, select, [contenteditable='true'], .ant-select, .ant-slider",
        )
      ) {
        return;
      }
      event.preventDefault();
      const delta = event.key === "ArrowRight" ? 1 : -1;
      setCrosshair((prev) => ({
        ...prev,
        z: Math.max(0, Math.min(sliceInfo.slices - 1, prev.z + delta)),
      }));
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [kind, sliceInfo]);

  const submit = async () => {
    if (!taskId || !caseId) return;
    setSubmitting(true);
    try {
      let current = annotation;
      if (editable) {
        const saved = kind === "mask" ? await saveMask() : await saveData();
        if (!saved) return;
        current = saved;
      }
      if (!current?.id) {
        message.error("请先保存标注内容");
        return;
      }
      const submitted = await annotationApi.submit(current.id);
      setAnnotation(submitted);
      message.success("已提交审核");
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  const doReview = async () => {
    if (!annotation?.id || !reviewDecision) return;
    try {
      const updated = await annotationApi.review(
        annotation.id,
        reviewDecision,
        reviewComment,
      );
      setAnnotation(updated);
      setReviewDecision(null);
      setReviewComment("");
      message.success(reviewDecision === "approved" ? "已通过审核" : "已驳回");
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const reopen = async () => {
    if (!annotation?.id) return;
    try {
      const updated = await annotationApi.reopen(annotation.id);
      setAnnotation(updated);
      message.success("已撤回为标注中");
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const jumpToAxial = (zIndex: number) => {
    if (!sliceInfo) return;
    setCrosshair((prev) => ({
      ...prev,
      z: Math.max(0, Math.min(sliceInfo.slices - 1, zIndex)),
    }));
  };

  const setLabelFrame = (labelId: number) => {
    if (!editable) return;
    setFrames((prev) => {
      const next = prev.filter((item) => item.label_id !== labelId);
      next.push({ label_id: labelId, z_index: crosshair.z });
      return next.sort((a, b) => a.z_index - b.z_index || a.label_id - b.label_id);
    });
    setFramesDirty(true);
  };

  const clearLabel = (labelId: number) => {
    if (!editable) return;
    setFrames((prev) => prev.filter((item) => item.label_id !== labelId));
    setFramesDirty(true);
  };

  const stepAxis = (axisName: "x" | "y" | "z", delta: number) => {
    if (!sliceInfo) return;
    const limit =
      axisName === "z"
        ? sliceInfo.slices
        : axisName === "x"
          ? sliceInfo.width
          : sliceInfo.height;
    setCrosshair((prev) => {
      const value = Math.max(0, Math.min(limit - 1, prev[axisName] + delta));
      if (axisName === "x") return { ...prev, x: value };
      if (axisName === "y") return { ...prev, y: value };
      return { ...prev, z: value };
    });
  };

  const setPoint = (viewAxis: SliceAxis, u: number, v: number) => {
    if (viewAxis === "axial") {
      setCrosshair((prev) => ({ ...prev, x: u, y: v }));
    } else if (viewAxis === "coronal") {
      setCrosshair((prev) => ({ ...prev, x: u, z: v }));
    } else {
      setCrosshair((prev) => ({ ...prev, y: u, z: v }));
    }
  };

  const resetWindow = () => {
    if (!sliceInfo) return;
    setWindowValue(sliceInfo.default_window ?? undefined);
    setLevelValue(sliceInfo.default_level ?? undefined);
  };

  const addBox = (rect: DraftRect) => {
    if (!editable) return;
    const box: DetBox = {
      label_id: boxLabel,
      center_voxel: [rect.x + rect.width / 2, rect.y + rect.height / 2, index],
      size_voxel: [rect.width, rect.height, 1],
    };
    setBoxes([...boxes, box]);
    setSelectedBox(boxes.length);
    setDraftRect(null);
    message.info("已添加包围框，可在右侧调整 z 轴中心与范围");
  };

  const updateBox = (boxIndex: number, patch: Partial<DetBox>) => {
    setBoxes(boxes.map((item, i) => (i === boxIndex ? { ...item, ...patch } : item)));
  };

  const currentBoxes = boxes.filter((box) => {
    const z = box.center_voxel[2] ?? 0;
    const sizeZ = box.size_voxel[2] ?? 1;
    return Math.abs(index - z) <= Math.max(sizeZ, 1) / 2;
  });
  const currentFrames = frames.filter((frame) => frame.z_index === crosshair.z);
  const labeledCount = new Set(frames.map((frame) => frame.label_id)).size;

  if (loading || !task || !sliceInfo || !caseItem) {
    return (
      <div className="mp-page">
        <Card className="mp-card" loading={loading} />
      </div>
    );
  }

  const readOnlyReason =
    !editable && task.status !== "archived"
      ? status === "submitted"
        ? "标注已提交，等待审核；审核前不可修改。"
        : status === "approved"
          ? "标注已通过审核；如需修改，请管理员撤回。"
          : "当前账号无权编辑该标注。"
      : task.status === "archived"
        ? "任务已归档，不能继续标注。"
        : "";

  const backDatasetId = datasetId || caseItem.dataset_id;
  const backUrl = `/datasets/${backDatasetId}?taskId=${task.id}`;

  const zSpacing = Number(sliceInfo.spacing?.[2] ?? 0);
  const spacingX = Number(sliceInfo.spacing?.[0] ?? 1) || 1;
  const spacingY = Number(sliceInfo.spacing?.[1] ?? 1) || 1;
  const spacingZ = Number(sliceInfo.spacing?.[2] ?? 1) || 1;

  const reviewModal = (
    <Modal
      title={reviewDecision === "approved" ? "通过审核" : "驳回标注"}
      open={reviewDecision !== null}
      onCancel={() => {
        setReviewDecision(null);
        setReviewComment("");
      }}
      onOk={doReview}
      okText={reviewDecision === "approved" ? "确认通过" : "确认驳回"}
      okButtonProps={{ danger: reviewDecision === "rejected" }}
      destroyOnHidden
    >
      <Paragraph type="secondary">
        审核结论会记录到标注版本中。驳回后标注员可以继续修改并重新提交。
      </Paragraph>
      <Input.TextArea
        rows={4}
        value={reviewComment}
        onChange={(event) => setReviewComment(event.target.value)}
        placeholder="审核意见（可选）"
      />
    </Modal>
  );

  if (kind === "keyframe" && sliceInfo.dimension === "3d") {
    const zMax = Math.max(0, sliceInfo.slices - 1);
    return (
      <div className="mp-keyframe-page">
        <div className="mp-keyframe-topbar">
          <div className="mp-keyframe-topbar-main">
            <Button
              type="link"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate(backUrl)}
            >
              返回数据集
            </Button>
            <Text strong className="mp-keyframe-case" title={caseItem.case_uid}>
              {caseItem.case_uid}
            </Text>
            <Tag color="blue">{task.name}</Tag>
            <StatusTag status={status} />
            <Tag>v{annotation?.version ?? 0}</Tag>
            {framesDirty && <Tag color="orange">未保存</Tag>}
          </div>
          <Space wrap size={6}>
            {editable && (
              <>
                <Button
                  size="small"
                  icon={<SaveOutlined />}
                  loading={saving}
                  onClick={() => void saveData()}
                >
                  保存
                </Button>
                <Button
                  size="small"
                  type="primary"
                  icon={<SendOutlined />}
                  loading={submitting}
                  onClick={submit}
                >
                  提交审核
                </Button>
              </>
            )}
            {canReview && status === "submitted" && (
              <>
                <Button
                  size="small"
                  type="primary"
                  icon={<CheckOutlined />}
                  onClick={() => setReviewDecision("approved")}
                >
                  通过
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<CloseOutlined />}
                  onClick={() => setReviewDecision("rejected")}
                >
                  驳回
                </Button>
              </>
            )}
            {isAdmin &&
              annotation?.id &&
              ["submitted", "approved", "rejected"].includes(status) && (
                <Button size="small" icon={<ReloadOutlined />} onClick={reopen}>
                  撤回
                </Button>
              )}
          </Space>
        </div>

        <div className="mp-keyframe-grid">
          <SliceViewport
            caseId={caseItem.id}
            axis="axial"
            title="轴位"
            index={crosshair.z}
            width={sliceInfo.width}
            height={sliceInfo.height}
            spacingU={spacingX}
            spacingV={spacingY}
            crosshairU={crosshair.x}
            crosshairV={crosshair.y}
            windowValue={windowValue}
            levelValue={levelValue}
            onPoint={(u, v) => setPoint("axial", u, v)}
            onStep={(delta) => stepAxis("z", delta)}
            overlay={
              currentFrames.length > 0 ? (
                <div className="mp-slice-tags">
                  {currentFrames.map((frame, frameIndex) => (
                    <Tag
                      key={`axial-tag-${frameIndex}`}
                      color={labelColors[frame.label_id]}
                      style={{ marginInlineEnd: 0 }}
                    >
                      {labelNames[frame.label_id] ?? `#${frame.label_id}`}
                    </Tag>
                  ))}
                </div>
              ) : undefined
            }
          />
          <SliceViewport
            caseId={caseItem.id}
            axis="sagittal"
            title="矢状位"
            index={crosshair.x}
            width={sliceInfo.height}
            height={sliceInfo.slices}
            spacingU={spacingY}
            spacingV={spacingZ}
            crosshairU={crosshair.y}
            crosshairV={crosshair.z}
            flipVertical
            windowValue={windowValue}
            levelValue={levelValue}
            onPoint={(u, v) => setPoint("sagittal", u, v)}
            onStep={(delta) => stepAxis("x", delta)}
          />
          <SliceViewport
            caseId={caseItem.id}
            axis="coronal"
            title="冠状位"
            index={crosshair.y}
            width={sliceInfo.width}
            height={sliceInfo.slices}
            spacingU={spacingX}
            spacingV={spacingZ}
            crosshairU={crosshair.x}
            crosshairV={crosshair.z}
            flipVertical
            windowValue={windowValue}
            levelValue={levelValue}
            onPoint={(u, v) => setPoint("coronal", u, v)}
            onStep={(delta) => stepAxis("y", delta)}
          />

          <Card
            className="mp-card mp-keyframe-info"
            size="small"
            title="关键帧与信息"
            styles={{ body: { padding: 12, overflow: "auto" } }}
          >
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Space style={{ width: "100%", justifyContent: "space-between" }}>
                <Text type="secondary">当前轴位</Text>
                <Text strong>
                  第 {crosshair.z} / {zMax} 层
                </Text>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {(crosshair.z * zSpacing).toFixed(1)} mm · 体素 x {crosshair.x} / y{" "}
                {crosshair.y}
              </Text>
              <Space wrap size={6}>
                <Text type="secondary">窗宽</Text>
                <InputNumber
                  size="small"
                  value={windowValue}
                  onChange={(value) => setWindowValue(value ?? undefined)}
                  style={{ width: 88 }}
                />
                <Text type="secondary">窗位</Text>
                <InputNumber
                  size="small"
                  value={levelValue}
                  onChange={(value) => setLevelValue(value ?? undefined)}
                  style={{ width: 88 }}
                />
                <Button size="small" onClick={resetWindow}>
                  自动
                </Button>
              </Space>
              <Divider style={{ margin: "2px 0" }} />
              <Space style={{ width: "100%", justifyContent: "space-between" }}>
                <Text type="secondary">关键帧</Text>
                <Text type="secondary">
                  已标注 {labeledCount}/{labels.length}
                </Text>
              </Space>
              {labels.map((label) => {
                const labelFrames = frames.filter((item) => item.label_id === label.id);
                const primary = labelFrames[0];
                const atCurrent = labelFrames.some(
                  (item) => item.z_index === crosshair.z,
                );
                return (
                  <div key={label.id} className="mp-keyframe-row">
                    <Space size={6} wrap>
                      <span
                        className="mp-legend-dot"
                        style={{ background: label.color }}
                      />
                      {primary ? (
                        <Button
                          type="link"
                          size="small"
                          className="mp-keyframe-name"
                          style={{ color: label.color }}
                          title={`跳转到轴位第 ${primary.z_index} 层`}
                          onClick={() => jumpToAxial(primary.z_index)}
                        >
                          {label.name}
                        </Button>
                      ) : (
                        <Text strong>{label.name}</Text>
                      )}
                      {primary ? (
                        <>
                          <Text>
                            第 {labelFrames.map((item) => item.z_index).join(" / ")} 层
                          </Text>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {(primary.z_index * zSpacing).toFixed(1)} mm
                          </Text>
                        </>
                      ) : (
                        <Text type="secondary">未标注</Text>
                      )}
                    </Space>
                    <Space size={2}>
                      <Button
                        size="small"
                        disabled={!editable || atCurrent}
                        onClick={() => setLabelFrame(label.id)}
                      >
                        {atCurrent
                          ? "已在当前层"
                          : primary
                            ? "更新到当前层"
                            : "标注当前层"}
                      </Button>
                      {primary && (
                        <Button
                          size="small"
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          disabled={!editable}
                          onClick={() => clearLabel(label.id)}
                        />
                      )}
                    </Space>
                  </div>
                );
              })}
              <Divider style={{ margin: "2px 0" }} />
              <Text type="secondary" style={{ fontSize: 12 }}>
                左键点击视窗定位十字线；滚轮翻层；← → 调整轴位层。
              </Text>
              {readOnlyReason && (
                <Alert
                  type={status === "approved" ? "success" : "info"}
                  showIcon
                  message={readOnlyReason}
                />
              )}
              {annotation?.review_comment && (
                <Alert
                  type={status === "rejected" ? "error" : "success"}
                  showIcon
                  message={`审核意见：${annotation.review_comment}`}
                />
              )}
              <Space style={{ width: "100%", justifyContent: "space-between" }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  标注员：{annotation?.annotator?.display_name || "-"}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {annotation?.updated_at
                    ? dayjs(annotation.updated_at).format("YYYY-MM-DD HH:mm")
                    : "-"}
                </Text>
              </Space>
            </Space>
          </Card>
        </div>
        {reviewModal}
      </div>
    );
  }

  const stageStyle: CSSProperties = {
    width:
      dims.height > 0
        ? `min(100%, calc(68vh * ${dims.width / dims.height}))`
        : "100%",
    aspectRatio: `${dims.width} / ${Math.max(dims.height, 1)}`,
    maxHeight: "68vh",
  };

  return (
    <div className="mp-page">
      <div className="mp-page-header">
        <div>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            style={{ paddingLeft: 0 }}
            onClick={() => navigate(backUrl)}
          >
            返回数据集
          </Button>
          <Title className="mp-page-title" style={{ marginTop: 4 }}>
            {caseItem.case_uid}
          </Title>
          <Space style={{ marginTop: 8 }} wrap>
            <Tag color="blue">{task.name}</Tag>
            <Tag>{taskType?.name ?? task.task_type}</Tag>
            <Tag>{task.dimension.toUpperCase()}</Tag>
            <StatusTag status={status} />
            <Tag>版本 v{annotation?.version ?? 0}</Tag>
            <Text type="secondary">{caseItem.source_path || caseItem.source_kind}</Text>
          </Space>
        </div>
        <Space wrap>
          {editable && (
            <Button
              icon={<SaveOutlined />}
              loading={saving}
              onClick={() => (kind === "mask" ? saveMask() : saveData())}
            >
              保存
            </Button>
          )}
          {editable && (
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={submitting}
              onClick={submit}
            >
              提交审核
            </Button>
          )}
          {canReview && status === "submitted" && (
            <Space>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                onClick={() => setReviewDecision("approved")}
              >
                通过
              </Button>
              <Button danger icon={<CloseOutlined />} onClick={() => setReviewDecision("rejected")}>
                驳回
              </Button>
            </Space>
          )}
          {isAdmin && annotation?.id && ["submitted", "approved", "rejected"].includes(status) && (
            <Button icon={<ReloadOutlined />} onClick={reopen}>
              撤回
            </Button>
          )}
        </Space>
      </div>

      {readOnlyReason && (
        <Alert
          type={status === "approved" ? "success" : "info"}
          showIcon
          message={readOnlyReason}
          style={{ marginBottom: 16 }}
        />
      )}
      {annotation?.review_comment && (
        <Alert
          type={status === "rejected" ? "error" : "success"}
          showIcon
          message={`审核意见：${annotation.review_comment}`}
          style={{ marginBottom: 16 }}
        />
      )}

      <div className="mp-annotation-layout">
        <div className="mp-annotation-panel">
          <Card className="mp-card" size="small" title="任务信息">
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Text strong>{task.name}</Text>
              <Text type="secondary">{taskType?.name}</Text>
              <div>
                {labels.map((item) => (
                  <Tag key={item.id} color={item.color} style={{ marginBottom: 6 }}>
                    {item.id}. {item.name}
                  </Tag>
                ))}
              </div>
              {task.annotation_guide && (
                <>
                  <Divider style={{ margin: "8px 0" }} />
                  <Text type="secondary" style={{ whiteSpace: "pre-wrap" }}>
                    {task.annotation_guide}
                  </Text>
                </>
              )}
            </Space>
          </Card>

          <Card className="mp-card" size="small" title="标注工具" style={{ marginTop: 12 }}>
            {kind === "mask" && (
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                {axis !== "axial" && (
                  <Alert type="info" showIcon message="首版仅支持轴位勾画，请切换到轴位" />
                )}
                <div>
                  <Text type="secondary">工具</Text>
                  <Radio.Group
                    value={tool}
                    onChange={(event) => setTool(event.target.value)}
                    optionType="button"
                    buttonStyle="solid"
                    style={{ display: "flex", marginTop: 6 }}
                  >
                    <Radio.Button value="brush" style={{ flex: 1 }}>
                      画笔
                    </Radio.Button>
                    <Radio.Button value="eraser" style={{ flex: 1 }}>
                      橡皮
                    </Radio.Button>
                  </Radio.Group>
                </div>
                <div>
                  <Text type="secondary">画笔大小：{brushSize}px</Text>
                  <Slider
                    min={1}
                    max={64}
                    value={brushSize}
                    onChange={setBrushSize}
                    disabled={!editable}
                  />
                </div>
                <div>
                  <Text type="secondary">当前类别</Text>
                  <Select
                    style={{ width: "100%", marginTop: 6 }}
                    value={activeLabel}
                    onChange={setActiveLabel}
                    disabled={!editable}
                    options={foregroundLabels.map((item) => ({
                      value: item.id,
                      label: (
                        <Space>
                          <span
                            className="mp-legend-dot"
                            style={{ background: item.color }}
                          />
                          {item.name}
                        </Space>
                      ),
                    }))}
                  />
                </div>
                <Space>
                  <Button
                    disabled={!editable || !maskLabels}
                    onClick={() => {
                      setMaskLabels(new Uint8Array(dims.width * dims.height));
                      setMaskDirty(true);
                    }}
                  >
                    清空当前层
                  </Button>
                  <Button
                    type="primary"
                    ghost
                    icon={<SaveOutlined />}
                    loading={saving}
                    disabled={!editable || !maskLabels}
                    onClick={saveMask}
                  >
                    保存当前层
                  </Button>
                </Space>
              </Space>
            )}

            {kind === "boxes" && (
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                <Alert
                  type="info"
                  showIcon
                  message="在轴位影像上拖拽画框，再在右侧调整 z 轴中心与范围"
                />
                <div>
                  <Text type="secondary">包围框标签</Text>
                  <Select
                    style={{ width: "100%", marginTop: 6 }}
                    value={boxLabel}
                    onChange={setBoxLabel}
                    disabled={!editable}
                    options={labels.map((item) => ({
                      value: item.id,
                      label: item.name,
                    }))}
                  />
                </div>
                <Button
                  type="primary"
                  ghost
                  icon={<SaveOutlined />}
                  loading={saving}
                  disabled={!editable}
                  onClick={saveData}
                >
                  保存包围框
                </Button>
              </Space>
            )}

            <Divider style={{ margin: "12px 0" }} />
            <Space direction="vertical" size={2} style={{ width: "100%" }}>
              <Text type="secondary">标注员：{annotation?.annotator?.display_name || "-"}</Text>
              <Text type="secondary">
                更新时间：
                {annotation?.updated_at
                  ? dayjs(annotation.updated_at).format("YYYY-MM-DD HH:mm")
                  : "-"}
              </Text>
            </Space>
          </Card>
        </div>

        <Card className="mp-card" size="small" styles={{ body: { padding: 12 } }}>
          <Space wrap style={{ marginBottom: 10, width: "100%", justifyContent: "space-between" }}>
            <Space wrap>
              {sliceInfo.dimension === "3d" && (
                <Select
                  value={axis}
                  onChange={changeAxis}
                  style={{ width: 110 }}
                  options={[
                    { value: "axial", label: "轴位" },
                    { value: "coronal", label: "冠状位" },
                    { value: "sagittal", label: "矢状位" },
                  ]}
                />
              )}
              {sliceInfo.dimension === "3d" && (
                <Space>
                  <Text type="secondary">层</Text>
                  <Slider
                    min={0}
                    max={Math.max(0, dims.slices - 1)}
                    value={index}
                    onChange={(value) => {
                      void changeIndex(value);
                    }}
                    style={{ width: 220 }}
                  />
                  <InputNumber
                    min={0}
                    max={Math.max(0, dims.slices - 1)}
                    value={index}
                    onChange={(value) => {
                      if (typeof value === "number") void changeIndex(value);
                    }}
                    style={{ width: 76 }}
                  />
                  <Text type="secondary">/ {Math.max(0, dims.slices - 1)}</Text>
                </Space>
              )}
            </Space>
            <Space>
              <Text type="secondary">窗</Text>
              <InputNumber
                value={windowValue}
                onChange={(value) => setWindowValue(value ?? undefined)}
                style={{ width: 100 }}
              />
              <Text type="secondary">位</Text>
              <InputNumber
                value={levelValue}
                onChange={(value) => setLevelValue(value ?? undefined)}
                style={{ width: 100 }}
              />
              <Button
                size="small"
                onClick={() => {
                  setWindowValue(sliceInfo.default_window ?? undefined);
                  setLevelValue(sliceInfo.default_level ?? undefined);
                }}
              >
                自动
              </Button>
            </Space>
          </Space>

          <div className="mp-viewer">
            {imageLoading && <Spin size="large" />}
            {!imageLoading && imageUrl && kind === "mask" && axis === "axial" && maskLabels && (
              <div style={stageStyle}>
                <SegCanvas
                  imageUrl={imageUrl}
                  width={dims.width}
                  height={dims.height}
                  labels={maskLabels}
                  labelColors={labelColors}
                  brushSize={brushSize}
                  tool={tool}
                  activeLabel={activeLabel}
                  editable={editable}
                  onLabelsChange={(next) => {
                    setMaskLabels(next);
                    setMaskDirty(true);
                  }}
                />
              </div>
            )}
            {!imageLoading && imageUrl && kind === "mask" && (axis !== "axial" || !maskLabels) && (
              <div style={stageStyle}>
                <img
                  src={imageUrl}
                  alt="影像切片"
                  style={{ width: "100%", height: "100%", objectFit: "contain" }}
                />
              </div>
            )}
            {!imageLoading && imageUrl && kind === "boxes" && (
              <div style={stageStyle}>
                <BoxCanvas
                  imageUrl={imageUrl}
                  width={dims.width}
                  height={dims.height}
                  boxes={axis === "axial" ? currentBoxes : []}
                  labelColors={labelColors}
                  drawEnabled={editable && axis === "axial"}
                  selectedIndex={
                    selectedBox === null ? null : currentBoxes.indexOf(boxes[selectedBox])
                  }
                  draftRect={draftRect}
                  onDraftRect={addBox}
                />
              </div>
            )}
            {!imageLoading && !imageUrl && <Empty description="影像加载失败" />}
          </div>
          <div style={{ marginTop: 8, textAlign: "center" }}>
            <Text type="secondary">
              {dims.width} × {dims.height}
              {sliceInfo.spacing
                ? ` · spacing ${sliceInfo.spacing.map((v) => Number(v).toFixed(2)).join(" × ")} mm`
                : ""}
              {maskDirty ? " · 当前层未保存" : ""}
            </Text>
          </div>
        </Card>

        <Card
          className="mp-card"
          size="small"
          title={kind === "boxes" ? "包围框" : "当前层统计"}
        >
          {kind === "boxes" && (
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              {boxes.length === 0 && <Empty description="尚未添加包围框" />}
              {boxes.map((box, boxIndex) => (
                <Card
                  key={boxIndex}
                  size="small"
                  style={{
                    borderColor: selectedBox === boxIndex ? "#1677ff" : undefined,
                    cursor: "pointer",
                  }}
                  onClick={() => setSelectedBox(boxIndex)}
                >
                  <Space style={{ width: "100%", justifyContent: "space-between" }}>
                    <Space>
                      <Tag color={labelColors[box.label_id]}>
                        {labelNames[box.label_id] ?? `#${box.label_id}`}
                      </Tag>
                      <Text type="secondary">
                        z {box.center_voxel[2].toFixed(1)} · 高 {box.size_voxel[2].toFixed(1)}
                      </Text>
                    </Space>
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={!editable}
                      onClick={(event) => {
                        event.stopPropagation();
                        setBoxes(boxes.filter((_, i) => i !== boxIndex));
                        setSelectedBox(null);
                      }}
                    />
                  </Space>
                </Card>
              ))}
              {selectedBox !== null && boxes[selectedBox] && (
                <Card size="small" title="编辑选中框">
                  <Space direction="vertical" size={6} style={{ width: "100%" }}>
                    <Text type="secondary">中心（体素 x / y / z）</Text>
                    <Space>
                      {[0, 1, 2].map((axisIndex) => (
                        <InputNumber
                          key={axisIndex}
                          value={boxes[selectedBox].center_voxel[axisIndex]}
                          disabled={!editable}
                          onChange={(value) => {
                            if (typeof value !== "number") return;
                            const center = [...boxes[selectedBox].center_voxel];
                            center[axisIndex] = value;
                            updateBox(selectedBox, { center_voxel: center });
                          }}
                          style={{ width: 78 }}
                        />
                      ))}
                    </Space>
                    <Text type="secondary">尺寸（体素 x / y / z）</Text>
                    <Space>
                      {[0, 1, 2].map((axisIndex) => (
                        <InputNumber
                          key={axisIndex}
                          min={0.1}
                          value={boxes[selectedBox].size_voxel[axisIndex]}
                          disabled={!editable}
                          onChange={(value) => {
                            if (typeof value !== "number") return;
                            const size = [...boxes[selectedBox].size_voxel];
                            size[axisIndex] = value;
                            updateBox(selectedBox, { size_voxel: size });
                          }}
                          style={{ width: 78 }}
                        />
                      ))}
                    </Space>
                  </Space>
                </Card>
              )}
            </Space>
          )}

          {kind === "mask" && (
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Text type="secondary">
                当前层 {dims.width} × {dims.height}，共 {labels.length} 个类别
              </Text>
              {maskLabels &&
                labels
                  .filter((item) => item.id !== 0)
                  .map((item) => {
                    let count = 0;
                    for (let i = 0; i < maskLabels.length; i += 1) {
                      if (maskLabels[i] === item.id) count += 1;
                    }
                    return (
                      <Space key={item.id} style={{ width: "100%", justifyContent: "space-between" }}>
                        <Space>
                          <span className="mp-legend-dot" style={{ background: item.color }} />
                          <Text>{item.name}</Text>
                        </Space>
                        <Text strong>{count} px</Text>
                      </Space>
                    );
                  })}
              <Divider style={{ margin: "8px 0" }} />
              <Text type="secondary">
                三维分割按层保存，提交时后端会按影像几何组装为压缩 NRRD 掩码。
              </Text>
            </Space>
          )}

          {annotation?.reviewer && (
            <>
              <Divider style={{ margin: "12px 0" }} />
              <Text type="secondary">
                审核人：{annotation.reviewer.display_name || annotation.reviewer.username}
              </Text>
              {annotation.reviewed_at && (
                <div>
                  <Text type="secondary">
                    审核时间：{dayjs(annotation.reviewed_at).format("YYYY-MM-DD HH:mm")}
                  </Text>
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      {reviewModal}
    </div>
  );
}
