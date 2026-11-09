import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { Spin, message } from "antd";
import { caseApi, getErrorMessage } from "../api";

export type SliceAxis = "axial" | "coronal" | "sagittal";

interface SliceViewportProps {
  caseId: string;
  axis: SliceAxis;
  title: string;
  index: number;
  width: number;
  height: number;
  spacingU: number;
  spacingV: number;
  crosshairU: number;
  crosshairV: number;
  flipVertical?: boolean;
  windowValue?: number;
  levelValue?: number;
  overlay?: ReactNode;
  onPoint: (u: number, v: number) => void;
  onStep: (delta: number) => void;
}

/**
 * 单个方向的切片视窗：滚轮翻层、点击/拖动设置十字线。
 * 显示按物理尺寸（spacing）拉伸像素，矢状位/冠状位不会因厚层被压成细条；
 * SVG viewBox 使用物理坐标，十字线与拖动定位在任何窗口尺寸下都精确对应体素。
 */
export default function SliceViewport({
  caseId,
  axis,
  title,
  index,
  width,
  height,
  spacingU,
  spacingV,
  crosshairU,
  crosshairV,
  flipVertical = false,
  windowValue,
  levelValue,
  overlay,
  onPoint,
  onStep,
}: SliceViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const imageUrlRef = useRef<string | null>(null);
  const lastWheelRef = useRef(0);
  const lastPointerRef = useRef(0);
  const draggingRef = useRef(false);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    caseApi
      .sliceBlob(caseId, { axis, index, window: windowValue, level: levelValue })
      .then((blob) => {
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        if (imageUrlRef.current) URL.revokeObjectURL(imageUrlRef.current);
        imageUrlRef.current = url;
        setImageUrl(url);
      })
      .catch((error) => {
        if (!cancelled) message.error(getErrorMessage(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [caseId, axis, index, windowValue, levelValue]);

  useEffect(
    () => () => {
      if (imageUrlRef.current) URL.revokeObjectURL(imageUrlRef.current);
    },
    [],
  );

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const handler = (event: WheelEvent) => {
      event.preventDefault();
      const now = performance.now();
      if (now - lastWheelRef.current < 40) return;
      lastWheelRef.current = now;
      onStep(event.deltaY > 0 ? 1 : -1);
    };
    element.addEventListener("wheel", handler, { passive: false });
    return () => element.removeEventListener("wheel", handler);
  }, [onStep]);

  const su = spacingU > 0 ? spacingU : 1;
  const sv = spacingV > 0 ? spacingV : 1;
  const physicalWidth = width * su;
  const physicalHeight = height * sv;

  const updateFromEvent = (event: ReactPointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const matrix = svg.getScreenCTM();
    if (!matrix) return;
    const local = point.matrixTransform(matrix.inverse());
    const u = Math.max(0, Math.min(width - 1, Math.floor(local.x / su)));
    // 冠状位/矢状位的 z 轴需要上下翻转：viewBox 顶部对应 z 最大值
    const rawV = flipVertical
      ? (physicalHeight - local.y) / sv
      : local.y / sv;
    const v = Math.max(0, Math.min(height - 1, Math.floor(rawV)));
    onPoint(u, v);
  };

  const handlePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.preventDefault();
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    lastPointerRef.current = performance.now();
    updateFromEvent(event);
  };

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!draggingRef.current) return;
    const now = performance.now();
    if (now - lastPointerRef.current < 45) return;
    lastPointerRef.current = now;
    updateFromEvent(event);
  };

  const handlePointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!draggingRef.current) return;
    updateFromEvent(event);
    draggingRef.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handlePointerCancel = (event: ReactPointerEvent<SVGSVGElement>) => {
    draggingRef.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const cx = (crosshairU + 0.5) * su;
  const cy = (crosshairV + 0.5) * sv;
  const contentTransform = flipVertical
    ? `translate(0 ${physicalHeight}) scale(1 -1)`
    : undefined;

  return (
    <div ref={containerRef} className="mp-slice-cell">
      <div className="mp-slice-header">
        <span>{title}</span>
        <span>
          第 {index} 层
          <span className="mp-slice-header-hint"> · 滚轮翻层</span>
        </span>
      </div>
      <svg
        ref={svgRef}
        className="mp-slice-overlay"
        viewBox={`0 0 ${physicalWidth} ${physicalHeight}`}
        preserveAspectRatio="xMidYMid meet"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        role="img"
        aria-label={`${title}切片`}
      >
        <g transform={contentTransform}>
          {imageUrl && (
            <image
              href={imageUrl}
              x={0}
              y={0}
              width={physicalWidth}
              height={physicalHeight}
              preserveAspectRatio="none"
            />
          )}
          <line
            x1={cx}
            y1={0}
            x2={cx}
            y2={physicalHeight}
            stroke="#38bdf8"
            strokeWidth={1}
            strokeDasharray="6 4"
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1={0}
            y1={cy}
            x2={physicalWidth}
            y2={cy}
            stroke="#38bdf8"
            strokeWidth={1}
            strokeDasharray="6 4"
            vectorEffect="non-scaling-stroke"
          />
          <circle
            cx={cx}
            cy={cy}
            r={3}
            fill="none"
            stroke="#38bdf8"
            vectorEffect="non-scaling-stroke"
          />
        </g>
      </svg>
      {overlay}
      {loading && (
        <div className="mp-slice-loading">
          <Spin size="small" />
        </div>
      )}
      {!imageUrl && !loading && <div className="mp-slice-error">影像加载失败</div>}
    </div>
  );
}
