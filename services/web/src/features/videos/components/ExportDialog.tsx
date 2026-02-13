"use client";

import { FormEvent, useEffect, useState } from "react";

interface ExportDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onExport: (config: {
    projectName: string;
    outputDir: string;
    frameRate: number;
  }) => void;
  selectedCount: number;
  isExporting: boolean;
  defaultProjectName: string;
}

const FRAME_RATE_OPTIONS = [24, 25, 29.97, 30, 60];

export function ExportDialog({
  isOpen,
  onClose,
  onExport,
  selectedCount,
  isExporting,
  defaultProjectName,
}: ExportDialogProps) {
  const [projectName, setProjectName] = useState(defaultProjectName);
  const [outputDir, setOutputDir] = useState("");
  const [frameRate, setFrameRate] = useState(29.97);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) return;
    setProjectName(defaultProjectName);
  }, [defaultProjectName, isOpen]);

  if (!isOpen) {
    return null;
  }

  const isSubmitDisabled =
    isExporting || projectName.trim().length === 0 || outputDir.trim().length === 0;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitDisabled) return;
    onExport({
      projectName: projectName.trim(),
      outputDir: outputDir.trim(),
      frameRate,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Close export dialog"
      />
      <div className="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-md">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Export to Premiere Pro</h3>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="export-project-name" className="block text-sm font-medium text-gray-700 mb-1">
              Project Name
            </label>
            <input
              id="export-project-name"
              className="input-field"
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              required
            />
          </div>

          <div>
            <label htmlFor="export-output-dir" className="block text-sm font-medium text-gray-700 mb-1">
              Output Directory
            </label>
            <input
              id="export-output-dir"
              className="input-field"
              value={outputDir}
              onChange={(event) => setOutputDir(event.target.value)}
              placeholder="/Users/you/exports"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Format</label>
            <p className="text-sm text-gray-700">EDL (CMX 3600)</p>
          </div>

          <div>
            <label htmlFor="export-frame-rate" className="block text-sm font-medium text-gray-700 mb-1">
              Frame Rate
            </label>
            <select
              id="export-frame-rate"
              className="input-field"
              value={frameRate}
              onChange={(event) => setFrameRate(Number(event.target.value))}
            >
              {FRAME_RATE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Clips</label>
            <p className="text-sm text-gray-700">{selectedCount} clips selected</p>
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 border border-gray-200 rounded-lg hover:bg-gray-50"
              onClick={onClose}
              disabled={isExporting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={isSubmitDisabled}
            >
              {isExporting ? "Exporting..." : "Export"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
