"""
Configuration management for the Liftbook application.
"""
import os
import urllib.parse
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


class Config:
    """Base configuration class."""
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    # Database
    DATABASE_URL = os.environ.get('DATABASE_URL')

    # Public addresses of every deployment (they share one database), used to
    # show Shortcut URLs for each. Format: "Name=https://host,Name=https://host".
    DEPLOYMENT_URLS = os.environ.get(
        'DEPLOYMENT_URLS',
        'Railway=https://workoutlogger-production-7f91.up.railway.app,'
        'Render=https://workout-tracker-62qi.onrender.com',
    )
    
    # App Settings
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    # Elastic Beanstalk's nginx proxy expects the web process on 8000 unless
    # a different PORT is explicitly injected into the environment.
    PORT = int(os.environ.get('PORT', 8000))
    HOST = os.environ.get('HOST', '0.0.0.0')
    
    # Feature Flags
    ENABLE_CSRF = True
    # A form stays good for as long as the page is open: with the default one hour, a workout
    # typed at the gym and saved later was refused. The token still belongs to the session.
    WTF_CSRF_TIME_LIMIT = None
    # Largest request accepted (photos, pasted workouts). Without it an upload of any size was
    # taken and decoded, enough to run a small server out of memory.
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ENABLE_RATE_LIMITING = os.environ.get('ENABLE_RATE_LIMITING', 'True').lower() == 'true'
    
    # Pagination
    ITEMS_PER_PAGE = 20
    
    # Timezone (IST)
    TIMEZONE_OFFSET_HOURS = 5
    TIMEZONE_OFFSET_MINUTES = 30
    
    # Email Configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = (
        os.environ.get('MAIL_DEFAULT_SENDER')
        or os.environ.get('MAIL_USERNAME')
        or 'noreply@workouttracker.com'
    )

    # Brevo Transactional Email API (recommended for Railway)
    BREVO_API_KEY = os.environ.get('BREVO_API_KEY')
    BREVO_SENDER_EMAIL = os.environ.get('BREVO_SENDER_EMAIL') or MAIL_DEFAULT_SENDER
    BREVO_SENDER_NAME = os.environ.get('BREVO_SENDER_NAME', 'Liftbook')

    # Google Gemini API (Google AI Studio)
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    # Optional: the model the admin AI coach tries first (falls back to its built-in list).
    GEMINI_COACH_MODEL = os.environ.get('GEMINI_COACH_MODEL', '')
    # Groq (OpenAI-compatible) key for the AI coach; saved gsk_ keys in Integrations work too.
    GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
    # Optional: the coach's model order, e.g. "groq:openai/gpt-oss-120b,gemini:gemini-2.5-flash".
    AI_MODEL_ORDER = os.environ.get('AI_MODEL_ORDER', '')

    # Profile image storage (Cloudflare R2)
    R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
    R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
    R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', 'workout-tracker-avatars')
    R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID', 'c60933f634439b0fb2e6c7762535ba6c')
    
    # Authentication
    REMEMBER_COOKIE_DURATION = 30  # days

    # Sign-in cookies: hidden from page scripts, not sent along with other sites' requests,
    # and only over HTTPS where the app is deployed (Render and Railway set these variables;
    # a local run on http://localhost keeps working).
    DEPLOYED = bool(
        os.environ.get('RENDER')
        or os.environ.get('RAILWAY_ENVIRONMENT')
        or os.environ.get('RAILWAY_ENVIRONMENT_NAME')
        or os.environ.get('RAILWAY_PROJECT_ID')
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = DEPLOYED
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = DEPLOYED
    VERIFICATION_TOKEN_EXPIRY = 24  # hours
    OTP_TOKEN_EXPIRY_MINUTES = int(os.environ.get('OTP_TOKEN_EXPIRY_MINUTES', 10))

    # Admin bootstrap (create/update admin user on startup if password is provided)
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@workouttracker.local')
    ADMIN_EMAILS = os.environ.get('ADMIN_EMAILS', '')
    ADMIN_EMAIL_ALLOWLIST = {
        email.strip().lower()
        for email in ADMIN_EMAILS.split(',')
        if email.strip()
    }
    if ADMIN_EMAIL:
        ADMIN_EMAIL_ALLOWLIST.add(ADMIN_EMAIL.lower())
    
    @staticmethod
    def get_database_url() -> str:
        """Get database URL with proper formatting."""
        database_url = Config.DATABASE_URL
        if database_url and database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        if database_url and database_url.startswith("postgresql://") and "sslmode=" not in database_url:
            parsed = urllib.parse.urlparse(database_url)
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            query.setdefault("sslmode", "require")
            query.setdefault("connect_timeout", "10")
            database_url = urllib.parse.urlunparse(
                parsed._replace(query=urllib.parse.urlencode(query))
            )
        
        if not database_url:
            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            DB_PATH = os.path.join(BASE_DIR, "workout.db")
            database_url = f"sqlite:///{DB_PATH}"
        
        return database_url


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    ENABLE_CSRF = True
    ENABLE_RATE_LIMITING = True


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    DATABASE_URL = 'sqlite:///:memory:'
    SECRET_KEY = 'test-secret-key'


# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
