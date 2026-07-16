from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.post_deploy_smoke import (
    SMOKE_STAGES,
    PostDeploySmokeRunner,
    SmokeTestError,
    validate_smoke_base_url,
)


class Command(BaseCommand):
    help = "Run the authenticated post-deployment REST, MCP, dataset, and worker smoke test."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            default=settings.SITE_URL,
            help="Deployed Rowset base URL. Defaults to SITE_URL.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=30.0,
            help="Per-request and worker timeout in seconds (default: 30).",
        )
        parser.add_argument(
            "--fail-after",
            choices=SMOKE_STAGES,
            help="Force a failure after a stage to verify cleanup.",
        )

    def handle(self, *args, **options):
        try:
            validate_smoke_base_url(options["base_url"], settings.SITE_URL)
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        runner = PostDeploySmokeRunner(
            base_url=options["base_url"],
            timeout=options["timeout"],
            fail_after=options["fail_after"],
            report=self.stdout.write,
        )
        try:
            runner.run()
        except SmokeTestError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS("Authenticated post-deployment smoke test passed."))
