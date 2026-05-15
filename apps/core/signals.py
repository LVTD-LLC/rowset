from allauth.account.signals import email_confirmed, user_signed_up
from allauth.socialaccount.signals import social_account_added, social_account_updated
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_q.tasks import async_task

from apps.core.models import Profile, ProfileStates
from apps.core.tasks import add_email_to_buttondown
from apps.datasets.google_sheets import (
    GOOGLE_SHEETS_CONNECT_SESSION_KEY,
    GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY,
)
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        profile = Profile.objects.create(user=instance)
        profile.track_state_change(
            to_state=ProfileStates.SIGNED_UP,
            source_function="create_user_profile signal",
        )

    if instance.id == 1:
        # Use update() to avoid triggering the signal again
        User.objects.filter(id=1).update(is_staff=True, is_superuser=True)


@receiver(email_confirmed)
def add_email_to_buttondown_on_confirm(sender, **kwargs):
    logger.info(
        "Adding new user to buttondown newsletter, on email confirmation",
        kwargs=kwargs,
        sender=sender,
    )
    async_task(add_email_to_buttondown, kwargs["email_address"], tag="user")


@receiver(user_signed_up)
def email_confirmation_callback(sender, request, user, **kwargs):
    if 'sociallogin' in kwargs:
        logger.info(
            "Adding new user to buttondown newsletter on social signup",
            kwargs=kwargs,
            sender=sender,
        )
        email = kwargs['sociallogin'].user.email
        if email:
            async_task(add_email_to_buttondown, email, tag="user")


def _mark_google_sheets_connected(request, sociallogin):
    if sociallogin.account.provider != "google":
        return
    if not request.session.pop(GOOGLE_SHEETS_CONNECT_SESSION_KEY, False):
        return
    extra_data = sociallogin.account.extra_data or {}
    extra_data[GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY] = True
    sociallogin.account.extra_data = extra_data
    sociallogin.account.save(update_fields=["extra_data"])


@receiver(social_account_added)
def mark_google_sheets_connected_on_add(sender, request, sociallogin, **kwargs):
    _mark_google_sheets_connected(request, sociallogin)


@receiver(social_account_updated)
def mark_google_sheets_connected_on_update(sender, request, sociallogin, **kwargs):
    _mark_google_sheets_connected(request, sociallogin)
