import { useCallback, useEffect, useRef, useState } from "react";
import type { DetBox } from "../api/types";

export interface DraftRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface BoxCanvasProps {
  imageUrl: string | null;
  width: number;
  height: number;
  boxes: DetBox[];
  labelColors: Record<number, string>;
  drawEnabled: boolean;
  selectedIndex: number | null;
  draftRect: DraftRect | null;
  onDraftRect: (rect: DraftRect) => void;
}

export default function BoxCanvas({
  imageUrl,
  width,
  height,
  boxes,
  labelColors,
  drawEnabled,
  selectedIndex,
  draftRect,
  onDraftRect,
}: BoxCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const startRef = useRef<{ x: number; y: number } | null>(null);
  const [imageReady, setImageReady] = useState(false);
  const [localDraft, setLocalDraft] = useState<DraftRect | null>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(0, 0, width, height);
    if (imageReady && imageRef.current) {
      ctx.drawImage(imageRef.current, 0, 0, width, height);
    }
    boxes.forEach((box, index) => {
      const [cx, cy] = box.center_voxel;
      const [sx, sy] = box.size_voxel;
      const x = cx - sx / 2;
      const y = cy - sy / 2;
      const color = labelColors[box.label_id] ?? "#fa8c16";
      ctx.save();
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      const baseWidth = Math.max(1, width / 256);
      ctx.lineWidth = index === selectedIndex ? baseWidth * 2 : baseWidth;
      ctx.globalAlpha = 0.12;
      ctx.fillRect(x, y, sx, sy);
      ctx.globalAlpha = 1;
      ctx.strokeRect(x, y, sx, sy);
      ctx.restore();
    });
    const rect = draftRect ?? localDraft;
    if (rect) {
      ctx.save();
      ctx.strokeStyle = "#ffffff";
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 2;
      ctx.strokeRect(rect.x, rect.y, rect.width, rect.height);
      ctx.restore();
    }
  }, [
    boxes,
    draftRect,
    height,
    imageReady,
    labelColors,
      localDraft,
    selectedIndex,
    width,
  ]);

  useEffect(() => {
    setImageReady(false);
    imageRef.current = null;
    if (!imageUrl) {
      draw();
      return;
    }
    const image = new Image();
    image.onload = () => {
      imageRef.current = image;
      setImageReady(true);
    };
    image.src = imageUrl;
    return () => {
      image.onload = null;
    };
  }, [imageUrl]);

  useEffect(() => {
    if (imageReady) draw();
  }, [imageReady, draw]);

  const point = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * width,
      y: ((event.clientY - rect.top) / rect.height) * height,
    };
  };

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{
        cursor: drawEnabled ? "crosshair" : "default",
        touchAction: "none",
        width: "100%",
        height: "100%",
        display: "block",
        imageRendering: "pixelated",
        background: "#0b1220",
      }}
      onPointerDown={(event) => {
        if (!drawEnabled) return;
        const position = point(event);
        startRef.current = position;
        setLocalDraft({ x: position.x, y: position.y, width: 0, height: 0 });
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (!startRef.current) return;
        const position = point(event);
        const start = startRef.current;
        setLocalDraft({
          x: Math.min(start.x, position.x),
          y: Math.min(start.y, position.y),
          width: Math.abs(position.x - start.x),
          height: Math.abs(position.y - start.y),
        });
      }}
      onPointerUp={(event) => {
        if (!startRef.current) return;
        const position = point(event);
        const start = startRef.current;
        startRef.current = null;
        event.currentTarget.releasePointerCapture(event.pointerId);
        const rect = {
          x: Math.min(start.x, position.x),
          y: Math.min(start.y, position.y),
          width: Math.abs(position.x - start.x),
          height: Math.abs(position.y - start.y),
        };
        setLocalDraft(null);
        if (rect.width >= 4 && rect.height >= 4) {
          onDraftRect(rect);
        }
      }}
      onPointerLeave={() => {
        startRef.current = null;
        setLocalDraft(null);
      }}
    />
  );
}
