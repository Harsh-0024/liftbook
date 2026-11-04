"""workout dates in local time: move workouts stamped with the server's UTC clock to local time

Workouts saved without a written date used to get the server's clock (UTC). They now get
local time (APP_TIMEZONE, India by default), so the old ones move forward by the zone's
offset (5h30 for India). Workouts with a written date (saved as midnight) don't move.
Run scripts/preview_workout_time_fix.py first to see what changes.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-04
"""

from alembic import op

from services.workout_time_fix import apply_shift, plan_shift
from utils.dates import app_timezone


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    apply_shift(connection, plan_shift(connection, app_timezone()))


def downgrade() -> None:
    # Not undone: once shifted, an old row can't be told from one saved in local time
    # since. The nightly backup holds the dates as they were.
    pass
