from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from apps.datasets.models import Dataset
from apps.datasets.vector_indexing import backfill_dataset_vectors


class Command(BaseCommand):
    help = "Backfill Qdrant vectors for rows in one ready dataset."

    def add_arguments(self, parser):
        parser.add_argument("dataset_key")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--stop-on-error", action="store_true")

    def handle(self, *args, **options):
        dataset_key = options["dataset_key"]
        try:
            dataset = Dataset.objects.get(key=dataset_key)
        except Dataset.DoesNotExist as exc:
            raise CommandError(f"Dataset {dataset_key!r} was not found.") from exc

        try:
            result = backfill_dataset_vectors(
                dataset,
                dry_run=options["dry_run"],
                limit=options["limit"],
                batch_size=options["batch_size"],
                stop_on_error=options["stop_on_error"],
            )
        except (ImproperlyConfigured, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{result.would_index} row(s) would be indexed; "
                    f"{result.indexed} indexed, {result.failed} failed."
                )
            )
            return

        message = (
            f"Vector backfill complete: {result.indexed} indexed, "
            f"{result.failed} failed, {result.rows_seen} row(s) seen."
        )
        if result.failed:
            self.stdout.write(self.style.WARNING(message))
        else:
            self.stdout.write(self.style.SUCCESS(message))
