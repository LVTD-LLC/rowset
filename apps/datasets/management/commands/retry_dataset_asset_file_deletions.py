from django.core.management.base import BaseCommand

from apps.datasets.models import retry_dataset_asset_file_deletions


class Command(BaseCommand):
    help = "Retry failed dataset asset file deletions."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        result = retry_dataset_asset_file_deletions(limit=options["limit"])
        message = (
            f"Attempted {result['attempted']} deletion(s): "
            f"{result['deleted']} deleted, {result['failed']} failed."
        )
        if result["failed"]:
            self.stdout.write(self.style.WARNING(message))
        else:
            self.stdout.write(self.style.SUCCESS(message))
