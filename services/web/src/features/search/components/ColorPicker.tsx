"use client";

import { useCallback, useRef, useState } from "react";

interface ColorPickerProps {
  value: string | undefined;
  onChange: (hex: string | undefined) => void;
}

const CANVAS_WIDTH = 200;
const CANVAS_HEIGHT = 100;

export default function ColorPicker({ value, onChange }: ColorPickerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isOpen, setIsOpen] = useState(false);

  const drawGradient = useCallback((canvas: HTMLCanvasElement) => {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Hue gradient (left to right)
    for (let x = 0; x < CANVAS_WIDTH; x++) {
      const hue = (x / CANVAS_WIDTH) * 360;
      for (let y = 0; y < CANVAS_HEIGHT; y++) {
        const saturation = 100 - (y / CANVAS_HEIGHT) * 80; // 100% to 20%
        const lightness = 30 + (y / CANVAS_HEIGHT) * 30; // 30% to 60%
        ctx.fillStyle = `hsl(${hue}, ${saturation}%, ${lightness}%)`;
        ctx.fillRect(x, y, 1, 1);
      }
    }
  }, []);

  const handleCanvasRef = useCallback(
    (canvas: HTMLCanvasElement | null) => {
      if (canvas) {
        canvasRef.current = canvas;
        drawGradient(canvas);
      }
    },
    [drawGradient],
  );

  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const pixel = ctx.getImageData(x, y, 1, 1).data;
      const hex = `#${pixel[0].toString(16).padStart(2, "0")}${pixel[1].toString(16).padStart(2, "0")}${pixel[2].toString(16).padStart(2, "0")}`;
      onChange(hex);
    },
    [onChange],
  );

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center gap-2 text-sm font-medium text-gray-700 hover:text-gray-900"
        >
          <svg
            className={`h-3 w-3 transition-transform ${isOpen ? "rotate-90" : ""}`}
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
              clipRule="evenodd"
            />
          </svg>
          Color
        </button>
        {value && (
          <button
            type="button"
            onClick={() => onChange(undefined)}
            className="text-xs text-primary-600 hover:text-primary-700"
          >
            Clear
          </button>
        )}
      </div>

      {isOpen && (
        <div className="space-y-2">
          <canvas
            ref={handleCanvasRef}
            width={CANVAS_WIDTH}
            height={CANVAS_HEIGHT}
            onClick={handleCanvasClick}
            className="w-full cursor-crosshair rounded border border-gray-200"
            style={{ imageRendering: "pixelated" }}
          />
          {value && (
            <div className="flex items-center gap-2">
              <div
                className="h-6 w-6 rounded border border-gray-300"
                style={{ backgroundColor: value }}
              />
              <span className="text-xs text-gray-500">{value}</span>
            </div>
          )}
        </div>
      )}

      {!isOpen && value && (
        <div className="flex items-center gap-2">
          <div
            className="h-5 w-5 rounded border border-gray-300"
            style={{ backgroundColor: value }}
          />
          <span className="text-xs text-gray-500">{value}</span>
        </div>
      )}
    </div>
  );
}
