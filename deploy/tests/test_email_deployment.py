from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class EmailDeploymentTests(unittest.TestCase):
    def test_worker_stays_disabled_until_test_credentials_and_target_exist(self):
        values = (ROOT / "helm/myota/values.yaml").read_text()
        email_values = values.split("  email:\n", 1)[1].split("activityWorkers:", 1)[0]
        self.assertIn("enabled: false", email_values)
        self.assertIn("ghcr.io/myota-platform/myota-email-service", email_values)
        self.assertIn("smtpSecret: myota-email-runtime", email_values)
        self.assertIn("identitySecret: myota-email-runtime", email_values)

    def test_smtp_password_and_identity_client_secret_are_secret_references(self):
        deployment = (ROOT / "helm/myota/templates/deployment.yaml").read_text()
        config = (ROOT / "helm/myota/templates/email-config.yaml").read_text()
        self.assertIn("key: {{ $cfg.smtpPasswordKey }}", deployment)
        self.assertIn("key: {{ $cfg.identityClientSecretKey }}", deployment)
        self.assertNotIn("EMAIL_SMTP_PASSWORD", config)
        self.assertNotIn("MYOTA_EMAIL_SERVICE_CLIENT_SECRET", config)
        for safe_key in (
            "EMAIL_SENDER_ADDRESS",
            "EMAIL_SENDER_DISPLAY_NAME",
            "EMAIL_SMTP_HOST",
            "EMAIL_SMTP_PORT",
            "EMAIL_SMTP_USERNAME",
            "EMAIL_SMTP_TLS_MODE",
            "EMAIL_SMTP_TIMEOUT_SECONDS",
        ):
            self.assertIn(safe_key, config)

    def test_worker_has_internal_metrics_and_readiness_without_ingress(self):
        service = (ROOT / "helm/myota/templates/service.yaml").read_text()
        deployment = (ROOT / "helm/myota/templates/deployment.yaml").read_text()
        ingress = (ROOT / "helm/myota/templates/ingress.yaml").read_text()
        self.assertIn("{{- if ne $cfg.enabled false }}", service)
        self.assertIn("path: /readyz, port: http", deployment)
        self.assertIn("path: /healthz, port: http", deployment)
        self.assertNotIn("email:", ingress)

    def test_testing_is_the_only_email_image_publish_target(self):
        workflow = (ROOT.parent / ".github/workflows/email.yml").read_text()
        digest_sync = (ROOT / "scripts/sync-image-digests.py").read_text()
        self.assertIn("refs/heads/testing", workflow)
        self.assertIn("myota-email-service:testing", workflow)
        self.assertIn("myota-email-service:testing-${{ github.sha }}", workflow)
        self.assertNotIn("myota-email-service:latest", workflow)
        self.assertIn('TEST_IMAGES["email"]', digest_sync)

    def test_email_database_is_isolated_and_uses_a_separate_app_role(self):
        postgres = (ROOT / "helm/myota/templates/postgres.yaml").read_text()
        deployment = (ROOT / "helm/myota/templates/deployment.yaml").read_text()
        self.assertIn("name: myota-email-postgres", postgres)
        self.assertIn("POSTGRES_DB, value: myota_email", postgres)
        self.assertIn('key: app-password', postgres)
        self.assertIn("name: EMAIL_DATABASE_URL", deployment)
        self.assertIn("/run/secrets/email-database-url", (ROOT / "compose.yaml").read_text())

    def test_email_stream_job_requires_explicit_capacity_and_review_gate(self):
        template = (
            ROOT / "helm/myota/templates/email-jetstream-provisioner.yaml"
        ).read_text()
        self.assertIn('NATS_TOPOLOGY_SCOPE, value: "email-work"', template)
        self.assertIn("confirmedMigrationGate", template)
        for key in (
            "emailWorkMaxAgeSeconds",
            "emailWorkMaxBytes",
            "emailWorkMaxMessages",
            "emailWorkMaxMessageBytes",
        ):
            self.assertIn(key, template)


if __name__ == "__main__":
    unittest.main()
