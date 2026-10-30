"""
Email service for sending verification codes and admin notifications.
"""
import html

import requests
from flask_mail import Mail, Message
from flask import current_app
from typing import Optional
from utils.logger import logger
from config import Config


# ---------------------------------------------------------------------------
# One calm layout for every account email. Tables and inline styles so it looks
# the same in Gmail, Outlook and Apple Mail; Apple Mail also gets a dark version.
# ---------------------------------------------------------------------------

_EMAIL_DARK_CSS = """
    @media (prefers-color-scheme: dark) {
        .wt-bg { background: #000000 !important; }
        .wt-card { background: #111113 !important; border-color: #26262a !important; }
        .wt-t1 { color: #f5f5f5 !important; }
        .wt-t2 { color: #a1a1aa !important; }
        .wt-t3 { color: #71717a !important; }
        .wt-codebox { background: #1a1608 !important; border-color: #3d3314 !important; }
        .wt-code { color: #f4d03f !important; }
        .wt-hair { border-color: #26262a !important; }
    }
"""


def _email_page(preheader: str, inner_html: str) -> str:
    """Wrap card content in the shared email shell (brand, card, footer)."""
    font = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>Liftbook</title>
<style>{_EMAIL_DARK_CSS}</style>
</head>
<body class="wt-bg" style="margin:0;padding:0;background:#f4f2ee;-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{html.escape(preheader)}&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>
<table role="presentation" class="wt-bg" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f2ee;">
<tr><td align="center" style="padding:40px 16px 48px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px;">
    <tr><td style="padding:0 4px 22px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td width="34" height="34" align="center" valign="middle" style="width:34px;height:34px;background:#0b0b0d;border-radius:10px;font-family:{font};font-size:12px;font-weight:700;letter-spacing:0.5px;color:#d4af37;">LB</td>
        <td class="wt-t1" style="padding-left:12px;font-family:{font};font-size:15px;font-weight:600;color:#1a1a1a;">Liftbook</td>
      </tr></table>
    </td></tr>
    <tr><td class="wt-card" style="background:#ffffff;border:1px solid #e8e4dc;border-radius:18px;padding:36px 32px 32px;font-family:{font};">
      {inner_html}
    </td></tr>
    <tr><td class="wt-t3" align="center" style="padding:22px 16px 0;font-family:{font};font-size:12px;line-height:1.6;color:#9a958a;">
      Sent by Liftbook. Replies to this address aren't read.
    </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""


def _email_title(text: str) -> str:
    return (
        f'<h1 class="wt-t1" style="margin:0 0 12px;font-size:22px;line-height:1.3;font-weight:600;color:#111111;">'
        f'{text}</h1>'
    )


def _email_text(text: str, muted: bool = False, top: int = 0) -> str:
    color, cls, size = ('#8a8579', 'wt-t3', 13) if muted else ('#55524c', 'wt-t2', 15)
    return (
        f'<p class="{cls}" style="margin:{top}px 0 0;font-size:{size}px;line-height:1.6;color:{color};">{text}</p>'
    )


