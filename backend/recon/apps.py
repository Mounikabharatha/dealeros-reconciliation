from django.apps import AppConfig


class ReconConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "recon"

    def ready(self):
        # Registers the connection_created handler that drops every
        # application connection to the restricted database role.
        from . import db  # noqa: F401
