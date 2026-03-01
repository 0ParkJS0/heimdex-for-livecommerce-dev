"use client";

import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { exportPremierePackage } from "@/lib/cloud-export";
import { useSceneBasket } from "./useSceneBasket";

const STORAGE_KEY = "heimdex_drive_mount_path";
const CUSTOM_OPTION = "__custom__";

interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ExportModal({ isOpen, onClose }: ExportModalProps) {
  const { items } = useSceneBasket();
  const { getAccessToken } = useAuth();

  const isMac = typeof navigator !== "undefined" && /Mac/.test(navigator.userAgent);
  const driveOptions = useMemo(
    () =>
      isMac
        ? ["~/Library/CloudStorage/GoogleDrive-email@gmail.com/", "/Volumes/GoogleDrive"]
        : ["G:\\My Drive\\"],
    [isMac]
  );

  const [sequenceName, setSequenceName] = useState("Heimdex Export");
  const [selectedDriveOption, setSelectedDriveOption] = useState(driveOptions[0]);
  const [customDrivePath, setCustomDrivePath] = useState("");
  const [drivePath, setDrivePath] = useState(driveOptions[0]);
  const [clipGapMs, setClipGapMs] = useState(0);
  const [includeMarkers, setIncludeMarkers] = useState(true);
  const [includeTranscriptMarkers, setIncludeTranscriptMarkers] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    const defaultPath = driveOptions[0];
    setSelectedDriveOption(defaultPath);
    setDrivePath(defaultPath);

    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) {
      return;
    }

    if (driveOptions.includes(saved)) {
      setSelectedDriveOption(saved);
      setDrivePath(saved);
      return;
    }

    setSelectedDriveOption(CUSTOM_OPTION);
    setCustomDrivePath(saved);
    setDrivePath(saved);
  }, [driveOptions]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, drivePath);
  }, [drivePath]);

  const handleExport = async () => {
    if (!drivePath.trim()) {
      setError("Google 드라이브 위치를 입력해주세요.");
      return;
    }

    if (items.length === 0) {
      setError("내보낼 장면이 없습니다.");
      return;
    }

    setLoading(true);
    setError("");
    setSuccess("");
    try {
      await exportPremierePackage(
        {
          sequence_name: sequenceName,
          drive_mount_path: drivePath,
          clips: items.map((item) => ({
            scene_id: item.scene_id,
            video_id: item.video_id,
            video_title: item.video_title,
            start_ms: item.start_ms,
            end_ms: item.end_ms,
            label: item.label,
            keyword_tags: item.keyword_tags ?? [],
            transcript_raw: item.transcript_raw ?? "",
          })),
          clip_gap_ms: clipGapMs,
          include_markers: includeMarkers,
          include_transcript_markers: includeTranscriptMarkers,
        },
        getAccessToken
      );
      setSuccess("내보내기가 완료되었습니다. 다운로드를 확인해주세요.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "내보내기에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
        aria-label="모달 닫기"
      />

      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Premiere 내보내기</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 text-xl leading-none"
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">시퀀스 이름</label>
            <input
              type="text"
              value={sequenceName}
              onChange={(e) => setSequenceName(e.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none"
              placeholder="Heimdex Export"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Google 드라이브 위치</label>
            <select
              value={selectedDriveOption}
              onChange={(e) => {
                const value = e.target.value;
                setSelectedDriveOption(value);
                if (value === CUSTOM_OPTION) {
                  setDrivePath(customDrivePath);
                } else {
                  setDrivePath(value);
                }
              }}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none"
            >
              {driveOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
              <option value={CUSTOM_OPTION}>직접 입력...</option>
            </select>
            {selectedDriveOption === CUSTOM_OPTION && (
              <input
                type="text"
                value={customDrivePath}
                onChange={(e) => {
                  const value = e.target.value;
                  setCustomDrivePath(value);
                  setDrivePath(value);
                }}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none mt-2"
                placeholder="경로를 입력하세요"
              />
            )}
            <p className="text-xs text-gray-400 mt-1">
              이 경로는 Premiere Pro에서 원본 미디어를 찾는 데 사용됩니다.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">클립 간격</label>
            <select
              value={clipGapMs}
              onChange={(e) => setClipGapMs(Number(e.target.value))}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none"
            >
              <option value={0}>없음</option>
              <option value={1000}>1초</option>
            </select>
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeMarkers}
              onChange={(e) => setIncludeMarkers(e.target.checked)}
            />
            마커 포함
          </label>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeTranscriptMarkers}
              onChange={(e) => setIncludeTranscriptMarkers(e.target.checked)}
            />
            자막 마커 포함
          </label>

          {error && <p className="text-sm text-red-600">{error}</p>}
          {success && <p className="text-sm text-green-600">{success}</p>}

          <button
            type="button"
            onClick={handleExport}
            disabled={loading}
            className="w-full bg-primary-600 text-white py-2.5 rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading && (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                />
              </svg>
            )}
            Premiere 내보내기 패키지 다운로드 (.zip)
          </button>
        </div>
      </div>
    </div>
  );
}
