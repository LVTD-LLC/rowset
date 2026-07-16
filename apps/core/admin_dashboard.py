from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from apps.core.choices import ProfileStates
from apps.core.models import AgentApiKey, Feedback, Profile
from apps.datasets.models import Dataset, DatasetMutation, Project

ADMIN_DASHBOARD_PERIODS = (7, 30)


def _trend(current: int, previous: int) -> dict:
    if current == previous:
        return {"direction": "neutral", "label": "No change"}
    if previous == 0:
        return {"direction": "up", "label": "New"}

    change = round(abs(current - previous) / previous * 100)
    return {
        "direction": "up" if current > previous else "down",
        "label": f"{change}%",
    }


def _daily_counts(queryset, field: str, start) -> dict:
    return {
        item["day"]: item["count"]
        for item in queryset.filter(**{f"{field}__gte": start})
        .annotate(day=TruncDate(field))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    }


def _growth_series(nonstaff_users, profiles, mutations, now, period_days: int) -> list[dict]:
    local_now = timezone.localtime(now)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=period_days - 1
    )
    signups = _daily_counts(nonstaff_users, "date_joined", start)
    setups = _daily_counts(profiles, "setup_completed_at", start)
    mutation_counts = _daily_counts(mutations, "created_at", start)
    today = local_now.date()
    first_day = today - timedelta(days=period_days - 1)
    series = []

    for offset in range(period_days):
        day = first_day + timedelta(days=offset)
        series.append(
            {
                "label": day.strftime("%b %-d"),
                "signups": signups.get(day, 0),
                "setups": setups.get(day, 0),
                "mutations": mutation_counts.get(day, 0),
            }
        )

    scale = max(
        (item["signups"] + item["setups"] + item["mutations"] for item in series),
        default=0,
    )
    scale = max(scale, 1)
    for item in series:
        for metric in ("signups", "setups", "mutations"):
            value = item[metric]
            item[f"{metric.removesuffix('s')}_height_percent"] = (
                max(round(value / scale * 100), 2) if value else 0
            )

    return series


def _activation_funnel(user_stats, profile_stats) -> list[dict]:
    signed_up = user_stats["total"]
    stages = [
        ("Signed up", signed_up),
        ("Completed setup", profile_stats["setup_total"]),
        ("Used an agent key", profile_stats["used_agent_key"]),
        ("Created a dataset", profile_stats["created_agent_dataset"]),
    ]
    return [
        {
            "label": label,
            "count": count,
            "percent": round(count / signed_up * 100) if signed_up else 0,
        }
        for label, count in stages
    ]


def _activity_feed(nonstaff_users, feedback, mutations) -> list[dict]:
    events = []
    for mutation in (
        mutations.select_related("dataset")
        .only("id", "summary", "actor_label", "created_at", "dataset__name")
        .order_by("-created_at", "-id")[:12]
    ):
        events.append(
            {
                "kind": "mutation",
                "title": mutation.summary,
                "detail": f"{mutation.dataset.name} · {mutation.actor_label}",
                "timestamp": mutation.created_at,
                "url": reverse("admin:datasets_datasetmutation_change", args=[mutation.pk]),
            }
        )
    for item in (
        feedback.select_related("profile__user")
        .only("id", "feedback", "created_at", "profile__user__email")
        .order_by("-created_at", "-id")[:12]
    ):
        submitter = item.profile.user.email if item.profile else "Anonymous"
        events.append(
            {
                "kind": "feedback",
                "title": item.feedback,
                "detail": f"Feedback · {submitter}",
                "timestamp": item.created_at,
                "url": reverse("admin:core_feedback_change", args=[item.pk]),
            }
        )
    for user in nonstaff_users.only("id", "email", "username", "date_joined").order_by(
        "-date_joined", "-id"
    )[:12]:
        events.append(
            {
                "kind": "signup",
                "title": "New account created",
                "detail": user.email or user.username,
                "timestamp": user.date_joined,
                "url": reverse("admin:auth_user_change", args=[user.pk]),
            }
        )

    return sorted(events, key=lambda event: event["timestamp"], reverse=True)[:12]


