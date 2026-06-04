from django.core.management.base import BaseCommand

from apps.mcp_server.oauth import prune_expired_oauth_artifacts


class Command(BaseCommand):
    help = "Delete expired, used, or revoked MCP OAuth artifacts."

    def handle(self, *args, **options):
        counts = prune_expired_oauth_artifacts()
        total = sum(counts.values())
        self.stdout.write(self.style.SUCCESS(f"Pruned {total} MCP OAuth artifacts: {counts}"))
