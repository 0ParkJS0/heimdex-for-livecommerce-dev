"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { getCloudThumbnailUrl, getFaceThumbnailUrl } from "@/lib/agent";
import { PersonIcon } from "@/components/icons";
import type { PersonResponse } from "@/lib/types";

/** Thumbnail content shared between PersonAvatar and DragOverlay */
export function AvatarThumbnail({
  person,
  agentAvailable,
  className,
  onClick,
  cacheBuster,
}: {
  person: PersonResponse;
  agentAvailable: boolean;
  className?: string;
  onClick?: () => void;
  cacheBuster?: number;
}) {
  const [imgError, setImgError] = useState(false);
  const faceThumbnailUrl = getFaceThumbnailUrl(person.person_cluster_id, cacheBuster);
  const sceneThumbnailUrl =
    person.representative_video_id && person.representative_scene_id
      ? getCloudThumbnailUrl(person.representative_video_id, person.representative_scene_id)
      : null;
  const [useFallback, setUseFallback] = useState(false);
  const thumbnailUrl = !useFallback ? faceThumbnailUrl : sceneThumbnailUrl;
  const isCustom = person.thumbnail_source && person.thumbnail_source !== "auto";

  return (
    <div
      className={cn(
        "relative flex h-24 w-24 items-center justify-center overflow-hidden rounded-2xl bg-gray-100 transition-all group-hover:brightness-90",
        onClick && "cursor-pointer",
        className,
      )}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter") onClick(); } : undefined}
    >
      {thumbnailUrl && !imgError ? (
        <img
          src={thumbnailUrl}
          alt={person.label ?? "인물"}
          className="h-full w-full object-cover"
          onError={() => {
            if (!useFallback && sceneThumbnailUrl) {
              setUseFallback(true);
            } else {
              setImgError(true);
            }
          }}
        />
      ) : (
        <div className="relative flex h-full w-full items-center justify-center">
          <PersonIcon className="h-12 w-12 text-gray-400" />
          {!agentAvailable && (
            <span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-gray-500/80 px-1.5 py-0.5 text-[8px] font-medium leading-tight text-white">
              오프라인
            </span>
          )}
        </div>
      )}
      {onClick && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-all hover:bg-black/20 hover:opacity-100">
          <svg className="h-5 w-5 text-white drop-shadow" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
          </svg>
        </div>
      )}
      {isCustom && (
        <span className="absolute bottom-1 right-1 rounded-full bg-indigo-500 px-1 py-0.5 text-[7px] font-bold leading-tight text-white">
          {person.thumbnail_source === "upload" ? "UP" : "SEL"}
        </span>
      )}
    </div>
  );
}
