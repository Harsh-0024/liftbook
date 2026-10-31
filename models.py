"""
Database models for the Liftbook application.
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float, ForeignKey, Index, Boolean, Enum, LargeBinary, event
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session, relationship
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy_utils import JSONType
from datetime import datetime
import os
from config import Config
from list_of_exercise import list_of_exercises, DEFAULT_REP_RANGES
import enum

# --- DATABASE CONNECTION ---
database_url = Config.get_database_url()

connect_args = {}
if isinstance(database_url, str) and database_url.startswith("postgresql://"):
    connect_args = {
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }

# Enable connection pooling and better error handling
engine = create_engine(
    database_url,
    connect_args=connect_args,
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600,   # Recycle connections after 1 hour
    echo=False
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    if not isinstance(database_url, str) or not database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)
Base = declarative_base()


# --- USER ROLE ENUM ---
class UserRole(enum.Enum):
    USER = "user"
    ADMIN = "admin"


# --- 1. USERS TABLE ---
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(100), nullable=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(
        Enum(
            UserRole,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            native_enum=False,
        ),
        default=UserRole.USER,
        nullable=False,
    )
    is_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String(255), nullable=True)
    verification_token_expires = Column(DateTime, nullable=True)
    otp_code = Column(String(10), nullable=True)
    otp_purpose = Column(String(32), nullable=True)
    otp_expires = Column(DateTime, nullable=True)
    bodyweight = Column(Float, nullable=True)
    profile_image = Column(String(255), nullable=True)
    # New accounts follow the main admin's plan and rep ranges until they switch it off.
    follow_admin_plan = Column(Boolean, default=True, nullable=False)
    follow_admin_exercises = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)

    lifts = relationship("Lift", back_populates="user", cascade="all, delete-orphan")
    plan = relationship("Plan", uselist=False, back_populates="user", cascade="all, delete-orphan")
    rep_ranges = relationship("RepRange", uselist=False, back_populates="user", cascade="all, delete-orphan")
    shortcut_key_map = relationship("ShortcutKeyMap", uselist=False, back_populates="user", cascade="all, delete-orphan")
    logs = relationship("WorkoutLog", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("UserApiKey", back_populates="user", cascade="all, delete-orphan")
    bodyweight_preferences = relationship("BodyweightExercisePreference", back_populates="user", cascade="all, delete-orphan")
    custom_retrieval_events = relationship("CustomRetrievalEvent", back_populates="user", cascade="all, delete-orphan")
    custom_retrieval_preference = relationship("CustomRetrievalPreference", uselist=False, back_populates="user", cascade="all, delete-orphan")
    stats_preference = relationship("StatsPreference", uselist=False, back_populates="user", cascade="all, delete-orphan")
    stats_exercise_views = relationship("StatsExerciseView", back_populates="user", cascade="all, delete-orphan")
    exercise_groups = relationship("ExerciseGroupChoice", back_populates="user", cascade="all, delete-orphan")
    exercise_renames = relationship("ExerciseRename", back_populates="user", cascade="all, delete-orphan")

    def is_admin(self):
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN
    
    def get_id(self):
        """Flask-Login integration: return user ID as string."""
        return str(self.id)
    
    @property
    def is_authenticated(self):
        """Flask-Login integration: return True if user is authenticated."""
        return True
    
    @property
    def is_active(self):
        """Flask-Login integration: return True if user account is active."""
        return self.is_verified
    
    @property
    def is_anonymous(self):
        """Flask-Login integration: return False for regular users."""
        return False
    
    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role={self.role.value})>"


# --- EMAIL VERIFICATIONS TABLE ---
class EmailVerification(Base):
    __tablename__ = 'email_verifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    purpose = Column(String(32), nullable=False, index=True)
    code = Column(String(10), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)


# --- USER API KEYS TABLE ---
class UserApiKey(Base):
    __tablename__ = 'user_api_keys'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    account_label = Column(String(100), nullable=True)
    api_key = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="api_keys")

    def __repr__(self):
        return f"<UserApiKey(id={self.id}, user_id={self.user_id}, active={self.is_active})>"


# --- 2. LIFTS TABLE (PR Tracker) ---
class Lift(Base):
    __tablename__ = 'lifts'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    exercise = Column(String(100), nullable=False, index=True)
    best_log_id = Column(Integer, ForeignKey('workout_logs.id', ondelete='SET NULL'), nullable=True, index=True)

    user = relationship("User", back_populates="lifts")
    best_log = relationship("WorkoutLog", foreign_keys=[best_log_id], passive_deletes=True)
    
    # Composite index for faster lookups
    __table_args__ = (
        Index('idx_user_exercise', 'user_id', 'exercise'),
    )
    
    def __repr__(self):
        return f"<Lift(id={self.id}, user_id={self.user_id}, exercise='{self.exercise}', best_log_id={self.best_log_id})>"


# --- 3. PLANS TABLE ---
class Plan(Base):
    __tablename__ = 'plans'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    text_content = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("User", back_populates="plan")
    
    def __repr__(self):
        return f"<Plan(id={self.id}, user_id={self.user_id})>"


# --- 4. REP RANGES TABLE ---
class RepRange(Base):
    __tablename__ = 'rep_ranges'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    text_content = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("User", back_populates="rep_ranges")
    
    def __repr__(self):
        return f"<RepRange(id={self.id}, user_id={self.user_id})>"


# --- 4B. SHORTCUT KEY MAPPINGS TABLE ---
class ShortcutKeyMap(Base):
    __tablename__ = 'shortcut_key_maps'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    text_content = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("User", back_populates="shortcut_key_map")

    def __repr__(self):
        return f"<ShortcutKeyMap(id={self.id}, user_id={self.user_id})>"


# --- 5. HISTORY TABLE (New) ---
class WorkoutLog(Base):
    __tablename__ = 'workout_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    date = Column(DateTime, default=datetime.now, nullable=False, index=True)
    workout_name = Column(String(100), nullable=True, index=True)
    exercise = Column(String(100), nullable=False, index=True)
    exercise_string = Column(Text)
    sets_json = Column(JSONType)
    bodyweight = Column(Float)
    uses_bodyweight = Column(Boolean, nullable=True)
    top_weight = Column(Float)  # Heaviest weight moved that day
    top_reps = Column(Integer)  # Reps at that top weight
    estimated_1rm = Column(Float, index=True)  # Calculated strength metric

    user = relationship("User", back_populates="logs")
    
    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_user_date', 'user_id', 'date'),
        Index('idx_user_exercise_date', 'user_id', 'exercise', 'date'),
    )
    
    def __repr__(self):
        return f"<WorkoutLog(id={self.id}, user_id={self.user_id}, exercise='{self.exercise}', date={self.date})>"

    @staticmethod
    def _format_value(value):
        if value is None:
            return ""
        try:
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
        except Exception:
            pass
        return f"{value:g}" if isinstance(value, float) else str(value)

    @property
    def sets_display(self):
        trimmed = None
        if self.exercise_string:
            trimmed = self.exercise_string.strip()
            if trimmed.lower().startswith(self.exercise.lower()):
                trimmed = trimmed[len(self.exercise):].strip()
                trimmed = trimmed.lstrip("-:").strip()
            if trimmed and 'bw' in trimmed.lower():
                return trimmed

        if self.sets_json and isinstance(self.sets_json, dict):
            weights = self.sets_json.get('weights') or []
            reps = self.sets_json.get('reps') or []
            pairs = [
                f"{self._format_value(w)} x {int(r)}" for w, r in zip(weights, reps)
                if w is not None and r is not None
            ]
            if pairs:
                return ", ".join(pairs)

        if trimmed:
            return trimmed or None

        if self.top_weight and self.top_reps:
            return f"{self._format_value(self.top_weight)} x {self.top_reps}"

        return None


# --- 5B. TIMED EXERCISE USER PREFERENCES ---
class TimedExercisePreference(Base):
    __tablename__ = 'timed_exercise_preferences'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    exercise_key = Column(String(160), nullable=False, index=True)
    is_timed = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        Index('idx_user_exercise_timed_pref', 'user_id', 'exercise_key', unique=True),
    )

    def __repr__(self):
        return (
            f"<TimedExercisePreference(id={self.id}, user_id={self.user_id}, "
            f"exercise_key='{self.exercise_key}', is_timed={self.is_timed})>"
        )


# --- 5C. BODYWEIGHT EXERCISE USER PREFERENCES ---
class BodyweightExercisePreference(Base):
    __tablename__ = 'bodyweight_exercise_preferences'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    exercise_key = Column(String(160), nullable=False, index=True)
    exercise_name = Column(String(160), nullable=False)
    is_bodyweight = Column(Boolean, nullable=False, default=True)
    source = Column(String(32), nullable=False, default='manual')
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    user = relationship("User", back_populates="bodyweight_preferences")

    __table_args__ = (
        Index('idx_user_bodyweight_exercise_pref', 'user_id', 'exercise_key', unique=True),
    )

    def __repr__(self):
        return (
            f"<BodyweightExercisePreference(id={self.id}, user_id={self.user_id}, "
            f"exercise_key='{self.exercise_key}', is_bodyweight={self.is_bodyweight})>"
        )


# --- 5D. CUSTOM RETRIEVAL HISTORY AND PREFERENCES ---
class CustomRetrievalEvent(Base):
    __tablename__ = 'custom_retrieval_events'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    exercise_key = Column(String(160), nullable=False, index=True)
    retrieved_at = Column(DateTime, default=datetime.now, nullable=False, index=True)

    user = relationship("User", back_populates="custom_retrieval_events")

    __table_args__ = (
        Index('idx_custom_retrieval_event_user_date', 'user_id', 'retrieved_at'),
        Index('idx_custom_retrieval_event_user_exercise_date', 'user_id', 'exercise_key', 'retrieved_at'),
    )


class CustomRetrievalPreference(Base):
    __tablename__ = 'custom_retrieval_preferences'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    sort_mode = Column(String(32), nullable=False, default='most_retrieved')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    user = relationship("User", back_populates="custom_retrieval_preference")


class StatsPreference(Base):
    __tablename__ = 'stats_preferences'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    sort_mode = Column(String(32), nullable=False, default='most_viewed')
    time_range = Column(String(8), nullable=False, default='all')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    user = relationship("User", back_populates="stats_preference")


class StatsExerciseView(Base):
    """How often a user opened an exercise's chart on the stats page (for "Viewed" sorting)."""
    __tablename__ = 'stats_exercise_views'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    exercise_key = Column(String(160), nullable=False)
    view_count = Column(Integer, nullable=False, default=0)
    last_viewed_at = Column(DateTime, default=datetime.now, nullable=False)

    user = relationship("User", back_populates="stats_exercise_views")

    __table_args__ = (
        Index('idx_stats_exercise_view_user_exercise', 'user_id', 'exercise_key', unique=True),
    )


