from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, cast

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib.auth import get_user_model

from apps.core.choices import EmailType
from apps.core.utils import send_transactional_email
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

User = get_user_model()

if TYPE_CHECKING:
    from apps.core.models import Profile


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Custom adapter to track email confirmations and welcome emails.
    """

    def is_open_for_signup(self, request):
        """Allow operators to pause new registrations without affecting existing users."""
        return getattr(settings, "ALLOW_SIGNUPS", True) and super().is_open_for_signup(request)

    def send_confirmation_mail(self, request, emailconfirmation, signup):
        """
        Override to track email confirmation sends.

        Args:
            request: The HTTP request
            emailconfirmation: The email confirmation object
            signup: Boolean indicating if this is during signup (True) or resend (False)
        """
        email_user = emailconfirmation.email_address.user
        profile: Profile | None = None
        if hasattr(email_user, "profile"):
            profile = cast("Profile", email_user.profile)

        # Track as welcome email during signup, confirmation email on resend
        email_type = EmailType.WELCOME if signup else EmailType.EMAIL_CONFIRMATION
        email_address = emailconfirmation.email_address.email
        context = {
            "flow": "signup" if signup else "confirmation_resend",
            "user_id": emailconfirmation.email_address.user.id,
        }

        logger.info(
            "[Send Confirmation Mail] Sending email",
            signup=signup,
            email_type=email_type,
            user_id=emailconfirmation.email_address.user.id,
            email=email_address,
        )

        success = send_transactional_email(
            lambda: super(CustomAccountAdapter, self).send_confirmation_mail(
                request,
                emailconfirmation,
                signup,
            ),
            email_address=email_address,
            email_type=email_type,
            profile=profile,
            context=context,
        )

        if not success:
            logger.warning(
                "[Send Confirmation Mail] Email send failed after retries",
                signup=signup,
                email_type=email_type,
                user_id=emailconfirmation.email_address.user.id,
                email=email_address,
            )


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter to automatically generate usernames from email addresses
    during social authentication signup, bypassing the username selection page.
    """

    def is_open_for_signup(self, request, sociallogin):
        """Mirror email signup gating for social-account auto-signups."""
        return getattr(settings, "ALLOW_SIGNUPS", True) and super().is_open_for_signup(
            request,
            sociallogin,
        )

    def populate_user(self, request, sociallogin, data):
        """
        Automatically set username from email address before user creation.
        Uses the part before @ symbol as username, ensuring uniqueness.
        """
        user = super().populate_user(request, sociallogin, data)

        if not user.username and user.email:
            base_username = re.sub(r"[^\w]", "", user.email.split("@")[0])
            if not base_username:
                base_username = f"user{uuid.uuid4().hex[:8]}"
            username = base_username

            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user.username = username

        return user
