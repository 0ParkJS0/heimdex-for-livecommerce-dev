/**
 * Feature-flag accessors for the web service.
 *
 * Flags ride on `NEXT_PUBLIC_*` env vars so client components can read them.
 * They are baked into the JS bundle at build time — flipping a flag means
 * rebuilding the web container, not a runtime config change.
 *
 * Strict-string parsing: only the literal "true" turns a flag on. Empty,
 * undefined, "false", "0", anything else → off.
 *
 * 2026-05-22 cleanup — `isShortsEditorV2Enabled` and the legacy
 * `TextOverlayPanel` were removed. The V2 OverlayPanel is now the only
 * render path; `NEXT_PUBLIC_EXPORT_SHORTS_EDITOR_V2_ENABLED` env var is
 * intentionally ignored (kept in docker-compose for one more release
 * window so a rollback build doesn't fail on a missing build arg).
 *
 * Reintroduce this module's exports when the next feature flag lands.
 */

export {};
