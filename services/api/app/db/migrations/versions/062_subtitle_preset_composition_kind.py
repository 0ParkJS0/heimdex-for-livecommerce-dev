"""subtitle_presets.kind allows 'composition'

Revision ID: 062_subtitle_preset_composition
Revises: 061_add_editor_projects
Create Date: 2026-05-24

Existing CHECK constraint restricted kind to ('text', 'background').
PresetKind now includes 'composition' for full-canvas templates
(subtitle style + overlays + letterbox + video transform); the
constraint is widened to match. Down-revision reverts to the original
two-kind set.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "062_subtitle_preset_composition"
down_revision: str | None = "061_add_editor_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_subtitle_presets_kind", "subtitle_presets", type_="check")
    op.create_check_constraint(
        "ck_subtitle_presets_kind",
        "subtitle_presets",
        "kind IN ('text', 'background', 'composition')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_subtitle_presets_kind", "subtitle_presets", type_="check")
    op.create_check_constraint(
        "ck_subtitle_presets_kind",
        "subtitle_presets",
        "kind IN ('text', 'background')",
    )
