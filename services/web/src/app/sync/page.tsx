"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "@/lib/auth";
import { getDevices } from "@/lib/api/devices";
import { createFolderIntent } from "@/lib/api/agent-intents";
import { AuthGuard } from "@/components/AuthGuard";
import { SyncSourceCard } from "@/components/sync/SyncSourceCard";
import { UploadProgress } from "@/components/sync/UploadProgress";
import { StopConfirmDialog } from "@/components/sync/StopConfirmDialog";
import type { DeviceListItem } from "@/lib/types";

type UploadState = "hidden" | "uploading" | "paused" | "complete";

const SYNC_SOURCES = ["클라우드", "외장하드", "로컬 파일", "수동 파일"] as const;

function SyncContent() {
  const { getAccessToken } = useAuth();
  const [uploadState, setUploadState] = useState<UploadState>("hidden");
  const [progress, setProgress] = useState(0);
  const [showStopDialog, setShowStopDialog] = useState(false);
  const [devices, setDevices] = useState<DeviceListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    async function loadDevices() {
      try {
        const res = await getDevices(getAccessToken);
        setDevices(res.devices.filter((d) => !d.is_revoked));
      } catch {
        setDevices([]);
      }
    }
    loadDevices();
  }, [getAccessToken]);

  const clearUploadInterval = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (uploadState === "uploading") {
      intervalRef.current = setInterval(() => {
        setProgress((prev) => {
          if (prev >= 100) {
            clearUploadInterval();
            setUploadState("complete");
            return 100;
          }
          return prev + 1;
        });
      }, 200);
    } else {
      clearUploadInterval();
    }
    return clearUploadInterval;
  }, [uploadState, clearUploadInterval]);

  const handleStartUpload = useCallback(async () => {
    if (uploadState !== "hidden") return;
    setError(null);

    if (devices.length === 0) {
      setError("등록된 디바이스가 없습니다. 설정 > 디바이스에서 먼저 디바이스를 등록해주세요.");
      return;
    }

    try {
      const device = devices[0];
      const intent = await createFolderIntent(getAccessToken, device.device_id);

      window.open(intent.deep_link_url, "_blank");

      setProgress(0);
      setUploadState("uploading");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "인텐트 생성에 실패했습니다.";
      setError(message);
    }
  }, [uploadState, devices, getAccessToken]);

  const handlePause = useCallback(() => setUploadState("paused"), []);
  const handleResume = useCallback(() => setUploadState("uploading"), []);

  const handleStopRequest = useCallback(() => setShowStopDialog(true), []);
  const handleStopCancel = useCallback(() => setShowStopDialog(false), []);
  const handleStopConfirm = useCallback(() => {
    clearUploadInterval();
    setUploadState("hidden");
    setProgress(0);
    setShowStopDialog(false);
  }, [clearUploadInterval]);

  const handleCloseComplete = useCallback(() => {
    setUploadState("hidden");
    setProgress(0);
  }, []);

  const isUploading = uploadState !== "hidden" && uploadState !== "complete";

  return (
    <div className="mx-auto max-w-5xl pt-12">
      <div className="mb-12 text-center">
        <h1 className="text-2xl font-bold text-gray-900">
          파일 추가 방식을 선택해 주세요.
        </h1>
        <p className="mt-3 text-gray-500">
          영상이 위치해있는 곳들을 선택하여 업데이트 할 수 있습니다.
        </p>
      </div>

      {error && (
        <div className="mx-auto mb-6 max-w-2xl rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {SYNC_SOURCES.map((source) => (
          <SyncSourceCard
            key={source}
            title={source}
            onUpdate={handleStartUpload}
            isUploading={isUploading}
          />
        ))}
      </div>

      <UploadProgress
        state={uploadState}
        progress={progress}
        onStop={handleStopRequest}
        onPause={handlePause}
        onResume={handleResume}
        onClose={handleCloseComplete}
      />

      <StopConfirmDialog
        isOpen={showStopDialog}
        onCancel={handleStopCancel}
        onConfirm={handleStopConfirm}
      />
    </div>
  );
}

export default function SyncPage() {
  return (
    <AuthGuard>
      <SyncContent />
    </AuthGuard>
  );
}
