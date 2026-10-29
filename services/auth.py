"""
Authentication service for user registration, login, and password management.
"""
import bcrypt
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from models import User, UserRole, EmailVerification, Session, _seed_user_data, session_factory
from utils.errors import ValidationError
from utils.logger import logger
from config import Config


class AuthenticationError(Exception):
    pass


class EmailNotVerifiedError(AuthenticationError):
    """The password was right but the email was never confirmed: sign-in can send a new code."""

    def __init__(self, user_id: int):
        super().__init__("Please verify your email before signing in.")
        self.user_id = user_id


def _password_bytes(password: str) -> bytes:
    """bcrypt only reads the first 72 bytes. Older bcrypt cut longer passwords there quietly;
    bcrypt 5 refuses them instead, which broke sign-up and password changes for long passwords
    (a password manager's, or ~40 accented letters) and locked out accounts made with one.
    Cutting here keeps every existing hash matching."""
    return (password or '').encode('utf-8')[:72]


def _checked_new_password(new_password: str) -> str:
    """The same rules as sign-up, for a password change."""
    from utils.errors import ValidationError
    from utils.validators import validate_password

    try:
        return validate_password(new_password)
    except ValidationError as e:
        raise AuthenticationError(str(e))


class AuthService:
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt."""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(_password_bytes(password), salt)
        return hashed.decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify a password against its hash."""
        try:
            return bcrypt.checkpw(_password_bytes(password), password_hash.encode('utf-8'))
        except Exception:
            return False
    
    @staticmethod
    def generate_verification_token() -> str:
        """Generate a secure random verification token."""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def generate_verification_code() -> str:
        """Generate a 6-digit verification code."""
        return str(secrets.randbelow(900000) + 100000)

    @staticmethod
    def _get_email_verification_expiry(purpose: str) -> datetime:
        if purpose == 'verify_email':
            return datetime.now() + timedelta(hours=Config.VERIFICATION_TOKEN_EXPIRY)
        return datetime.now() + timedelta(minutes=Config.OTP_TOKEN_EXPIRY_MINUTES)

    @staticmethod
    def _create_email_verification(session, user_id: int, email: str, purpose: str) -> str:
        if not email:
            raise AuthenticationError("This account has no email on file")

        session.query(EmailVerification).filter(
            EmailVerification.user_id == user_id,
            EmailVerification.email == email,
            EmailVerification.purpose == purpose,
            EmailVerification.verified_at.is_(None),
        ).delete(synchronize_session=False)

        otp_code = AuthService.generate_verification_code()
        expires_at = AuthService._get_email_verification_expiry(purpose)
        verification = EmailVerification(
            user_id=user_id,
            email=email,
            purpose=purpose,
            code=otp_code,
            expires_at=expires_at,
            created_at=datetime.now(),
        )
        session.add(verification)
        session.flush()
        logger.info(
            "OTP created",
            extra={"user_id": user_id, "purpose": purpose, "verification_id": verification.id},
        )
        return otp_code

    @staticmethod
    def _get_latest_email_verification(session, user_id: int, purpose: str, email: Optional[str] = None):
        query = session.query(EmailVerification).filter(
            EmailVerification.user_id == user_id,
            EmailVerification.purpose == purpose,
            EmailVerification.verified_at.is_(None),
        )
        if email:
            query = query.filter(EmailVerification.email == email)
        return query.order_by(EmailVerification.created_at.desc()).first()
    
    @staticmethod
    def register_user(
        username: str,
        email: str,
        password: str,
        name: Optional[str] = None,
        is_admin: bool = False
    ) -> Tuple[User, str]:
        """
        Register a new user.
        
        Returns:
            Tuple of (User object, verification_code)
        
        Raises:
            AuthenticationError: If registration fails
        """
        session = Session()
        try:
            # Validate inputs using centralized validators
            from utils.validators import (
                USERNAME_NOT_AVAILABLE, is_reserved_username, validate_email, validate_password, validate_username,
            )
            
            username = validate_username(username)
            if is_reserved_username(username):
                raise AuthenticationError(USERNAME_NOT_AVAILABLE)
            email = validate_email(email)
            password = validate_password(password)
            
            # Check if username or email already exists
            existing_user = session.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()
            
            if existing_user:
                if existing_user.username == username:
                    raise AuthenticationError("Username already taken")
                else:
                    raise AuthenticationError("Email already registered")
            # A username that is someone's email address would be mistaken for them at sign-in.
            if session.query(User).filter(User.email == username).first():
                raise AuthenticationError(USERNAME_NOT_AVAILABLE)
            
            # Create user
            role = UserRole.ADMIN if is_admin or email in Config.ADMIN_EMAIL_ALLOWLIST else UserRole.USER
            user = User(
                username=username,
                email=email,
                password_hash=AuthService.hash_password(password),
                role=role,
                is_verified=False,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )

            session.add(user)
            session.flush()
            verification_code = AuthService._create_email_verification(
                session,
                user_id=user.id,
                email=user.email,
                purpose='verify_email',
            )
            _seed_user_data(session, user)
            session.commit()
            session.refresh(user)
            
            return user, verification_code
            
        except AuthenticationError:
            session.rollback()
            raise
        except ValidationError as e:
            # "Password must contain at least one number" is the whole message.
            session.rollback()
            raise AuthenticationError(str(e))
        except Exception as e:
            session.rollback()
            logger.error(f"Registration failed: {e}", exc_info=True)
            raise AuthenticationError("Couldn't create your account right now. Please try again.")
        finally:
            session.close()

    @staticmethod
    def request_password_change_otp(user_id: int) -> dict:
        """Generate and store a one-time code for password changes."""
        session = Session()
        try:
            user = session.get(User, user_id)
            if not user:
                raise AuthenticationError("User not found")

            if not user.email:
                raise AuthenticationError("This account has no email on file")

            otp_code = AuthService._create_email_verification(
                session,
                user_id=user.id,
                email=user.email,
                purpose='change_password',
            )
            session.commit()

            logger.info(
                "Password change OTP created",
                extra={"user_id": user.id},
            )

            return {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'otp_code': otp_code,
            }

        except AuthenticationError:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to request password change OTP: {e}", exc_info=True)
            raise AuthenticationError("Unable to send a password change code right now. Please try again.")
        finally:
            session.close()

    @staticmethod
    def request_email_change_otps(user_id: int, current_email: str, new_email: str) -> dict:
        """Generate OTPs for confirming an email change on both old and new addresses."""
        session = Session()
        try:
            user = session.get(User, user_id)
            if not user:
                raise AuthenticationError("User not found")

            if not current_email or not new_email:
                raise AuthenticationError("Both current and new email addresses are required")

            otp_old = AuthService._create_email_verification(
                session,
                user_id=user.id,
                email=current_email,
                purpose='change_email_old',
            )
            otp_new = AuthService._create_email_verification(
                session,
                user_id=user.id,
                email=new_email,
                purpose='change_email_new',
            )
            session.commit()

            return {
                'id': user.id,
                'username': user.username,
                'current_email': current_email,
                'new_email': new_email,
                'otp_old': otp_old,
                'otp_new': otp_new,
            }

        except AuthenticationError:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to request email change OTPs: {e}", exc_info=True)
            raise AuthenticationError("Unable to send email change codes right now. Please try again.")
        finally:
            session.close()

    @staticmethod
    def delete_account(user_id: int) -> None:
        """Delete an account and everything in it (Settings, Account, Delete my
        account). Every table points at users with ON DELETE CASCADE, so removing
        the user row removes the workouts, lifts, plan and the rest with it."""
        session = Session()
        try:
            session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def set_password(user_id: int, new_password: str) -> bool:
        """Set a user's password without verifying the current password."""
        session = Session()
        try:
            user = session.get(User, user_id)

            if not user:
                return False

            new_password = _checked_new_password(new_password)
            user.password_hash = AuthService.hash_password(new_password)
            user.updated_at = datetime.now()
            session.commit()
            return True

        except AuthenticationError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()

    @staticmethod
    def request_login_otp(username_or_email: str) -> dict:
        """Generate and store a one-time code for login."""
        session = Session()
        try:
            identifier = (username_or_email or '').strip().lower()
            if not identifier:
                raise AuthenticationError("Username or email is required")

            identifier_type = 'email' if '@' in identifier else 'username'

            # An address means its owner (the code goes to that inbox), a name its account.
            matches = session.query(User).filter(
                (User.username == identifier) | (User.email == identifier)
            ).all()
            by_email = [m for m in matches if (m.email or '').lower() == identifier]
            user = (by_email if identifier_type == 'email' and by_email else matches or [None])[0]
            if identifier_type == 'username':
                user = next((m for m in matches if (m.username or '').lower() == identifier), user)

            if not user:
                logger.info(
                    "Login OTP request rejected: user not found",
                    extra={"identifier_type": identifier_type},
                )
                raise AuthenticationError("Account not found for that username or email")

            if not user.email:
                raise AuthenticationError("This account has no email on file")

            otp_code = AuthService._create_email_verification(
                session,
                user_id=user.id,
                email=user.email,
                purpose='login_otp',
            )
            session.commit()

            return {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'otp_code': otp_code,
            }

        except AuthenticationError:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to request login OTP: {e}", exc_info=True)
            raise AuthenticationError("Unable to send a login code right now. Please try again.")
        finally:
            session.close()

    @staticmethod
    def request_profile_update_otp(user_id: int) -> dict:
        """Generate and store a one-time code for profile updates."""
        session = Session()
        try:
            user = session.get(User, user_id)
            if not user:
                raise AuthenticationError("User not found")

            if not user.email:
                raise AuthenticationError("This account has no email on file")

            otp_code = AuthService._create_email_verification(
                session,
                user_id=user.id,
                email=user.email,
                purpose='profile_update',
            )
            session.commit()

            return {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'otp_code': otp_code,
            }

        except AuthenticationError:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to request profile OTP: {e}", exc_info=True)
            raise AuthenticationError("Unable to send a verification code right now. Please try again.")
        finally:
            session.close()

    @staticmethod
    def verify_otp(user_id: int, otp_code: str, purpose: str, mark_verified: bool = False, use: bool = True) -> bool:
        """Verify a one-time code for a given purpose. With use=False the code is only checked,
        not spent (for steps that need two codes to be right before either is used)."""
        session = session_factory()
        try:
            user = session.get(User, user_id)
            if not user:
                logger.info(
                    "OTP verification failed: user missing",
                    extra={"user_id": user_id, "purpose": purpose},
                )
                return False

            verification = AuthService._get_latest_email_verification(session, user.id, purpose)
            if not verification:
                logger.info(
                    "OTP verification failed: no active code",
                    extra={"user_id": user_id, "purpose": purpose},
                )
                return False

            if verification.expires_at and verification.expires_at < datetime.now():
                raise AuthenticationError("One-time code has expired")

            if verification.code != otp_code:
                logger.info(
                    "OTP verification failed: code mismatch",
                    extra={"user_id": user_id, "purpose": purpose},
                )
                return False

            if not use:
                return True
            verification.verified_at = datetime.now()
            if mark_verified and not user.is_verified:
                user.is_verified = True
            user.updated_at = datetime.now()
            session.commit()
            return True

        except AuthenticationError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()
    
    @staticmethod
    def verify_email(user_id: int, verification_code: str) -> bool:
        """
        Verify a user's email with the verification code.
        
        Returns:
            True if verification successful, False otherwise
        """
        session = Session()
        try:
            user = session.get(User, user_id)
            
            if not user:
                return False
            
            if user.is_verified:
                return True

            verification = AuthService._get_latest_email_verification(session, user.id, 'verify_email', user.email)
            if not verification:
                return False

            if verification.expires_at and verification.expires_at < datetime.now():
                raise AuthenticationError("Verification code has expired")

            if verification.code != verification_code:
                return False

            verification.verified_at = datetime.now()
            user.is_verified = True
            user.updated_at = datetime.now()
            session.commit()
            return True
            
        except AuthenticationError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()
    
    @staticmethod
    def resend_verification_code(user_id: int) -> str:
        """
        Generate and return a new verification code for a user.
        
        Returns:
            New verification code
        
        Raises:
            AuthenticationError: If user not found or already verified
        """
        session = Session()
        try:
            user = session.get(User, user_id)
            
            if not user:
                raise AuthenticationError("User not found")
            
            if user.is_verified:
                raise AuthenticationError("Email already verified")
            
            verification_code = AuthService._create_email_verification(
                session,
                user_id=user.id,
                email=user.email,
                purpose='verify_email',
            )
            user.updated_at = datetime.now()
            session.commit()
            return verification_code
            
        except AuthenticationError:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to resend verification code: {e}", exc_info=True)
            raise AuthenticationError("Couldn't send a new code right now. Please try again.")
        finally:
            session.close()
    
    @staticmethod
    def authenticate_user(username_or_email: str, password: str) -> Optional[User]:
        """
        Authenticate a user with username/email and password.
        
        Returns:
            User object if authentication successful, None otherwise
        """
        session = Session()
        try:
            # Username or email. One person's username can be another's email address, so each
            # match is tried: taking whichever came first could check the wrong password.
            identifier = (username_or_email or '').strip().lower()
            candidates = session.query(User).filter(
                (User.username == identifier) | (User.email == identifier)
            ).all()
            user = next(
                (c for c in candidates if AuthService.verify_password(password, c.password_hash)),
                None,
            )
            if not user:
                return None
            
            # Check if verified
            if not user.is_verified:
                raise EmailNotVerifiedError(user.id)
            
            return user
            
        except AuthenticationError:
            raise
        except Exception:
            return None
        finally:
            session.close()
    
    @staticmethod
    def change_password(user_id: int, old_password: str, new_password: str) -> bool:
        """
        Change a user's password.
        
        Returns:
            True if successful, False otherwise
        """
        session = Session()
        try:
            user = session.get(User, user_id)
            
            if not user:
                return False
            
            # Verify old password
            if not AuthService.verify_password(old_password, user.password_hash):
                raise AuthenticationError("Current password is incorrect")
            
            new_password = _checked_new_password(new_password)
            
            # Update password
            user.password_hash = AuthService.hash_password(new_password)
            user.updated_at = datetime.now()
            session.commit()
            
            return True
            
        except AuthenticationError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()