def build_admin_dashboard_context(period_days: int, now=None) -> dict:
    now = now or timezone.now()
    if period_days not in ADMIN_DASHBOARD_PERIODS:
        period_days = ADMIN_DASHBOARD_PERIODS[0]

    local_now = timezone.localtime(now)
    current_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=period_days - 1
    )
    previous_start = current_start - timedelta(days=period_days)
    nonstaff_users = User.objects.filter(is_staff=False, is_superuser=False)
    profiles = Profile.objects.filter(user__is_staff=False, user__is_superuser=False)
    active_keys = AgentApiKey.objects.filter(
        profile__user__is_staff=False,
        profile__user__is_superuser=False,
        revoked_at__isnull=True,
    )
    visible_datasets = Dataset.objects.filter(archived_at__isnull=True)
    visible_projects = Project.objects.filter(archived_at__isnull=True)
    mutations = DatasetMutation.objects.all()
    feedback = Feedback.objects.all()

    user_stats = nonstaff_users.aggregate(
        total=Count("id"),
        current=Count("id", filter=Q(date_joined__gte=current_start, date_joined__lt=now)),
        previous=Count(
            "id", filter=Q(date_joined__gte=previous_start, date_joined__lt=current_start)
        ),
        stalled=Count(
            "id",
            filter=Q(
                date_joined__gte=current_start,
                date_joined__lt=now - timedelta(hours=24),
                profile__setup_completed_at__isnull=True,
            ),
        ),
    )
    profile_stats = profiles.aggregate(
        setup_current=Count(
            "id", filter=Q(setup_completed_at__gte=current_start, setup_completed_at__lt=now)
        ),
        setup_previous=Count(
            "id",
            filter=Q(setup_completed_at__gte=previous_start, setup_completed_at__lt=current_start),
        ),
        setup_total=Count("id", filter=Q(setup_completed_at__isnull=False)),
        trials_expiring=Count(
            "id",
            filter=Q(
                trial_started_at__isnull=False,
                trial_ends_at__gte=now,
                trial_ends_at__lte=now + timedelta(days=3),
            ),
        ),
        active_trials=Count("id", filter=Q(trial_started_at__isnull=False, trial_ends_at__gte=now)),
        subscribers=Count("id", filter=Q(state=ProfileStates.SUBSCRIBED)),
    )
    profile_stats["used_agent_key"] = (
        profiles.filter(agent_api_keys__last_used_at__isnull=False).distinct().count()
    )
    profile_stats["created_agent_dataset"] = (
        profiles.filter(datasets__created_by_agent_api_key__isnull=False).distinct().count()
    )
    key_stats = active_keys.aggregate(
        total=Count("id"),
        current=Count("id", filter=Q(last_used_at__gte=current_start, last_used_at__lt=now)),
        previous=Count(
            "id", filter=Q(last_used_at__gte=previous_start, last_used_at__lt=current_start)
        ),
        unused=Count("id", filter=Q(last_used_at__isnull=True)),
        stale=Count("id", filter=Q(last_used_at__lt=now - timedelta(days=30))),
    )
    mutation_stats = mutations.aggregate(
        current=Count("id", filter=Q(created_at__gte=current_start, created_at__lt=now)),
        previous=Count(
            "id", filter=Q(created_at__gte=previous_start, created_at__lt=current_start)
        ),
    )
    feedback_stats = feedback.aggregate(
        current=Count("id", filter=Q(created_at__gte=current_start)), total=Count("id")
    )
    metrics = {
        "new_users": (user_stats["current"], user_stats["previous"]),
        "setup_completed": (profile_stats["setup_current"], profile_stats["setup_previous"]),
        "active_agents": (key_stats["current"], key_stats["previous"]),
        "mutations": (mutation_stats["current"], mutation_stats["previous"]),
    }
    product_health = {key: values[0] for key, values in metrics.items()}
    product_health_cards = [
        {
            "label": label,
            "value": metrics[key][0],
            "trend": _trend(*metrics[key]),
        }
        for key, label in (
            ("new_users", "New users"),
            ("setup_completed", "Setup completed"),
            ("active_agents", "Active agents"),
            ("mutations", "Mutations"),
        )
    ]

    dataset_summary = visible_datasets.aggregate(
        count=Count("id"),
        rows_stored=Sum("row_count"),
        public_previews=Count("id", filter=Q(public_enabled=True)),
    )
    total_users = user_stats["total"]
    operations = {
        "datasets": dataset_summary["count"],
        "projects": visible_projects.count(),
        "rows_stored": dataset_summary["rows_stored"] or 0,
        "public_previews": dataset_summary["public_previews"] or 0,
        "active_agent_keys": key_stats["total"],
    }
    attention = {
        "stalled_onboarding": user_stats["stalled"],
        "unused_agent_keys": key_stats["unused"],
        "stale_agent_keys": key_stats["stale"],
        "trials_expiring": profile_stats["trials_expiring"],
        "new_feedback": feedback_stats["current"],
    }

    return {
        "period_days": period_days,
        "period_options": ADMIN_DASHBOARD_PERIODS,
        "product_health": product_health,
        "product_health_cards": product_health_cards,
        "activation_funnel": _activation_funnel(user_stats, profile_stats),
        "growth_series": _growth_series(
            nonstaff_users,
            profiles,
            mutations,
            now,
            period_days,
        ),
        "growth": {
            "total_users": total_users,
            "setup_rate": (
                round(profile_stats["setup_total"] / total_users * 100) if total_users else 0
            ),
            "active_trials": profile_stats["active_trials"],
            "subscribers": profile_stats["subscribers"],
        },
        "operations": operations,
        "attention": attention,
        "activity_feed": _activity_feed(nonstaff_users, feedback, mutations),
        "generated_at": now,
        # Compatibility context for integrations that still read the original totals.
        "total_users": User.objects.count(),
        "profile_count": Profile.objects.count(),
        "total_feedback": feedback_stats["total"],
        "total_datasets": operations["datasets"],
        "total_projects": operations["projects"],
        "total_rows": operations["rows_stored"],
        "public_preview_count": operations["public_previews"],
    }
