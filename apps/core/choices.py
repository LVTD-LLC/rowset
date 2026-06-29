from django.db import models


class AgentApiKeyAccessLevel(models.TextChoices):
    READ = "read", "Read"
    READ_WRITE = "read_write", "Read + write"
    ADMIN = "admin", "Admin"


class ProfileStates(models.TextChoices):
    STRANGER = "stranger"
    SIGNED_UP = "signed_up"
    FREE = (
        "free"  # This can be used for Freemium apps, and will be set when core action is completed
    )

    TRIAL_STARTED = "trial_started"  # This can be used in apps with Trials
    TRIAL_ENDED = "trial_ended"
    SUBSCRIBED = "subscribed"
    CANCELLED = "cancelled"  # when user cancels their subscription, but still have access
    CHURNED = "churned"  # when user lost access to paid features

    ACCOUNT_DELETED = "account_deleted"


class EmailType(models.TextChoices):
    EMAIL_CONFIRMATION = "EMAIL_CONFIRMATION", "Email Confirmation"
    WELCOME = "WELCOME", "Welcome"
    FEEDBACK_NOTIFICATION = "FEEDBACK_NOTIFICATION", "Feedback Notification"