class ExerciseGroupChoice(Base):
    """A user moving an exercise to another muscle group on the Custom workout page."""
    __tablename__ = 'exercise_group_choices'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    exercise_key = Column(String(160), nullable=False)
    group_name = Column(String(32), nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    user = relationship("User", back_populates="exercise_groups")

    __table_args__ = (
        Index('idx_exercise_group_choice_user_exercise', 'user_id', 'exercise_key', unique=True),
    )


class ExerciseRename(Base):
    """A user renaming an exercise: its history was moved to the new name, and anything still
    logged under the old name (habit, Shortcuts, offline logs) goes to the new one too."""
    __tablename__ = 'exercise_renames'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    old_key = Column(String(160), nullable=False)
    old_name = Column(String(160), nullable=False)
    new_name = Column(String(160), nullable=False)
    log_ids = Column(JSONType)  # the logs this rename moved, to undo it later if needed
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    user = relationship("User", back_populates="exercise_renames")

    __table_args__ = (
        Index('idx_exercise_rename_user_old', 'user_id', 'old_key', unique=True),
    )


class AppIcon(Base):
    """The app icon an admin uploaded, stored here so every host serves the same one.

    A single row (id 1). `image` is the already sized-and-centered square PNG;
    `version` is its hash, used in icon URLs so browsers and phones refetch it.
    """
    __tablename__ = 'app_icon'
    id = Column(Integer, primary_key=True)
    image = Column(LargeBinary, nullable=False)
    version = Column(String(16), nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class Feedback(Base):
    """Something a user told the developer: what they like or don't, what could be better, an idea.

    `kind` is one of FEEDBACK_KINDS; `status` moves new -> seen -> done as the admin works through it.
    """
    __tablename__ = 'feedback'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    message = Column(Text, nullable=False)
    page = Column(String(200))  # where they were in the app when they wrote it
    status = Column(String(8), nullable=False, default='new', index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True)

    user = relationship("User")


class CoachAnswer(Base):
    """One answer from the admin AI coach, kept so its quality can be reviewed and models compared.

    `source` is 'ai' or 'rules' (the built-in fallback); `rating` is 1 (helpful), -1 (not) or None.
    `steps` is the tools the model looked things up with, in order.
    """
    __tablename__ = 'coach_answers'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    source = Column(String(8), nullable=False, default='ai')
    model = Column(String(80))
    steps = Column(JSONType)
    calls = Column(Integer)
    tokens = Column(Integer)
    ms = Column(Integer)
    failed = Column(String(300))  # models that errored first, e.g. "gemini-2.5-flash:429"
    rating = Column(Integer, index=True)
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True)

    user = relationship("User")


# --- MIGRATION HELPERS ---
def migrate_schema():
    """Add missing columns to existing database tables."""
    from sqlalchemy import inspect, text
    from utils.logger import logger
    
    try:
        inspector = inspect(engine)
        
        # Check if users table exists
        if 'users' not in inspector.get_table_names():
            return
        
        # Check and add missing columns to users table
        users_columns = [col['name'] for col in inspector.get_columns('users')]
        
        with engine.begin() as conn:  # Use begin() for transaction management
            dialect = engine.dialect.name
            # Choose appropriate types per dialect
            if dialect == 'mysql':
                ts_type = 'DATETIME'
                str_type = 'VARCHAR(255)'
                bool_type = 'TINYINT(1)'
                json_type = 'JSON'
                float_type = 'DOUBLE'
                now_func = 'CURRENT_TIMESTAMP'
            elif dialect == 'postgresql':
                ts_type = 'TIMESTAMP'
                str_type = 'VARCHAR(255)'
                bool_type = 'BOOLEAN'
                json_type = 'JSONB'
                float_type = 'DOUBLE PRECISION'
                now_func = 'CURRENT_TIMESTAMP'
            else:
                # SQLite (and others)
                ts_type = 'TIMESTAMP'
                str_type = 'VARCHAR(255)'
                bool_type = 'BOOLEAN'
                json_type = 'TEXT'
                float_type = 'FLOAT'
                now_func = 'CURRENT_TIMESTAMP'

            # --- Auth columns ---
            if dialect == 'postgresql':
                logger.info("Ensuring auth columns exist for PostgreSQL")
                lock_timeout_ms = int(os.environ.get('DB_LOCK_TIMEOUT_MS', '5000'))
                statement_timeout_ms = int(os.environ.get('DB_STATEMENT_TIMEOUT_MS', '60000'))
                conn.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'"))
                conn.execute(text(f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(100)"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS email {str_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash {str_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS role {str_type} DEFAULT 'user'"))
                conn.execute(text("UPDATE users SET role = 'user' WHERE role IS NULL"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified {bool_type} DEFAULT FALSE"))
                conn.execute(text("UPDATE users SET is_verified = FALSE WHERE is_verified IS NULL"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token {str_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token_expires {ts_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_code {str_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_purpose {str_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_expires {ts_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS bodyweight {float_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_image {str_type}"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS follow_admin_plan {bool_type} DEFAULT FALSE"))
                conn.execute(text("UPDATE users SET follow_admin_plan = FALSE WHERE follow_admin_plan IS NULL"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS follow_admin_exercises {bool_type} DEFAULT FALSE"))
                conn.execute(text("UPDATE users SET follow_admin_exercises = FALSE WHERE follow_admin_exercises IS NULL"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at {ts_type}"))
                conn.execute(text(f"UPDATE users SET created_at = {now_func} WHERE created_at IS NULL"))
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at {ts_type}"))
                conn.execute(text(f"UPDATE users SET updated_at = {now_func} WHERE updated_at IS NULL"))
            else:
                if 'full_name' not in users_columns:
                    logger.info("Adding full_name column to users table")
                    conn.execute(text("ALTER TABLE users ADD COLUMN full_name VARCHAR(100)"))

                if 'email' not in users_columns:
                    logger.info("Adding email column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN email {str_type}"))

                if 'password_hash' not in users_columns:
                    logger.info("Adding password_hash column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN password_hash {str_type}"))

                if 'role' not in users_columns:
                    logger.info("Adding role column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN role {str_type} DEFAULT 'user'"))
                    conn.execute(text("UPDATE users SET role = 'user' WHERE role IS NULL"))

                if 'is_verified' not in users_columns:
                    logger.info("Adding is_verified column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN is_verified {bool_type} DEFAULT 0"))
                    conn.execute(text("UPDATE users SET is_verified = 0 WHERE is_verified IS NULL"))

                if 'verification_token' not in users_columns:
                    logger.info("Adding verification_token column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN verification_token {str_type}"))

                if 'verification_token_expires' not in users_columns:
                    logger.info("Adding verification_token_expires column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN verification_token_expires {ts_type}"))

                if 'otp_code' not in users_columns:
                    logger.info("Adding otp_code column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN otp_code {str_type}"))

                if 'otp_purpose' not in users_columns:
                    logger.info("Adding otp_purpose column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN otp_purpose {str_type}"))

                if 'otp_expires' not in users_columns:
                    logger.info("Adding otp_expires column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN otp_expires {ts_type}"))

                if 'bodyweight' not in users_columns:
                    logger.info("Adding bodyweight column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN bodyweight {float_type}"))

                if 'profile_image' not in users_columns:
                    logger.info("Adding profile_image column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN profile_image {str_type}"))

                if 'follow_admin_plan' not in users_columns:
                    logger.info("Adding follow_admin_plan column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN follow_admin_plan {bool_type} DEFAULT 0"))
                    conn.execute(text("UPDATE users SET follow_admin_plan = 0 WHERE follow_admin_plan IS NULL"))

                if 'follow_admin_exercises' not in users_columns:
                    logger.info("Adding follow_admin_exercises column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN follow_admin_exercises {bool_type} DEFAULT 0"))
                    conn.execute(text("UPDATE users SET follow_admin_exercises = 0 WHERE follow_admin_exercises IS NULL"))

                if 'created_at' not in users_columns:
                    logger.info("Adding created_at column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN created_at {ts_type}"))
                    conn.execute(text(f"UPDATE users SET created_at = {now_func} WHERE created_at IS NULL"))
                
                if 'updated_at' not in users_columns:
                    logger.info("Adding updated_at column to users table")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN updated_at {ts_type}"))
                    conn.execute(text(f"UPDATE users SET updated_at = {now_func} WHERE updated_at IS NULL"))

            # --- Workout log columns ---
            if 'email_verifications' not in inspector.get_table_names():
                EmailVerification.__table__.create(bind=conn, checkfirst=True)

            if 'user_api_keys' not in inspector.get_table_names():
                UserApiKey.__table__.create(bind=conn, checkfirst=True)
            else:
                key_columns = [col['name'] for col in inspector.get_columns('user_api_keys')]
                if 'account_label' not in key_columns:
                    conn.execute(text("ALTER TABLE user_api_keys ADD COLUMN account_label VARCHAR(100)"))

            if 'shortcut_key_maps' not in inspector.get_table_names():
                ShortcutKeyMap.__table__.create(bind=conn, checkfirst=True)

            if 'timed_exercise_preferences' not in inspector.get_table_names():
                TimedExercisePreference.__table__.create(bind=conn, checkfirst=True)

            if 'bodyweight_exercise_preferences' not in inspector.get_table_names():
                BodyweightExercisePreference.__table__.create(bind=conn, checkfirst=True)

            if 'custom_retrieval_events' not in inspector.get_table_names():
                CustomRetrievalEvent.__table__.create(bind=conn, checkfirst=True)

            if 'custom_retrieval_preferences' not in inspector.get_table_names():
                CustomRetrievalPreference.__table__.create(bind=conn, checkfirst=True)

            if 'stats_preferences' not in inspector.get_table_names():
                StatsPreference.__table__.create(bind=conn, checkfirst=True)
            else:
                stats_pref_columns = [col['name'] for col in inspector.get_columns('stats_preferences')]
                if 'time_range' not in stats_pref_columns:
                    logger.info("Adding time_range column to stats_preferences table")
                    conn.execute(text("ALTER TABLE stats_preferences ADD COLUMN time_range VARCHAR(8) NOT NULL DEFAULT 'all'"))

            if 'stats_exercise_views' not in inspector.get_table_names():
                StatsExerciseView.__table__.create(bind=conn, checkfirst=True)

            if 'app_icon' not in inspector.get_table_names():
                AppIcon.__table__.create(bind=conn, checkfirst=True)

            if 'exercise_group_choices' not in inspector.get_table_names():
                ExerciseGroupChoice.__table__.create(bind=conn, checkfirst=True)

            if 'exercise_renames' not in inspector.get_table_names():
                ExerciseRename.__table__.create(bind=conn, checkfirst=True)

            if 'feedback' not in inspector.get_table_names():
                Feedback.__table__.create(bind=conn, checkfirst=True)

            if 'coach_answers' not in inspector.get_table_names():
                CoachAnswer.__table__.create(bind=conn, checkfirst=True)

            if 'workout_logs' in inspector.get_table_names():
                logs_columns = [col['name'] for col in inspector.get_columns('workout_logs')]

                if dialect == 'postgresql':
                    conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN IF NOT EXISTS workout_name {str_type}"))
                    conn.execute(text("UPDATE workout_logs SET workout_name = '' WHERE workout_name IS NULL"))
                    conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN IF NOT EXISTS exercise_string TEXT"))
                    conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN IF NOT EXISTS sets_json {json_type}"))
                    conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN IF NOT EXISTS bodyweight {float_type}"))
                    conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN IF NOT EXISTS uses_bodyweight {bool_type}"))
                else:
                    if 'workout_name' not in logs_columns:
                        logger.info("Adding workout_name column to workout_logs table")
                        conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN workout_name {str_type}"))
                    if 'exercise_string' not in logs_columns:
                        logger.info("Adding exercise_string column to workout_logs table")
                        conn.execute(text("ALTER TABLE workout_logs ADD COLUMN exercise_string TEXT"))
                    if 'sets_json' not in logs_columns:
                        logger.info("Adding sets_json column to workout_logs table")
                        conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN sets_json {json_type}"))
                    if 'bodyweight' not in logs_columns:
                        logger.info("Adding bodyweight column to workout_logs table")
                        conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN bodyweight {float_type}"))
                    if 'uses_bodyweight' not in logs_columns:
                        logger.info("Adding uses_bodyweight column to workout_logs table")
                        conn.execute(text(f"ALTER TABLE workout_logs ADD COLUMN uses_bodyweight {bool_type}"))

            if 'lifts' in inspector.get_table_names():
                lift_columns = [col['name'] for col in inspector.get_columns('lifts')]

                if dialect == 'postgresql':
                    conn.execute(text("ALTER TABLE lifts ADD COLUMN IF NOT EXISTS best_log_id INTEGER"))
                    conn.execute(text(
                        "DO $$ BEGIN "
                        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_lifts_best_log_id_workout_logs') THEN "
                        "ALTER TABLE lifts ADD CONSTRAINT fk_lifts_best_log_id_workout_logs "
                        "FOREIGN KEY (best_log_id) REFERENCES workout_logs(id) ON DELETE SET NULL; "
                        "END IF; END $$;"
                    ))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lifts_best_log_id ON lifts (best_log_id)"))
                    for old_col in ("best_string", "sets_json", "updated_at"):
                        conn.execute(text(f"ALTER TABLE lifts DROP COLUMN IF EXISTS {old_col}"))
                else:
                    if 'best_log_id' not in lift_columns:
                        logger.info("Adding best_log_id column to lifts table")
                        conn.execute(text("ALTER TABLE lifts ADD COLUMN best_log_id INTEGER REFERENCES workout_logs(id) ON DELETE SET NULL"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lifts_best_log_id ON lifts (best_log_id)"))
                
    except Exception as e:
        logger.warning(f"Migration warning (may be expected): {e}")
        if isinstance(e, SQLAlchemyError):
            raise


# --- INITIALIZATION ---
def initialize_database():
    """Initialize database tables and seed default data."""
    # Create all tables (only creates new tables, not new columns)
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if 'users' not in tables:
        auto_create = os.environ.get('AUTO_CREATE_SCHEMA', '').lower() == 'true'
        if not auto_create:
            raise RuntimeError(
                "Database schema is not initialized. Run `alembic upgrade head` first "
                "(or set AUTO_CREATE_SCHEMA=true for dev-only auto-create)."
            )

        Base.metadata.create_all(engine)

    migrate_schema()
    
    session = Session()
    try:
        _bootstrap_admin_user(session)

        # Default users (can be made configurable)
        default_users = []
        for name in default_users:
            user = session.query(User).filter_by(username=name).first()
            if not user:
                user = User(username=name, created_at=datetime.now(), updated_at=datetime.now())
                session.add(user)
                session.flush()  # Get user.id
                _seed_user_data(session, user)
            else:
                # Update timestamps if they're None
                if user.created_at is None:
                    user.created_at = datetime.now()
                if user.updated_at is None:
                    user.updated_at = datetime.now()
        session.commit()
    except Exception as e:
        session.rollback()
        from utils.logger import logger
        logger.error(f"Database initialization error: {e}", exc_info=True)
        raise
    finally:
        session.close()

    # Data fix-ups that must never stop the app from starting.
    session = Session()
    try:
        from services.exercise_rename import finish_partial_renames
        finished = finish_partial_renames(session)
        if finished:
            from utils.logger import logger
            logger.info(f"Finished {finished} exercise rename(s) that had left a reordered name behind")
    except Exception as e:
        session.rollback()
        from utils.logger import logger
        logger.error(f"Finishing exercise renames failed: {e}", exc_info=True)
    finally:
        session.close()


def _bootstrap_admin_user(session):
    admin_password = Config.ADMIN_PASSWORD
    if not admin_password:
        return

    admin_username = (Config.ADMIN_USERNAME or 'admin').lower()
    admin_email = (Config.ADMIN_EMAIL or 'admin@liftbook.local').lower()

    try:
        import bcrypt

        user = None
        if admin_email:
            user = session.query(User).filter_by(email=admin_email).first()
        if not user:
            user = session.query(User).filter_by(username=admin_username).first()
        created = False
        if not user:
            user = User(username=admin_username)
            session.add(user)
            created = True

        if not user.email:
            user.email = admin_email
        if not user.is_admin():
            user.role = UserRole.ADMIN
        if created or not user.password_hash:
            # bcrypt reads 72 bytes at most (and bcrypt 5 refuses more), as in AuthService.
            user.password_hash = bcrypt.hashpw(admin_password.encode('utf-8')[:72], bcrypt.gensalt()).decode('utf-8')
        if not user.is_verified:
            user.is_verified = True
        if user.verification_token or user.verification_token_expires:
            user.verification_token = None
            user.verification_token_expires = None
        if not user.created_at:
            user.created_at = datetime.now()
        user.updated_at = datetime.now()
    except Exception:
        from utils.logger import logger
        logger.error("Failed to bootstrap admin user", exc_info=True)


def _seed_user_data(session, user):
    existing_lifts = session.query(Lift).filter(Lift.user_id == user.id).all()
    existing_by_exercise = {lift.exercise: lift for lift in existing_lifts}
    for ex in list_of_exercises:
        if ex not in existing_by_exercise:
            session.add(Lift(user_id=user.id, exercise=ex))

    # No plan is copied in: an account without its own plan always gets the current DEFAULT_PLAN.

    existing_rep_ranges = session.query(RepRange).filter(RepRange.user_id == user.id).first()
    if not existing_rep_ranges:
        # Their own rep ranges start as a copy of the main admin's, as they are today
        # (what they get if they stop following); the built-in list if there are none.
        from services.retrieve import _get_admin_rep_ranges_text

        rep_text = _get_admin_rep_ranges_text(session)
        if not rep_text:
            rep_text = "".join(f"{ex}: {rng}\n" for ex, rng in DEFAULT_REP_RANGES.items())
        session.add(RepRange(user_id=user.id, text_content=rep_text))

    existing_shortcut_map = session.query(ShortcutKeyMap).filter(ShortcutKeyMap.user_id == user.id).first()
    if not existing_shortcut_map:
        session.add(ShortcutKeyMap(user_id=user.id, text_content=""))
