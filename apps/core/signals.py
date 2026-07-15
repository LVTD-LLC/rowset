from allauth.account.signals import email_confirmed, user_signed_up
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_q.tasks import async_task

from apps.core.choices import TrialReward
from apps.core.models import Profile, ProfileStates
from apps.core.tasks import add_email_to_buttondown
from apps.core.trials import claim_trial_reward
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


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
    job_id = async_task(add_email_to_buttondown, kwargs["email_address"], tag="user")
    logger.info(
        "newsletter.subscription.queued",
        trigger="email_confirmation",
        outcome="success",
        **{"job.id": str(job_id)},
    )


@receiver(email_confirmed, dispatch_uid="rowset.claim_email_verification_trial_reward")
def claim_email_verification_trial_reward(sender, email_address, **kwargs):  # noqa: ARG001
    profile = email_address.user.profile
    if not profile.has_active_subscription:
        claim_trial_reward(profile, TrialReward.EMAIL_VERIFIED)


@receiver(user_signed_up)
def email_confirmation_callback(sender, request, user, **kwargs):
    if "sociallogin" in kwargs:
        email = kwargs["sociallogin"].user.email
        if email:
            job_id = async_task(add_email_to_buttondown, email, tag="user")
            logger.info(
                "newsletter.subscription.queued",
                trigger="social_signup",
                user_id=user.id,
                outcome="success",
                **{"job.id": str(job_id)},
            )
