"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export interface TopHeaderBackSlot {
  label: string;
  onClick: () => void;
}

// Unsaved-changes guard. When the editor registers ``shouldIntercept`` /
// ``onIntercept``, LNB link clicks pass through ``attemptNavigate``; while dirty
// it blocks the default navigation and raises the UnsavedExitDialog. With no
// registrant it always allows navigation.
export interface NavGuard {
  shouldIntercept: () => boolean;
  onIntercept: (href: string) => void;
}

interface TopHeaderActionsContextValue {
  actions: ReactNode | null;
  setActions: (node: ReactNode | null) => void;
  leftActions: ReactNode | null;
  setLeftActions: (node: ReactNode | null) => void;
  back: TopHeaderBackSlot | null;
  setBack: (slot: TopHeaderBackSlot | null) => void;
  setNavGuard: (guard: NavGuard | null) => void;
  attemptNavigate: (href: string) => boolean;
}

export const TopHeaderActionsContext =
  createContext<TopHeaderActionsContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
}

export function TopHeaderActionsProvider({ children }: ProviderProps) {
  const [actions, setActionsState] = useState<ReactNode | null>(null);
  const [leftActions, setLeftActionsState] = useState<ReactNode | null>(null);
  const [back, setBackState] = useState<TopHeaderBackSlot | null>(null);
  // Held in a ref so ``attemptNavigate`` stays referentially stable for the
  // LNB while still reading the latest guard the editor registered.
  const navGuardRef = useRef<NavGuard | null>(null);

  const setActions = useCallback((node: ReactNode | null) => {
    setActionsState(node);
  }, []);

  const setLeftActions = useCallback((node: ReactNode | null) => {
    setLeftActionsState(node);
  }, []);

  const setBack = useCallback((slot: TopHeaderBackSlot | null) => {
    setBackState(slot);
  }, []);

  const setNavGuard = useCallback((guard: NavGuard | null) => {
    navGuardRef.current = guard;
  }, []);

  // Returns false when the active guard intercepted the navigation (the LNB
  // link should then preventDefault); true means the caller may navigate.
  const attemptNavigate = useCallback((href: string) => {
    const guard = navGuardRef.current;
    if (guard && guard.shouldIntercept()) {
      guard.onIntercept(href);
      return false;
    }
    return true;
  }, []);

  const value = useMemo(
    () => ({
      actions,
      setActions,
      leftActions,
      setLeftActions,
      back,
      setBack,
      setNavGuard,
      attemptNavigate,
    }),
    [
      actions,
      setActions,
      leftActions,
      setLeftActions,
      back,
      setBack,
      setNavGuard,
      attemptNavigate,
    ],
  );

  return (
    <TopHeaderActionsContext.Provider value={value}>
      {children}
    </TopHeaderActionsContext.Provider>
  );
}

// Mounts `node` into the TopHeader's actions slot for the lifetime of the
// caller component. Cleared on unmount so route-specific menus don't leak
// into other pages.
export function useTopHeaderActions(node: ReactNode | null): void {
  const ctx = useContext(TopHeaderActionsContext);

  useEffect(() => {
    if (!ctx) return;
    ctx.setActions(node);
    return () => {
      ctx.setActions(null);
    };
  }, [ctx, node]);
}

// Mounts a back-button slot (label + onClick) into the TopHeader's leftmost
// area. Cleared on unmount.
export function useTopHeaderBack(slot: TopHeaderBackSlot | null): void {
  const ctx = useContext(TopHeaderActionsContext);

  useEffect(() => {
    if (!ctx) return;
    ctx.setBack(slot);
    return () => {
      ctx.setBack(null);
    };
  }, [ctx, slot]);
}

// Mounts `node` next to the back slot on the TopHeader's left side, used by
// editor-style routes that need title/metadata alongside the back button.
// Cleared on unmount.
export function useTopHeaderLeftActions(node: ReactNode | null): void {
  const ctx = useContext(TopHeaderActionsContext);

  useEffect(() => {
    if (!ctx) return;
    ctx.setLeftActions(node);
    return () => {
      ctx.setLeftActions(null);
    };
  }, [ctx, node]);
}

// Registers a navigation guard for the lifetime of the caller (the editor).
// While mounted, LNB link clicks consult it via ``attemptNavigate`` so a
// dirty editor can intercept and surface the unsaved-changes dialog instead
// of letting the route change silently. Cleared on unmount.
export function useRegisterNavGuard(guard: NavGuard | null): void {
  const ctx = useContext(TopHeaderActionsContext);

  useEffect(() => {
    if (!ctx) return;
    ctx.setNavGuard(guard);
    return () => {
      ctx.setNavGuard(null);
    };
  }, [ctx, guard]);
}

// Returns the ``attemptNavigate`` callback used by LNB links. Outside a
// provider (e.g. isolated component tests) it resolves to a no-op that always
// permits navigation.
export function useAttemptNavigate(): (href: string) => boolean {
  const ctx = useContext(TopHeaderActionsContext);
  return ctx ? ctx.attemptNavigate : ALWAYS_ALLOW;
}

const ALWAYS_ALLOW = (): boolean => true;