def _code_email_html(preheader: str, title: str, intro: str, code: str, expiry: str, notes: list[str]) -> str:
    """Card for any email whose job is to deliver a 6-digit code."""
    mono = "'SF Mono', SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
    code_box = f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 12px;">
        <tr><td class="wt-codebox" align="center" style="background:#faf6ea;border:1px solid #ece2c4;border-radius:14px;padding:22px 12px;">
          <div class="wt-code" style="font-family:{mono};font-size:34px;line-height:1;font-weight:700;letter-spacing:10px;padding-left:10px;color:#1a1a1a;">{html.escape(code)}</div>
        </td></tr>
      </table>"""
    parts = [
        _email_title(title),
        _email_text(intro),
        code_box,
        f'<p class="wt-t3" align="center" style="margin:0;font-size:13px;line-height:1.6;color:#8a8579;text-align:center;">{expiry}</p>',
    ]
    for i, note in enumerate(notes):
        parts.append(_email_text(note, muted=(i == len(notes) - 1), top=22 if i == 0 else 10))
    return _email_page(preheader, '\n'.join(parts))


# purpose -> (subject, title, what the code does)
_CODE_EMAILS = {
    'login_otp': ('Your sign-in code', 'Your sign-in code', 'sign in to Liftbook'),
    'forgot_password': ('Your password reset code', 'Reset your password', 'reset your password'),
    'change_password': ('Your password change code', 'Confirm password change', 'change your password'),
    'verify_email': ('Confirm your email for Liftbook', 'Confirm your email', 'confirm your email and finish setting up your account'),
    'change_email_old': ('Confirm your email change', 'Confirm email change', "confirm it's you"),
    'change_email_new': ('Confirm your new email', 'Confirm your new email', 'confirm this address'),
    'profile_update': ('Your profile update code', 'Confirm profile update', 'save changes to your profile'),
}


class EmailService:
    
    def __init__(self, mail: Mail):
        self.mail = mail

    def _send_message(self, subject: str, recipients: list[str], body: str, html: Optional[str] = None) -> bool:
        try:
            brevo_api_key = current_app.config.get('BREVO_API_KEY')
            if brevo_api_key:
                sender_email = current_app.config.get('BREVO_SENDER_EMAIL')
                sender_name = current_app.config.get('BREVO_SENDER_NAME', 'Liftbook')

                if not sender_email:
                    logger.error("Brevo email not sent: BREVO_SENDER_EMAIL is not set")
                    return False

                payload = {
                    'sender': {
                        'email': sender_email,
                        'name': sender_name,
                    },
                    'to': [{'email': r} for r in recipients],
                    'subject': subject,
                    'textContent': body,
                }
                if html:
                    payload['htmlContent'] = html

                resp = requests.post(
                    'https://api.brevo.com/v3/smtp/email',
                    headers={
                        'accept': 'application/json',
                        'content-type': 'application/json',
                        'api-key': brevo_api_key,
                    },
                    json=payload,
                    timeout=20,
                )

                if 200 <= resp.status_code < 300:
                    logger.info(f"Brevo email sent to {', '.join(recipients)}")
                    return True

                logger.error(
                    f"Brevo email failed (status={resp.status_code}): {resp.text}"
                )
                return False

            msg = Message(
                subject=subject,
                recipients=recipients,
                body=body,
                html=html,
            )
            self.mail.send(msg)
            logger.info(f"SMTP email sent to {', '.join(recipients)}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {', '.join(recipients)}: {e}", exc_info=True)
            return False

    def send_otp_email(self, email: str, username: str, otp_code: str, purpose: str = 'login') -> bool:
        """Send a one-time passcode email for verification flows."""
        try:
            normalized_purpose = {'login': 'login_otp'}.get(purpose, purpose)
            subject, title, action = _CODE_EMAILS.get(
                normalized_purpose,
                ('Your verification code', 'Your verification code', 'complete your request'),
            )

            if normalized_purpose == 'verify_email':
                expiry = f"{Config.VERIFICATION_TOKEN_EXPIRY} hours"
            else:
                expiry = f"{Config.OTP_TOKEN_EXPIRY_MINUTES} minutes"

            name = html.escape(username)
            if normalized_purpose == 'verify_email':
                intro = f"Hi {name}, welcome to Liftbook! Enter this code to {action}."
            else:
                intro = f"Hi {name}, enter this code to {action}."

            notes = []
            if normalized_purpose == 'login_otp':
                notes.append("Once you're in, you'll be asked to choose a new password.")
            elif normalized_purpose == 'change_email_old':
                notes.append("We've also sent a code to your new address. You'll need both to finish the change.")
            elif normalized_purpose == 'change_email_new':
                notes.append("You'll also need the code we sent to your current email.")
            if normalized_purpose == 'verify_email':
                notes.append("Didn't sign up? You can ignore this email and no account will be activated.")
            else:
                notes.append("Didn't ask for this? You can ignore this email. Nobody can get in without the code.")

            plain_intro = intro.replace(name, username)
            body = "\n\n".join([
                plain_intro,
                otp_code,
                f"The code works for {expiry}.",
                *notes,
                "Liftbook",
            ]) + "\n"

            html_body = _code_email_html(
                preheader=f"{otp_code} is your code. It works for {expiry}.",
                title=title,
                intro=intro,
                code=otp_code,
                expiry=f"Works for {expiry}",
                notes=notes,
            )

            return self._send_message(subject=subject, recipients=[email], body=body, html=html_body)

        except Exception as e:
            logger.error(f"Failed to send OTP email to {email}: {e}", exc_info=True)
            return False

    def send_verification_email(self, email: str, username: str, verification_code: str) -> bool:
        """Send the sign-up verification code (same email as the verify_email OTP)."""
        return self.send_otp_email(email, username, verification_code, purpose='verify_email')

    def send_account_deletion_email(
        self, 
        email: str, 
        username: str, 
        admin_message: str,
        admin_username: str
    ) -> bool:
        """
        Send account deletion notification to user.
        
        Args:
            email: User's email address
            username: User's username
            admin_message: Custom message from admin explaining deletion reason
            admin_username: Username of the admin who deleted the account
        
        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            subject = "Liftbook Account Deleted"
            
            body = f"""
Hello {username.title()},

Your Liftbook account has been deleted by an administrator.

Reason from Administrator ({admin_username}):
{admin_message}

If you believe this was done in error, please contact support.

Best regards,
The Liftbook team
            """
            
            html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a1a 100%);
            padding: 40px 20px;
            line-height: 1.6;
        }}
        .container {{ 
            max-width: 600px;
            margin: 0 auto;
            background: rgba(20, 20, 20, 0.95);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(220, 38, 38, 0.2);
        }}
        .header {{ 
            background: linear-gradient(135deg, rgba(220, 38, 38, 0.15) 0%, rgba(220, 38, 38, 0.05) 100%);
            padding: 40px 30px;
            text-align: center;
            border-bottom: 1px solid rgba(220, 38, 38, 0.3);
        }}
        .header h1 {{
            color: #DC2626;
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 8px;
            text-shadow: 0 2px 10px rgba(220, 38, 38, 0.3);
        }}
        .header p {{
            color: rgba(220, 38, 38, 0.7);
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }}
        .content {{ 
            padding: 40px 30px;
            color: rgba(255, 255, 255, 0.9);
        }}
        .content h2 {{
            color: #D4AF37;
            font-size: 22px;
            margin-bottom: 20px;
            font-weight: 500;
        }}
        .content p {{
            color: rgba(255, 255, 255, 0.7);
            margin-bottom: 16px;
            font-size: 15px;
        }}
        .message-box {{ 
            background: rgba(220, 38, 38, 0.05);
            border-left: 4px solid #DC2626;
            padding: 20px;
            margin: 25px 0;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(220, 38, 38, 0.1);
        }}
        .message-box h3 {{
            color: #DC2626;
            font-size: 16px;
            margin-bottom: 12px;
            font-weight: 600;
        }}
        .message-box p {{
            color: rgba(255, 255, 255, 0.8);
            font-style: italic;
        }}
        .highlight {{
            color: #D4AF37;
            font-weight: 600;
        }}
        .footer {{ 
            text-align: center;
            padding: 30px;
            color: rgba(255, 255, 255, 0.4);
            font-size: 12px;
            border-top: 1px solid rgba(212, 175, 55, 0.1);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏋️ LIFTBOOK</h1>
            <p>Account Deletion Notice</p>
        </div>
        <div class="content">
            <h2>Hello {username.title()},</h2>
            <p>Your <span class="highlight">Liftbook</span> account has been deleted by an administrator.</p>
            
            <div class="message-box">
                <h3>Reason from Administrator ({admin_username}):</h3>
                <p>{admin_message}</p>
            </div>
            
            <p>If you believe this was done in error, please contact support.</p>
            
            <p style="margin-top: 30px;">Best regards,<br><span class="highlight">The Liftbook team</span></p>
        </div>
        <div class="footer">
            <p>This is an automated message, please do not reply.</p>
        </div>
    </div>
</body>
</html>
            """
            
            return self._send_message(subject=subject, recipients=[email], body=body, html=html_body)
            
        except Exception as e:
            logger.error(f"Failed to send deletion email to {email}: {e}", exc_info=True)
            return False
    
    def send_welcome_email(self, email: str, username: str) -> bool:
        """Send welcome email after successful verification."""
        try:
            subject = "Welcome to Liftbook"
            features = [
                ("Log", "Type a workout the way you'd write it in your notes."),
                ("Retrieve", "Pull up last session's plan before you lift."),
                ("Stats", "Watch every lift add up over weeks and months."),
            ]

            body = "\n\n".join([
                f"Hi {username}, your email is confirmed and you're all set.",
                "\n".join(f"- {name}: {text}" for name, text in features),
                "Liftbook",
            ]) + "\n"

            rows = "".join(
                f"""<tr><td class="wt-hair" style="padding:14px 0;border-top:1px solid #efebe3;">
                    <div class="wt-t1" style="font-size:15px;font-weight:600;color:#111111;">{name}</div>
                    <div class="wt-t2" style="font-size:14px;line-height:1.5;color:#6b675e;margin-top:2px;">{text}</div>
                </td></tr>"""
                for name, text in features
            )
            inner = "\n".join([
                _email_title("You're all set"),
                _email_text(f"Hi {html.escape(username)}, your email is confirmed. Here's what you can do:"),
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:20px;">{rows}</table>',
                _email_text("Happy lifting.", muted=True, top=18),
            ])
            html_body = _email_page("Your email is confirmed. Here's how to get started.", inner)

            return self._send_message(subject=subject, recipients=[email], body=body, html=html_body)

        except Exception as e:
            logger.error(f"Failed to send welcome email to {email}: {e}", exc_info=True)
            return False
