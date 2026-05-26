/**
 * Editor exit/save dialogs — UnsavedExitDialog (figma 2105:410610 /
 * 2107:410657) + RenderCompleteDialog (figma 2107:410685).
 *
 * Covers the operator-confirmed 3-button matrix for each variant and
 * the success dialog's 2-button confirmation. The actual integration
 * (when each dialog opens, what action is wired to what button) is
 * driven by ShortsEditorPage; this file pins the dialog primitives so
 * a future refactor doesn't silently flip the copy or remove a button.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { RenderCompleteDialog } from "../components/RenderCompleteDialog";
import {
  UnsavedExitDialog,
  type UnsavedExitVariant,
} from "../components/UnsavedExitDialog";

describe("RenderCompleteDialog — figma 2107:410685", () => {
  it("renders both action buttons with operator-confirmed copy", () => {
    render(
      <RenderCompleteDialog
        open
        onContinueEditing={() => {}}
        onGoToShorts={() => {}}
      />,
    );
    expect(screen.getByText("저장이 완료되었습니다")).toBeTruthy();
    expect(
      screen.getByText("계속 편집하시겠어요, 아니면 내 쇼츠로 이동하시겠어요?"),
    ).toBeTruthy();
    expect(screen.getByTestId("render-complete-continue")).toBeTruthy();
    expect(screen.getByTestId("render-complete-go-to-shorts")).toBeTruthy();
  });

  it("does not render when open=false", () => {
    render(
      <RenderCompleteDialog
        open={false}
        onContinueEditing={() => {}}
        onGoToShorts={() => {}}
      />,
    );
    expect(screen.queryByTestId("render-complete-dialog")).toBeNull();
  });

  it("fires onContinueEditing on the secondary button", () => {
    const onContinueEditing = vi.fn();
    const onGoToShorts = vi.fn();
    render(
      <RenderCompleteDialog
        open
        onContinueEditing={onContinueEditing}
        onGoToShorts={onGoToShorts}
      />,
    );
    fireEvent.click(screen.getByTestId("render-complete-continue"));
    expect(onContinueEditing).toHaveBeenCalledTimes(1);
    expect(onGoToShorts).not.toHaveBeenCalled();
  });

  it("fires onGoToShorts on the primary button", () => {
    const onContinueEditing = vi.fn();
    const onGoToShorts = vi.fn();
    render(
      <RenderCompleteDialog
        open
        onContinueEditing={onContinueEditing}
        onGoToShorts={onGoToShorts}
      />,
    );
    fireEvent.click(screen.getByTestId("render-complete-go-to-shorts"));
    expect(onGoToShorts).toHaveBeenCalledTimes(1);
    expect(onContinueEditing).not.toHaveBeenCalled();
  });
});

describe("UnsavedExitDialog — figma 2105:410610 / 2107:410657", () => {
  const cases: Array<{
    variant: UnsavedExitVariant;
    title: string;
    bodyLine: string;
  }> = [
    {
      variant: "new",
      title: "저장하지 않고 나가시겠어요?",
      bodyLine: "저장하지 않으면 작업한 내용이 모두 삭제되며,",
    },
    {
      variant: "existing",
      title: "변경사항을 저장하시겠어요?",
      bodyLine: "저장하지 않으면 마지막 저장 이후 변경한",
    },
  ];

  it.each(cases)(
    "renders the $variant variant with the matching copy",
    ({ variant, title, bodyLine }) => {
      render(
        <UnsavedExitDialog
          open
          variant={variant}
          onCancel={() => {}}
          onDiscard={() => {}}
          onSaveAndExit={() => {}}
        />,
      );
      expect(screen.getByText(title)).toBeTruthy();
      expect(screen.getByText(bodyLine)).toBeTruthy();
      const dialog = screen.getByTestId("unsaved-exit-dialog");
      expect(dialog.getAttribute("data-variant")).toBe(variant);
    },
  );

  it("does not render when open=false", () => {
    render(
      <UnsavedExitDialog
        open={false}
        variant="new"
        onCancel={() => {}}
        onDiscard={() => {}}
        onSaveAndExit={() => {}}
      />,
    );
    expect(screen.queryByTestId("unsaved-exit-dialog")).toBeNull();
  });

  it("exposes all three actions and routes each to its handler", () => {
    const onCancel = vi.fn();
    const onDiscard = vi.fn();
    const onSaveAndExit = vi.fn();
    render(
      <UnsavedExitDialog
        open
        variant="existing"
        onCancel={onCancel}
        onDiscard={onDiscard}
        onSaveAndExit={onSaveAndExit}
      />,
    );

    fireEvent.click(screen.getByTestId("unsaved-exit-cancel"));
    fireEvent.click(screen.getByTestId("unsaved-exit-discard"));
    fireEvent.click(screen.getByTestId("unsaved-exit-save"));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(onSaveAndExit).toHaveBeenCalledTimes(1);
  });
});
