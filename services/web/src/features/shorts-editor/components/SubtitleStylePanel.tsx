"use client";

import { useCallback } from "react";
import type { EditorSubtitle } from "../lib/types";
import { FONT_OPTIONS } from "../constants";

interface SubtitleStylePanelProps {
  title: string;
  onTitleChange: (title: string) => void;
  videoTitle: string | null;
  subtitle: EditorSubtitle | null;
  subtitleIndex: number | null;
  onUpdateSubtitle: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onRemoveSubtitle: (index: number) => void;
}

export function SubtitleStylePanel({
  title,
  onTitleChange,
  videoTitle,
  subtitle,
  subtitleIndex,
  onUpdateSubtitle,
  onRemoveSubtitle,
}: SubtitleStylePanelProps) {
  const handleStyleChange = useCallback(
    (field: string, value: string | number | null) => {
      if (subtitleIndex == null || !subtitle) return;
      onUpdateSubtitle(subtitleIndex, {
        style: { ...subtitle.style, [field]: value },
      });
    },
    [subtitleIndex, subtitle, onUpdateSubtitle],
  );

  return (
    <div className="flex h-full flex-col">
      {/* Title section */}
      <div className="border-b border-gray-200 p-4">
        <label className="block text-xs font-medium text-gray-500 mb-1.5">작곡 내용</label>
        <input
          type="text"
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          placeholder={videoTitle ?? "제목을 입력하세요"}
          className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      {/* Subtitle controls */}
      {subtitle && subtitleIndex != null ? (
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Text */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">자막 텍스트</label>
            <textarea
              value={subtitle.text}
              onChange={(e) =>
                onUpdateSubtitle(subtitleIndex, { text: e.target.value.slice(0, 500) })
              }
              rows={3}
              maxLength={500}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm resize-none focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <span className="text-[10px] text-gray-400">{subtitle.text.length}/500</span>
          </div>

          {/* Text template */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">텍스트 템플릿</label>
            <select
              value={subtitle.style.fontFamily}
              onChange={(e) => handleStyleChange("fontFamily", e.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              {FONT_OPTIONS.map((font) => (
                <option key={font.value} value={font.value}>{font.label}</option>
              ))}
            </select>
          </div>

          {/* Font / Size / Color */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">폰트 / 크기 / 색상</label>
            <div className="flex gap-2">
              <select
                value={subtitle.style.fontFamily}
                onChange={(e) => handleStyleChange("fontFamily", e.target.value)}
                className="flex-1 rounded-lg border border-gray-200 px-2 py-1.5 text-xs focus:border-indigo-500 focus:outline-none"
              >
                {FONT_OPTIONS.map((font) => (
                  <option key={font.value} value={font.value}>{font.label}</option>
                ))}
              </select>
              <input
                type="number"
                value={subtitle.style.fontSizePx}
                onChange={(e) => handleStyleChange("fontSizePx", parseInt(e.target.value, 10) || 36)}
                min={8}
                max={200}
                className="w-16 rounded-lg border border-gray-200 px-2 py-1.5 text-xs text-center focus:border-indigo-500 focus:outline-none"
              />
              <input
                type="color"
                value={subtitle.style.fontColor}
                onChange={(e) => handleStyleChange("fontColor", e.target.value)}
                className="h-8 w-8 cursor-pointer rounded border border-gray-200 p-0.5"
              />
            </div>
          </div>

          {/* Weight */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">굵기</label>
            <div className="flex gap-2">
              {[
                { value: 400, label: "보통" },
                { value: 700, label: "굵게" },
              ].map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => handleStyleChange("fontWeight", opt.value)}
                  className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                    subtitle.style.fontWeight === opt.value
                      ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                      : "border-gray-200 text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Background */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">배경 추가</label>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={subtitle.style.backgroundColor != null}
                onChange={(e) =>
                  handleStyleChange("backgroundColor", e.target.checked ? "#000000" : null)
                }
                className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-xs text-gray-600">배경 색상</span>
              {subtitle.style.backgroundColor != null && (
                <>
                  <input
                    type="color"
                    value={subtitle.style.backgroundColor}
                    onChange={(e) => handleStyleChange("backgroundColor", e.target.value)}
                    className="h-6 w-6 cursor-pointer rounded border border-gray-200 p-0.5"
                  />
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={Math.round(subtitle.style.backgroundOpacity * 100)}
                    onChange={(e) => handleStyleChange("backgroundOpacity", parseInt(e.target.value, 10) / 100)}
                    className="flex-1"
                  />
                  <span className="text-[10px] text-gray-400 w-8 text-right">
                    {Math.round(subtitle.style.backgroundOpacity * 100)}%
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Position */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">위치</label>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 w-6">X</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round(subtitle.style.positionX * 100)}
                  onChange={(e) => handleStyleChange("positionX", parseInt(e.target.value, 10) / 100)}
                  className="flex-1"
                />
                <span className="text-[10px] text-gray-400 w-8 text-right">
                  {Math.round(subtitle.style.positionX * 100)}%
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 w-6">Y</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round(subtitle.style.positionY * 100)}
                  onChange={(e) => handleStyleChange("positionY", parseInt(e.target.value, 10) / 100)}
                  className="flex-1"
                />
                <span className="text-[10px] text-gray-400 w-8 text-right">
                  {Math.round(subtitle.style.positionY * 100)}%
                </span>
              </div>
            </div>
          </div>

          {/* Delete */}
          <button
            type="button"
            onClick={() => onRemoveSubtitle(subtitleIndex)}
            className="w-full rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 transition-colors hover:bg-red-50"
          >
            자막 삭제
          </button>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center p-4 text-gray-400">
          <div className="text-center">
            <p className="text-xs font-medium">자막 스타일</p>
            <p className="mt-1 text-[10px]">타임라인에서 자막을 선택하세요</p>
          </div>
        </div>
      )}
    </div>
  );
}
