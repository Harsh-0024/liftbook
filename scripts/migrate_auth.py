"""
Database migration script to add authentication fields to existing users.
This script upgrades the database schema for the new authentication system.
"""
import sys
from datetime import datetime
from sqlalchemy import inspect, text
import os

# Let this script import project modules when run as `python scripts/<name>.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import engine, Session, User, UserRole
from services.auth import AuthService
from utils.logger import logger


def check_column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def migrate_users_table():
    """Add authentication columns to users table."""
    logger.info("Starting users table migration...")
    
    with engine.begin() as conn:
        dialect = engine.dialect.name
        
        # Determine SQL types based on dialect
        if dialect == 'mysql':
            string_type = 'VARCHAR(255)'
            bool_type = 'TINYINT(1)'
            datetime_type = 'DATETIME'
        elif dialect == 'postgresql':
            string_type = 'VARCHAR(255)'
            bool_type = 'BOOLEAN'
            datetime_type = 'TIMESTAMP'
        else:  # SQLite and others
            string_type = 'VARCHAR(255)'
            bool_type = 'BOOLEAN'
            datetime_type = 'TIMESTAMP'
        
        # Add email column
        if not check_column_exists('users', 'email'):
            logger.info("Adding email column...")
            conn.execute(text(f"ALTER TABLE users ADD COLUMN email {string_type}"))
        
        # Add password_hash column
        if not check_column_exists('users', 'password_hash'):
            logger.info("Adding password_hash column...")
            conn.execute(text(f"ALTER TABLE users ADD COLUMN password_hash {string_type}"))
        
        # Add role column
        if not check_column_exists('users', 'role'):
            logger.info("Adding role column...")
            conn.execute(text(f"ALTER TABLE users ADD COLUMN role {string_type} DEFAULT 'user'"))
        
        # Add is_verified column
        if not check_column_exists('users', 'is_verified'):
            logger.info("Adding is_verified column...")
            if dialect == 'postgresql':
                conn.execute(text(f"ALTER TABLE users ADD COLUMN is_verified {bool_type} DEFAULT FALSE"))
            else:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN is_verified {bool_type} DEFAULT 0"))
        
        # Add verification_token column
        if not check_column_exists('users', 'verification_token'):
            logger.info("Adding verification_token column...")
            conn.execute(text(f"ALTER TABLE users ADD COLUMN verification_token {string_type}"))
        
        # Add verification_token_expires column
        if not check_column_exists('users', 'verification_token_expires'):
            logger.info("Adding verification_token_expires column...")
            conn.execute(text(f"ALTER TABLE users ADD COLUMN verification_token_expires {datetime_type}"))
    
    logger.info("Users table migration completed!")


def migrate_existing_users():
    """
    Migrate existing users to the new authentication system.
    This function prompts for setup of existing users.
    """
    logger.info("Migrating existing users...")
    
    session = Session()
    try:
        users = session.query(User).all()
        
        if not users:
            logger.info("No existing users found.")
            return
        
        logger.info(f"Found {len(users)} existing user(s)")
        
        for user in users:
            # Skip if already migrated (has email)
            if user.email:
                logger.info(f"User '{user.username}' already migrated, skipping...")
                continue
            
            logger.info(f"\n--- Migrating user: {user.username} ---")
            
            # For automated migration: Set default values and mark as verified
            # In production, you'd want to prompt for email and password
            default_email = f"{user.username}@workouttracker.local"
            default_password = "ChangeMe123!"  # Temporary password
            
            user.email = default_email
            user.password_hash = AuthService.hash_password(default_password)
            user.role = UserRole.USER
            user.is_verified = True  # Auto-verify existing users
            user.verification_token = None
            user.verification_token_expires = None
            
            if not user.created_at:
                user.created_at = datetime.now()
            if not user.updated_at:
                user.updated_at = datetime.now()
            
            logger.info(f"  ✓ Migrated '{user.username}'")
            logger.info(f"    Email: {default_email}")
            logger.info(f"    Password: {default_password}")
            logger.info(f"    Role: user")
            logger.info(f"    Status: verified")
        
        session.commit()
        logger.info("\n✅ All users migrated successfully!")
        
        logger.info("\n" + "="*60)
        logger.info("IMPORTANT: Default credentials for existing users:")
        logger.info("="*60)
        for user in users:
            if not hasattr(user, '_migrated'):
                logger.info(f"Username: {user.username}")
                logger.info(f"Email: {user.username}@workouttracker.local")
                logger.info(f"Password: ChangeMe123!")
                logger.info("-" * 60)
        logger.info("\nUsers should change their passwords after first login!")
        logger.info("="*60)
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error migrating users: {e}", exc_info=True)
        raise
    finally:
        session.close()


