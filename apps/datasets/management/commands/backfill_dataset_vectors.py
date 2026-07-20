from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from apps.datasets.models import Dataset
from apps.datasets.services import DEFAULT_VECTOR_BACKFILL_BATCH_SIZE, backfill_dataset_vectors


class Command(BaseCommand):
    help = "Backfill Qdrant vectors for rows in one or every active dataset."

    def add_arguments(self, parser):
        parser.add_argument("dataset_key", nargs="?")
        parser.add_argument("--all", action="store_true", dest="all_datasets")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--batch-size", type=int, default=DEFAULT_VECTOR_BACKFILL_BATCH_SIZE)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--stop-on-error", action="store_true")

    def handle(self, *args, **options):
        dataset_key = options["dataset_key"]
        all_datasets = options["all_datasets"]
        if bool(dataset_key) == bool(all_datasets):
            raise CommandError("Provide one dataset_key or --all.")
        if all_datasets:
            datasets = Dataset.objects.filter(archived_at__isnull=True).order_by("id")
        else:
            try:
                datasets = [Dataset.objects.get(key=dataset_key)]
            except Dataset.DoesNotExist as exc:
                raise CommandError(f"Dataset {dataset_key!r} was not found.") from exc

        totals = {"rows_seen": 0, "indexed": 0, "would_index": 0, "failed": 0}
        for dataset in datasets:
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
            except Exception as exc:
                raise CommandError(f"Vector backfill failed: {exc}") from exc
            for field in totals:
                totals[field] += getattr(result, field)

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{totals['would_index']} row(s) would be indexed; "
                    f"{totals['indexed']} indexed, {totals['failed']} failed."
                )
            )
            return

        message = (
            f"Vector backfill complete: {totals['indexed']} indexed, "
            f"{totals['failed']} failed, {totals['rows_seen']} row(s) seen."
        )
        if totals["failed"]:
            raise CommandError(message)
        self.stdout.write(self.style.SUCCESS(message))
