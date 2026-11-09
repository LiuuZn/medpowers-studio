import { useCallback, useEffect, useRef, useState } from "react";

interface SegCanvasProps {
  imageUrl: string | null;
  width: number;
  height: number;
  labels: Uint8Array | null;
  labelColors: Record<number, string>;
  brushSize: number;
  tool: "brush" | "eraser";
  activeLabel: number;
  editable: boolean;
  onLabelsChange: (labels: Uint8Array) => void;
}

function parseColor(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  const normalized = value.length === 3 ? value.split("").map((c) => c + c).join("") : value;
  const num = Number.parseInt(normalized || "ff4d4f", 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

export default function SegCanvas({
  imageUrl,
  width,
  height,
  labels,
  labelColors,
  brushSize,
  tool,
  activeLabel,
  editable,
  onLabelsChange,
}: SegCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const maskRef = useRef<Uint8Array>(new Uint8Array(width * height));
  const drawingRef = useRef(false);
  const [imageReady, setImageReady] = useState(false);

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

    const overlay = overlayRef.current ?? document.createElement("canvas");
    overlay.width = width;
    overlay.height = height;
    overlayRef.current = overlay;
    const overlayCtx = overlay.getContext("2d");
    if (!overlayCtx) return;
    const imageData = overlayCtx.createImageData(width, height);
    const colors = new Map<number, [number, number, number]>();
    Object.entries(labelColors).forEach(([key, value]) => {
      colors.set(Number(key), parseColor(value));
    });
    for (let i = 0; i < maskRef.current.length; i += 1) {
      const label = maskRef.current[i];
      if (!label) continue;
      const [r, g, b] = colors.get(label) ?? [255, 77, 79];
      const offset = i * 4;
      imageData.data[offset] = r;
      imageData.data[offset + 1] = g;
      imageData.data[offset + 2] = b;
      imageData.data[offset + 3] = 135;
    }
    overlayCtx.putImageData(imageData, 0, 0);
    ctx.drawImage(overlay, 0, 0);
  }, [height, imageReady, labelColors, width]);

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

  useEffect(() => {
    maskRef.current = labels ? new Uint8Array(labels) : new Uint8Array(width * height);
    draw();
  }, [labels, width, height, draw]);

  const point = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * width,
      y: ((event.clientY - rect.top) / rect.height) * height,
    };
  };

  const paint = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!editable || !drawingRef.current) return;
    const { x, y } = point(event);
    const radius = Math.max(1, brushSize / 2);
    const value = tool === "eraser" ? 0 : activeLabel;
    const minX = Math.max(0, Math.floor(x - radius));
    const maxX = Math.min(width - 1, Math.ceil(x + radius));
    const minY = Math.max(0, Math.floor(y - radius));
    const maxY = Math.min(height - 1, Math.ceil(y + radius));
    const r2 = radius * radius;
    for (let py = minY; py <= maxY; py += 1) {
      for (let px = minX; px <= maxX; px += 1) {
        const dx = px + 0.5 - x;
        const dy = py + 0.5 - y;
        if (dx * dx + dy * dy <= r2) {
          maskRef.current[py * width + px] = value;
        }
      }
    }
    draw();
  };

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{
        cursor: editable ? "crosshair" : "default",
        touchAction: "none",
        width: "100%",
        height: "100%",
        display: "block",
        imageRendering: "pixelated",
        background: "#0b1220",
      }}
      onPointerDown={(event) => {
        if (!editable) return;
        drawingRef.current = true;
        event.currentTarget.setPointerCapture(event.pointerId);
        paint(event);
      }}
      onPointerMove={paint}
      onPointerUp={(event) => {
        if (!drawingRef.current) return;
        drawingRef.current = false;
        event.currentTarget.releasePointerCapture(event.pointerId);
        onLabelsChange(new Uint8Array(maskRef.current));
      }}
      onPointerLeave={() => {
        if (drawingRef.current) {
          drawingRef.current = false;
          onLabelsChange(new Uint8Array(maskRef.current));
        }
      }}
    />
  );
}
