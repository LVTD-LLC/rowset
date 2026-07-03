from django.core.management.base import BaseCommand, CommandError

from apps.blog.services import BlogPostSourceError, sync_blog_posts_from_markdown


class Command(BaseCommand):
    help = "Sync repo-tracked Markdown blog posts into BlogPost rows."

    def add_arguments(self, parser):
        parser.add_argument("--content-dir")

    def handle(self, *args, **options):
        try:
            result = sync_blog_posts_from_markdown(options["content_dir"])
        except BlogPostSourceError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Blog post sync complete: scanned {result.scanned}, "
                f"created {result.created}, updated {result.updated}."
            )
        )
