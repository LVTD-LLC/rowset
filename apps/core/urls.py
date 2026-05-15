from django.urls import path

from apps.core import views

urlpatterns = [
    # App pages
    path("home", views.HomeView.as_view(), name="home"),
    path("settings", views.UserSettingsView.as_view(), name="settings"),
    path(
        "settings/connect-google-sheets/",
        views.connect_google_sheets,
        name="connect_google_sheets",
    ),
    path("admin-panel", views.AdminPanelView.as_view(), name="admin_panel"),
    path(
        "SKILL.md",
        views.agent_instructions_filebridge_mcp,
        name="agent_instructions_filebridge_mcp",
    ),
    path(
        "home/dismiss-agent-setup/",
        views.dismiss_agent_setup_prompt,
        name="dismiss_agent_setup_prompt",
    ),
    # Utils
    path("resend-confirmation/", views.resend_confirmation_email, name="resend_confirmation"),
    path("delete-account/", views.delete_account, name="delete_account"),
    # Payments
    path("stripe-webhook/", views.stripe_webhook, name="stripe_webhook"),
    path(
        "create-checkout-session/<int:pk>/<str:plan>/",
        views.create_checkout_session,
        name="user_upgrade_checkout_session",
    ),
    path(
      "create-customer-portal/",
      views.create_customer_portal_session,
      name="create_customer_portal_session"
    ),
    
]
