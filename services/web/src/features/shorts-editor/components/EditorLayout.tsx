"use client";

import type { ReactNode } from "react";

interface EditorLayoutProps {
  preview: ReactNode;
  timeline: ReactNode;
  properties: ReactNode;
}

export function EditorLayout({ preview, timeline, properties }: EditorLayoutProps) {
  return (
    <div className="grid h-[calc(100vh-64px)] grid-cols-[1fr_320px] grid-rows-[1fr_200px] gap-0 overflow-hidden">
      {/* Preview panel — top left */}
      <div className="overflow-hidden border-r border-gray-200 bg-gray-950 flex items-center justify-center">
        {preview}
      </div>

      {/* Properties panel — top right */}
      <div className="overflow-y-auto border-b border-gray-200 bg-white">
        {properties}
      </div>

      {/* Timeline panel — bottom, full width */}
      <div className="col-span-2 overflow-hidden border-t border-gray-200 bg-gray-50">
        {timeline}
      </div>
    </div>
  );
}
