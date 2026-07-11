from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Profile
from apps.datasets.models import Dataset, DatasetRow, Project, ProjectSection

PROJECT_SPECS = (
    (
        "Product launch",
        "Planning and execution data for the next Rowset product launch.",
        ("Sales", "Content", "Operations"),
        (
            ("Accounts", "Sales"),
            ("Pipeline", "Sales"),
            ("Editorial calendar", "Content"),
            ("Content performance", "Content"),
            ("Vendors", "Operations"),
            ("Launch checklist", "Operations"),
            ("Customer interviews", None),
            ("Meeting notes", None),
            ("Research inbox", None),
        ),
    ),
    (
        "Customer research",
        "Customer evidence, interview programs, and synthesized product insights.",
        ("Interviews", "Insights"),
        (
            ("Interview participants", "Interviews"),
            ("Interview schedule", "Interviews"),
            ("Pain point library", "Insights"),
            ("Feature requests", "Insights"),
            ("Research sources", None),
        ),
    ),
    (
        "Operations hub",
        "Recurring finance, vendor, and people operations for the company.",
        ("Finance", "Vendors", "Hiring"),
        (
            ("Monthly budget", "Finance"),
            ("Invoices", "Finance"),
            ("Vendor directory", "Vendors"),
            ("Contract renewals", "Vendors"),
            ("Candidates", "Hiring"),
            ("Interview scorecards", "Hiring"),
        ),
    ),
    (
        "Growth experiments",
        "Experiment planning and results across the customer journey.",
        ("Acquisition", "Activation", "Retention"),
        (
            ("Channel tests", "Acquisition"),
            ("Campaign performance", "Acquisition"),
            ("Onboarding experiments", "Activation"),
            ("Activation cohorts", "Activation"),
            ("Churn interviews", "Retention"),
            ("Lifecycle campaigns", "Retention"),
        ),
    ),
)
STATUSES = ("Planned", "In progress", "Review", "Done", "Blocked")
OWNERS = ("Maya", "Theo", "Sam", "Alex", "Jordan")


class Command(BaseCommand):
    help = "Create an idempotent project/section/dataset workspace for dashboard design work."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Account that should own the demo data.")
        parser.add_argument(
            "--password",
            help="Create the local account with this password when the email does not exist.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options.get("password")
        if not email:
            raise CommandError("--email must not be blank.")

        user_model = get_user_model()
        user = user_model.objects.filter(email__iexact=email).order_by("id").first()
        user_created = False
        if user is None:
            if not password:
                raise CommandError(
                    "No account has that email. Pass --password to create a local account."
                )
            username = self._available_username(user_model, email)
            user = user_model.objects.create_user(
                username=username,
                email=email,
                password=password,
            )
            user_created = True

        profile, _profile_created = Profile.objects.get_or_create(user=user)
        if not profile.agent_setup_prompt_dismissed:
            profile.agent_setup_prompt_dismissed = True
            profile.save(update_fields=["agent_setup_prompt_dismissed", "updated_at"])

        for project_name, project_description, section_names, dataset_specs in PROJECT_SPECS:
            project, _project_created = Project.objects.update_or_create(
                profile=profile,
                name=project_name,
                archived_at__isnull=True,
                defaults={"description": project_description},
            )
            sections = {
                name: ProjectSection.objects.update_or_create(
                    profile=profile,
                    project=project,
                    name=name,
                    archived_at__isnull=True,
                    defaults={"description": f"{name} workstreams and supporting datasets."},
                )[0]
                for name in section_names
            }

            for dataset_name, section_name in dataset_specs:
                dataset, _dataset_created = Dataset.objects.update_or_create(
                    profile=profile,
                    name=dataset_name,
                    archived_at__isnull=True,
                    defaults={
                        "project": project,
                        "section": sections.get(section_name),
                        "description": f"Demo records for {dataset_name.lower()}.",
                        "headers": ["rowset_id", "item", "status", "owner"],
                        "column_schema": {
                            "rowset_id": {"type": "integer"},
                            "item": {"type": "text"},
                            "status": {"type": "choice", "choices": list(STATUSES)},
                            "owner": {"type": "text"},
                        },
                        "index_column": "rowset_id",
                        "index_generated": True,
                        "row_count": len(STATUSES),
                    },
                )
                for row_number, (status, owner) in enumerate(
                    zip(STATUSES, OWNERS, strict=True), start=1
                ):
                    DatasetRow.objects.update_or_create(
                        dataset=dataset,
                        row_number=row_number,
                        defaults={
                            "index_value": str(row_number),
                            "data": {
                                "rowset_id": str(row_number),
                                "item": f"{dataset_name} item {row_number}",
                                "status": status,
                                "owner": owner,
                            },
                        },
                    )
                dataset.rows.filter(row_number__gt=len(STATUSES)).delete()

        action = "created" if user_created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Dashboard demo {action} for {email}: 4 projects, 11 sections, "
                "26 datasets, 130 rows."
            )
        )

    @staticmethod
    def _available_username(user_model, email):
        base = email.split("@", maxsplit=1)[0][:140] or "demo"
        candidate = base
        suffix = 1
        while user_model.objects.filter(username=candidate).exists():
            suffix += 1
            candidate = f"{base[: 149 - len(str(suffix))]}-{suffix}"
        return candidate
