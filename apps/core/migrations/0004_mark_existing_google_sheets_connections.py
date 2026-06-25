from django.db import migrations

# Historical key written by this already-applied migration. Keep it stable for
# migration fidelity; use a new forward migration for any production data rename.
GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY = "filebridge_google_sheets_connected"


def mark_existing_google_sheets_connections(apps, schema_editor):
    SocialAccount = apps.get_model("socialaccount", "SocialAccount")
    SocialToken = apps.get_model("socialaccount", "SocialToken")
    google_account_ids = SocialToken.objects.filter(
        account__provider="google",
    ).values_list("account_id", flat=True)

    for account in SocialAccount.objects.filter(id__in=google_account_ids).iterator():
        extra_data = account.extra_data or {}
        if extra_data.get(GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY) is True:
            continue
        extra_data[GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY] = True
        account.extra_data = extra_data
        account.save(update_fields=["extra_data"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_profile_agent_setup_prompt_dismissed"),
        ("socialaccount", "0006_alter_socialaccount_extra_data"),
    ]

    operations = [
        migrations.RunPython(mark_existing_google_sheets_connections, migrations.RunPython.noop),
    ]
