"use client";

import { useRef, useState } from "react";

import { ColorPalettePopover } from "../primitives/ColorPalettePopover";
import { ColorPalettePortal } from "../primitives/ColorPalettePortal";
import { ImageIcon, PlusIcon } from "../primitives/icons";
import { t } from "../../lib/i18n/strings";
import type { EditorOverlayKind } from "../../lib/overlay-types";
import type { EditorState } from "../../lib/types";

interface ActionBarProps {
  kind: EditorOverlayKind;
  onAddText: () => void;
  // Figma 2015:249496 (배경 패널) — single-bg add is removed; the
  // primary button now adds a letterbox. Prop kept on the interface
  // for back-compat with text-tab callers that still pass a no-op.
  onAddBackground?: (fillColor: string) => void;
  // "Insert image" — receives the data URL of the picked file. When
  // omitted (e.g., text tab) the image button is hidden.
  onAddImage?: (dataUrl: string) => void;
  // Figma 2015:249496 annotation = "단색 배경 추가 삭제, 레터박스
  // 추가로 교체." On the background tab the primary action button
  // creates/updates a global letterbox via this callback.
  letterbox?: EditorState["letterbox"];
  onSetLetterbox?: (letterbox: EditorState["letterbox"]) => void;
}

const DEFAULT_BG_FILL = "#000000";
// 14% top and bottom — matches the spec's reference (a centered
// landscape clip inside a 9:16 frame leaves roughly 14% black above
// and below). Operators can drag the ChevronsUpDown handle in the
// canvas to fine-tune the height after the bars appear.
const DEFAULT_LETTERBOX_HEIGHT_PCT = 14;
const DEFAULT_LETTERBOX_FILL = "#000000";
// File picker accepts MIME types; spelled out so unsupported types
// (.heic, .tiff) don't slip through and surprise the renderer.
const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif,image/svg+xml";

/**
 * Top action row for the overlay panel.
 *
 * Text tab: [+ 텍스트 추가]
 * Background tab: [+ 단색 배경 추가] [이미지 삽입]
 *
 * "+ 단색 배경 추가" opens the ColorPalettePopover (figma 1602:41332)
 * anchored under the button — the picked color is used as the new
 * overlay's fillColor.
 *
 * "이미지 삽입" surfaces a hidden ``<input type="file">`` whose change
 * handler reads the picked file as a data URL and forwards it via
 * onAddImage. The image lands as a new background overlay with the
 * image painted on top of a transparent fill, with full transform /
 * effects controls available in the rest of the panel.
 */
export function ActionBar({
  kind,
  onAddText,
  onAddImage,
  letterbox,
  onSetLetterbox,
}: ActionBarProps) {
  // The popover under the primary button on the background tab is now
  // the letterbox color picker (was the single-background fill picker
  // pre-Figma 2015:249496). Same component, different sink.
  const [pickerOpen, setPickerOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const handleLetterboxColorChange = (next: string) => {
    if (!onSetLetterbox) return;
    const fillColor = next.toUpperCase();
    if (letterbox) {
      onSetLetterbox({ ...letterbox, fillColor });
    } else {
      onSetLetterbox({
        topHeightPct: DEFAULT_LETTERBOX_HEIGHT_PCT,
        bottomHeightPct: DEFAULT_LETTERBOX_HEIGHT_PCT,
        fillColor,
        borderColor: null,
        borderWidthPx: 5,
      });
    }
    setPickerOpen(false);
  };

  const handleLetterboxRemove = () => {
    if (!onSetLetterbox) return;
    onSetLetterbox(undefined);
    setPickerOpen(false);
  };

  const handleAddClick = () => {
    if (kind === "text") {
      onAddText();
    } else {
      // Background tab: primary button now opens the letterbox color
      // picker (single-bg add was removed per Figma 2015:249496).
      setPickerOpen((v) => !v);
    }
  };

  const handleImageClick = () => {
    imageInputRef.current?.click();
  };

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // Reset the input so picking the same file twice still fires a
    // change event; otherwise the second pick is silently dropped.
    e.target.value = "";
    if (!file || !onAddImage) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") onAddImage(reader.result);
    };
    reader.readAsDataURL(file);
  };

  return (
    <div className="flex items-stretch gap-2">
      <div className="relative flex flex-1">
        <button
          ref={triggerRef}
          type="button"
          onClick={handleAddClick}
          aria-haspopup={kind === "background" ? "dialog" : undefined}
          aria-expanded={kind === "background" ? pickerOpen : undefined}
          // figma 2015:249496 — primary button: rounded-[8px] h-[36px]
          className="flex flex-1 items-center justify-center gap-1.5 rounded-[8px] bg-heimdex-navy-500 px-3 py-2 text-[14px] font-semibold text-white transition-colors hover:bg-heimdex-navy-600"
        >
          <PlusIcon />
          {kind === "text" ? t.actions.addText : t.actions.letterbox}
        </button>
        {kind === "background" && pickerOpen && onSetLetterbox && (
          <ColorPalettePortal anchorRef={triggerRef} onClose={() => setPickerOpen(false)}>
            <ColorPalettePopover
              color={letterbox?.fillColor ?? DEFAULT_LETTERBOX_FILL}
              onChange={handleLetterboxColorChange}
              onClose={() => setPickerOpen(false)}
              showOpacity={false}
            />
            {letterbox && (
              <button
                type="button"
                onClick={handleLetterboxRemove}
                className="mt-2 w-full rounded-md border border-grayscale-200 px-3 py-1.5 text-xs font-medium text-grayscale-700 transition-colors hover:bg-grayscale-50"
              >
                {t.actions.removeLetterbox}
              </button>
            )}
          </ColorPalettePortal>
        )}
      </div>

      {kind === "background" && (
        <>
          <button
            type="button"
            onClick={handleImageClick}
            aria-label={t.actions.insertImage}
            // figma 2015:249496 — secondary button: rounded-[8px] h-[36px] border-neutral-500 text-neutral-500
            className="flex items-center justify-center gap-1.5 rounded-[8px] border border-neutral-h-500 px-3 py-2 text-[14px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-50"
          >
            <ImageIcon />
            {t.actions.insertImage}
          </button>
          <input
            ref={imageInputRef}
            type="file"
            accept={IMAGE_ACCEPT}
            onChange={handleImageChange}
            className="sr-only"
            aria-hidden
            tabIndex={-1}
          />
        </>
      )}
    </div>
  );
}
