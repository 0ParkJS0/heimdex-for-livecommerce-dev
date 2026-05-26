/**
 * TemplatePanel ActionRow trash button — figma 2107:410711 / 2015:246806.
 *
 * Pins the operator-confirmed delete affordance next to 적용하기:
 *   * onDelete 가 전달되지 않으면 휴지통 자체가 렌더되지 않는다.
 *   * 선택이 없으면 disabled, 클릭해도 onDelete 가 발화하지 않는다.
 *   * 선택이 있으면 enabled, 클릭 시 onDelete(selected) 가 한 번 호출된다.
 */

import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";

import { TemplatePanel } from "../components/TemplatePanel";
import type { WirePreset } from "../lib/overlay-types";

function makePreset(overrides: Partial<WirePreset> = {}): WirePreset {
  return {
    id: "preset_1",
    org_id: "org_test",
    user_id: "user_test",
    name: "테스트 템플릿",
    kind: "text",
    style_json: {},
    is_shared: false,
    is_owned: true,
    created_at: "2026-05-26T00:00:00Z",
    updated_at: "2026-05-26T00:00:00Z",
    ...overrides,
  };
}

describe("TemplatePanel — ActionRow trash button", () => {
  it("does not render the trash button when onDelete is omitted", () => {
    const { queryByTestId } = render(
      <TemplatePanel
        presets={[makePreset()]}
        selectedId={null}
        onSelect={() => {}}
        onApply={() => {}}
        onOpenSaveDialog={() => {}}
      />,
    );
    expect(queryByTestId("template-action-delete")).toBeNull();
  });

  it("renders the trash button disabled when nothing is selected", () => {
    const onDelete = vi.fn();
    const { getByTestId } = render(
      <TemplatePanel
        presets={[makePreset()]}
        selectedId={null}
        onSelect={() => {}}
        onApply={() => {}}
        onOpenSaveDialog={() => {}}
        onDelete={onDelete}
      />,
    );
    const btn = getByTestId("template-action-delete") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("fires onDelete(selected) once when clicked with a selection", () => {
    const onDelete = vi.fn();
    const preset = makePreset({ id: "preset_42", name: "내 템플릿" });
    const { getByTestId } = render(
      <TemplatePanel
        presets={[preset]}
        selectedId="preset_42"
        onSelect={() => {}}
        onApply={() => {}}
        onOpenSaveDialog={() => {}}
        onDelete={onDelete}
      />,
    );
    const btn = getByTestId("template-action-delete") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith(preset);
  });
});