def create_admin_user():
    """
    Create the first admin user.
    """
    session = Session()
    try:
        # Check if any admin exists
        admin_exists = session.query(User).filter_by(role=UserRole.ADMIN).first()
        
        if admin_exists:
            logger.info(f"Admin user already exists: {admin_exists.username}")
            return
        
        logger.info("\n" + "="*60)
        logger.info("Creating Admin User")
        logger.info("="*60)
        
        # Create admin with default credentials
        admin_username = "admin"
        admin_email = "admin@workouttracker.local"
        admin_password = "Admin123!SecurePassword"
        
        # Check if username exists
        existing = session.query(User).filter_by(username=admin_username).first()
        if existing:
            # Promote existing user to admin
            existing.role = UserRole.ADMIN
            existing.email = admin_email
            existing.password_hash = AuthService.hash_password(admin_password)
            existing.is_verified = True
            existing.updated_at = datetime.now()
            session.commit()
            logger.info(f"✓ Promoted existing user '{admin_username}' to admin")
        else:
            # Create new admin
            admin = User(
                username=admin_username,
                email=admin_email,
                password_hash=AuthService.hash_password(admin_password),
                role=UserRole.ADMIN,
                is_verified=True,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            session.add(admin)
            session.commit()
            logger.info(f"✓ Created new admin user: {admin_username}")
        
        logger.info("\n" + "="*60)
        logger.info("ADMIN CREDENTIALS:")
        logger.info("="*60)
        logger.info(f"Username: {admin_username}")
        logger.info(f"Email: {admin_email}")
        logger.info(f"Password: {admin_password}")
        logger.info("="*60)
        logger.info("\n⚠️  IMPORTANT: Change this password immediately after first login!")
        logger.info("="*60 + "\n")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error creating admin user: {e}", exc_info=True)
        raise
    finally:
        session.close()


def run_full_migration():
    """Run complete migration process."""
    try:
        logger.info("\n" + "="*60)
        logger.info("AUTHENTICATION SYSTEM MIGRATION")
        logger.info("="*60 + "\n")
        
        # Step 1: Migrate schema
        logger.info("Step 1: Migrating database schema...")
        migrate_users_table()
        
        # Step 2: Migrate existing users
        logger.info("\nStep 2: Migrating existing users...")
        migrate_existing_users()
        
        # Step 3: Create admin user
        logger.info("\nStep 3: Creating admin user...")
        create_admin_user()
        
        logger.info("\n" + "="*60)
        logger.info("✅ MIGRATION COMPLETED SUCCESSFULLY!")
        logger.info("="*60)
        logger.info("\nNext steps:")
        logger.info("1. Configure email settings in .env file")
        logger.info("2. Have users change their default passwords")
        logger.info("3. Update admin credentials")
        logger.info("4. Test the authentication system")
        logger.info("="*60 + "\n")
        
        return True
        
    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    print("\n" + "="*60)
    print("Liftbook - Authentication Migration")
    print("="*60)
    print("\nThis script will:")
    print("1. Add authentication columns to the database")
    print("2. Migrate existing users with default credentials")
    print("3. Create an admin user account")
    print("\n⚠️  WARNING: This will modify your database!")
    print("   Make sure you have a backup before proceeding.")
    print("="*60)
    
    response = input("\nDo you want to proceed? (yes/no): ").strip().lower()
    
    if response in ['yes', 'y']:
        success = run_full_migration()
        sys.exit(0 if success else 1)
    else:
        print("\nMigration cancelled.")
        sys.exit(0)
