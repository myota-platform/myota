import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parents[1]


class ObservabilityConfigurationTests(unittest.TestCase):
    def test_all_provisioned_dashboards_have_requested_defaults_and_match_helm(
        self,
    ):
        for source in (ROOT / "observability/grafana/dashboards").glob(
            "*.json"
        ):
            dashboard = json.loads(source.read_text())
            mirror = (
                ROOT
                / "helm/myota/observability/grafana/dashboards"
                / source.name
            )
            chart_dashboard = json.loads(
                mirror.read_text().replace("{{MYOTA_NAMESPACE}}", "myota")
            )
            self.assertEqual(dashboard, chart_dashboard)
            self.assertEqual(
                dashboard["time"], {"from": "now-30m", "to": "now"}
            )
            self.assertEqual(dashboard["refresh"], "30s")
            self.assertEqual(dashboard["timezone"], "utc")
            self.assertIsInstance(dashboard["editable"], bool)

    def test_complete_dashboard_set_matches_between_compose_and_helm(self):
        def inventory(directory):
            result = {}
            for path in directory.rglob("*.json"):
                data = json.loads(
                    path.read_text().replace("{{MYOTA_NAMESPACE}}", "myota")
                )
                self.assertNotIn(data["uid"], result, path)
                result[data["uid"]] = data
            return result

        self.assertEqual(
            inventory(ROOT / "observability/grafana/dashboards"),
            inventory(ROOT / "helm/myota/observability/grafana/dashboards"),
        )

    def test_trace_to_log_query_filters_structured_metadata(self):
        import yaml

        for prefix in ("observability", "helm/myota/observability"):
            config = yaml.safe_load(
                (
                    ROOT
                    / prefix
                    / "grafana/provisioning/datasources/datasources.yml"
                ).read_text()
            )
            tempo = next(
                d for d in config["datasources"] if d["uid"] == "myota-tempo"
            )
            query = tempo["jsonData"]["tracesToLogsV2"]
            self.assertTrue(query["customQuery"])
            self.assertFalse(query["filterByTraceID"])
            self.assertEqual(
                query["query"], '{$${__tags}} | trace_id="$${__span.traceId}"'
            )

    def test_compose_loki_bucket_init_uses_the_shipped_cli_and_runtime_credentials(
        self,
    ):
        import yaml

        services = yaml.safe_load((ROOT / "compose.yaml").read_text())[
            "services"
        ]
        init = services["loki-bucket-init"]
        self.assertIn("aws-cli", init["image"])
        self.assertEqual(len(init["command"]), 1)
        script = init["command"][0]
        self.assertIn("aws s3api head-bucket", script)
        self.assertIn("aws s3api create-bucket", script)
        self.assertNotIn("mc ", script)
        self.assertIn("--acl private", script)
        self.assertIn("$$AWS_ENDPOINT_URL", script)
        self.assertIn("$$AWS_DEFAULT_REGION", script)
        self.assertEqual(
            init["environment"]["AWS_ACCESS_KEY_ID"],
            services["loki"]["environment"]["AWS_ACCESS_KEY_ID"],
        )
        self.assertEqual(
            init["environment"]["AWS_SECRET_ACCESS_KEY"],
            services["loki"]["environment"]["AWS_SECRET_ACCESS_KEY"],
        )
        self.assertIn(
            "${MYOTA_OBJECT_STORAGE_SECRET_KEY",
            init["environment"]["AWS_SECRET_ACCESS_KEY"],
        )
        self.assertEqual(
            services["loki"]["depends_on"]["loki-bucket-init"]["condition"],
            "service_completed_successfully",
        )

    def test_compose_bootstrap_scripts_are_single_shell_arguments_and_sql_is_reachable(
        self,
    ):
        import yaml

        services = yaml.safe_load((ROOT / "compose.yaml").read_text())[
            "services"
        ]
        for name in (
            "loki-bucket-init",
            "profile-image-bucket-init",
            "postgres-monitor-role-init",
        ):
            self.assertEqual(services[name]["entrypoint"], ["/bin/sh", "-ec"])
            self.assertIsInstance(services[name]["command"], list)
            self.assertEqual(len(services[name]["command"]), 1)
        migrations = services["migrations"]
        self.assertIn("./db/migrations:/migrations:ro", migrations["volumes"])
        self.assertTrue(
            (ROOT / "db/migrations/core/001_core_baseline.sql").is_file()
        )
        self.assertTrue((ROOT / "db/migrations/run.sh").is_file())

    def test_postgres_monitor_role_job_does_not_block_fresh_install(self):
        template = (
            ROOT / "helm/myota/templates/observability.yaml"
        ).read_text()
        start = template.index('"postgres-monitor-role"')
        end = template.index("---", start)
        role_job = template[start:end]
        self.assertNotIn('"helm.sh/hook"', role_job)
        self.assertIn("activeDeadlineSeconds: 900", role_job)

    def test_prometheus_uses_collector_boundary(self):
        config = (ROOT / "observability" / "prometheus.yml").read_text()
        self.assertIn("otel-collector:8889", config)
        self.assertNotIn("identity:8001", config)
        self.assertNotIn("geodata:8003", config)

    def test_collector_has_otlp_and_prometheus_pipelines(self):
        config = (ROOT / "observability" / "otel-collector.yaml").read_text()
        self.assertIn("otlp:", config)
        self.assertIn("prometheus:", config)
        self.assertIn("otlp/tempo", config)
        self.assertIn("endpoint: 0.0.0.0:8889", config)

    def test_dashboard_is_real_data_only(self):
        dashboard = json.loads(
            (
                ROOT
                / "observability"
                / "grafana"
                / "dashboards"
                / "myota-service-health.json"
            ).read_text()
        )
        expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]
        self.assertTrue(
            any(
                "myota_identity_users{" in expression
                for expression in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_geodata_entities_total" in expression
                for expression in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_activity_qsos_total" in expression
                for expression in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_http_server_requests_total" in expression
                for expression in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_programmes{" in expression for expression in expressions
            )
        )
        self.assertFalse(
            any(
                "myota_identity_users_total" in expression
                or "myota_programmes_total" in expression
                for expression in expressions
            )
        )
        self.assertFalse(
            any(
                "vector(1)" in expression or "count(up)" in expression
                for expression in expressions
            )
        )

    def test_trace_dashboard_uses_supported_bounded_tempo_searches(self):
        dashboard = json.loads(
            (
                ROOT
                / "observability"
                / "grafana"
                / "dashboards"
                / "myota-traces.json"
            ).read_text()
        )
        self.assertEqual(dashboard["uid"], "myota-traces")
        self.assertEqual(dashboard["time"], {"from": "now-30m", "to": "now"})
        self.assertEqual(dashboard["refresh"], "30s")
        self.assertEqual(dashboard["timezone"], "utc")
        queries = [
            target
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]
        self.assertEqual(len(queries), 2)
        self.assertTrue(
            all(
                query.get("datasource", {}).get("uid") == "myota-tempo"
                and query.get("queryType") == "traceql"
                and query.get("tableType") == "traces"
                and query.get("limit") == 50
                for query in queries
            )
        )
        query_text = "\n".join(query["query"] for query in queries)
        self.assertIn("span:status = error", query_text)
        self.assertIn("trace:duration > 1s", query_text)
        self.assertIn('resource.service.namespace = "myota"', query_text)
        self.assertTrue(all("metricsQuery" not in query for query in queries))
        service_filter = dashboard["templating"]["list"][0]
        service_names = [
            option["value"] for option in service_filter["options"]
        ]
        self.assertEqual(service_filter["name"], "service")
        self.assertEqual(service_filter["type"], "custom")
        self.assertTrue(service_filter["includeAll"])
        self.assertEqual(service_filter["allValue"], ".*")
        self.assertEqual(service_names, sorted(set(service_names)))
        self.assertTrue(
            all(name.startswith("myota-") for name in service_names)
        )
        self.assertEqual(service_filter["query"], ",".join(service_names))
        helm_template = (
            ROOT / "helm/myota/templates/observability.yaml"
        ).read_text()
        self.assertIn("myota-traces.json", helm_template)
        self.assertIn(
            "/etc/grafana/dashboards/myota-traces.json", helm_template
        )
        datasources = (
            ROOT
            / "observability/grafana/provisioning/datasources/datasources.yml"
        ).read_text()
        self.assertIn("uid: myota-tempo", datasources)
        self.assertIn("datasourceUid: myota-loki", datasources)

    def test_log_to_trace_macro_survives_provisioning_environment_expansion(
        self,
    ):
        for prefix in ("observability", "helm/myota/observability"):
            config = (
                ROOT
                / prefix
                / "grafana/provisioning/datasources/datasources.yml"
            ).read_text()
            self.assertIn("url: '$${__value.raw}'", config)
            self.assertNotIn("url: '${__value.raw}'", config)

    def test_logs_dashboard_uses_bounded_filters_and_privacy_safe_queries(
        self,
    ):
        dashboard = json.loads(
            (
                ROOT
                / "observability"
                / "grafana"
                / "dashboards"
                / "myota-logs-failures.json"
            ).read_text()
        )
        variables = dashboard["templating"]["list"]
        self.assertEqual(
            [variable["name"] for variable in variables],
            ["environment", "service", "severity"],
        )
        for variable in variables:
            options = [option["value"] for option in variable["options"]]
            self.assertEqual(variable["type"], "custom")
            self.assertTrue(variable["includeAll"])
            self.assertEqual(variable["allValue"], ".*")
            self.assertEqual(len(options), len(set(options)))
            self.assertEqual(variable["query"], ",".join(options))
        self.assertEqual(
            [option["value"] for option in variables[0]["options"]],
            ["development", "test", "testing", "production"],
        )
        self.assertTrue(
            all(
                option["value"].startswith("myota-")
                for option in variables[1]["options"]
            )
        )
        expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]
        dashboard_json = json.dumps(dashboard)
        self.assertNotIn("correlation_id", dashboard_json)
        self.assertNotIn("component", dashboard_json)
        self.assertTrue(
            all("${component" not in expression for expression in expressions)
        )
        self.assertTrue(
            all(
                "${correlation_id" not in expression
                for expression in expressions
            )
        )
        self.assertIn(
            'severity_text=~"WARN|WARNING|ERROR"', "\n".join(expressions)
        )
        # Application namespace is a fixed telemetry resource attribute, not
        # the Kubernetes release namespace. Substitution hid Test failures.
        helm_logs = (
            ROOT
            / "helm/myota/observability/grafana/dashboards/myota-logs-failures.json"
        ).read_text()
        self.assertNotIn("{{MYOTA_NAMESPACE}}", helm_logs)
        for expression in expressions:
            if (
                expression.startswith("{")
                or "rate({" in expression
                or "count_over_time({" in expression
            ):
                self.assertIn('service_namespace="myota"', expression)
        warnings = next(
            panel for panel in dashboard["panels"] if panel["id"] == 2
        )
        self.assertIn("sum by (severity_text)", warnings["targets"][0]["expr"])
        errors_panel = next(
            panel for panel in dashboard["panels"] if panel["id"] == 3
        )
        self.assertEqual(errors_panel["title"], "Errors by service")
        self.assertIn(
            "sum by (service_name)",
            errors_panel["targets"][0]["expr"],
        )

    def test_seaweed_dashboard_is_valid_and_rolls_out_with_helm(self):
        dashboard_path = (
            ROOT
            / "observability"
            / "grafana"
            / "dashboards"
            / "myota-object-storage.json"
        )
        chart_dashboard_path = (
            ROOT
            / "helm"
            / "myota"
            / "observability"
            / "grafana"
            / "dashboards"
            / "myota-object-storage.json"
        )
        dashboard = json.loads(dashboard_path.read_text())
        chart_dashboard = json.loads(chart_dashboard_path.read_text())
        deployment_template = (
            ROOT / "helm" / "myota" / "templates" / "observability.yaml"
        ).read_text()

        self.assertEqual(dashboard, chart_dashboard)
        self.assertEqual("myota-object-storage", dashboard["uid"])
        self.assertGreater(len(dashboard["panels"]), 0)
        self.assertIn("checksum/grafana-config:", deployment_template)
        self.assertIn(
            '.Files.Glob "observability/grafana/**"', deployment_template
        )

    def test_loki_uses_s3_retention_and_native_otlp_pipeline(self):
        compose_config = (ROOT / "observability" / "loki.yaml").read_text()
        helm_config = (ROOT / "helm/myota/observability/loki.yaml").read_text()
        compose_collector = (
            ROOT / "observability" / "otel-collector.yaml"
        ).read_text()
        helm_collector = (
            ROOT / "helm/myota/observability/otel-collector.yaml"
        ).read_text()
        helm_template = (
            ROOT / "helm/myota/templates/observability.yaml"
        ).read_text()
        compose = (ROOT / "compose.yaml").read_text()

        for config in (compose_config, helm_config):
            self.assertIn("store: tsdb", config)
            self.assertIn("object_store: s3", config)
            self.assertIn("retention_enabled: true", config)
            self.assertIn("delete_request_store: s3", config)
            self.assertIn("ignore_defaults: true", config)
            self.assertIn("service.namespace", config)
        self.assertIn("bucketnames: myota-loki", compose_config)
        self.assertIn(".Values.observability.loki.bucketName", helm_config)
        self.assertIn("retention_period: 336h", compose_config)
        self.assertIn(
            ".Values.observability.loki.retentionPeriod", helm_config
        )
        self.assertIn("endpoint: http://loki:3100/otlp", compose_collector)
        self.assertIn("endpoint: http://myota-loki:3100/otlp", helm_collector)
        self.assertIn("exporters: [otlphttp/loki]", helm_collector)
        self.assertIn("loki-data", helm_template)
        self.assertIn("workingStorageSize", helm_template)
        self.assertIn("loki-bucket-init", compose)
        self.assertIn("  loki:", compose)
        self.assertIn("loki-data:", compose)

    def test_k3s_dashboard_and_scrapes_are_internal_and_least_privilege(self):
        dashboard = json.loads(
            (
                ROOT
                / "helm/myota/observability/grafana/dashboards"
                / "myota-k3s-workload.json"
            ).read_text()
        )
        helm_template = (
            ROOT / "helm/myota/templates/observability.yaml"
        ).read_text()
        prom_config = (
            ROOT / "helm/myota/observability/prometheus.yml"
        ).read_text()
        dashboard_provider = (
            ROOT
            / "helm/myota/observability/grafana/provisioning"
            / "dashboards/dashboards.yml"
        ).read_text()

        self.assertEqual(dashboard["time"], {"from": "now-30m", "to": "now"})
        self.assertEqual(dashboard["refresh"], "30s")
        self.assertEqual(dashboard["timezone"], "utc")
        self.assertIn(
            "kube_deployment_status_replicas_available", json.dumps(dashboard)
        )
        self.assertIn(
            "kube_pod_container_status_restarts_total", json.dumps(dashboard)
        )
        self.assertIn("pod_cpu_usage_seconds_total", json.dumps(dashboard))
        self.assertIn(
            "kubelet_volume_stats_available_bytes", json.dumps(dashboard)
        )
        self.assertIn("kube-state-metrics", prom_config)
        self.assertIn("scrape_interval: 30s", prom_config)
        self.assertNotIn("source_labels: [__name__]", prom_config)
        self.assertIn("serviceAccountName: myota-prometheus", helm_template)
        self.assertNotIn("kind: ClusterRole", helm_template)
        self.assertNotIn("nodes/proxy", helm_template)
        self.assertNotIn("insecure_skip_verify", prom_config)
        self.assertIn(
            'regex: "(pod_cpu_usage_seconds_total|pod_memory_working_set_bytes);{{ .Release.Namespace }}"',
            prom_config,
        )
        self.assertIn(
            'regex: "(kubelet_volume_stats_available_bytes|kubelet_volume_stats_capacity_bytes);{{ .Release.Namespace }}"',
            prom_config,
        )
        self.assertIn("folder: K3s", dashboard_provider)
        self.assertIn("myota-k3s-workload.json", helm_template)

    def test_workflow_dashboard_is_chart_provisioned_and_root_mirror_matches(
        self,
    ):
        dashboard = json.loads(
            (
                ROOT
                / "observability/grafana/dashboards"
                / "myota-application-workflows.json"
            ).read_text()
        )
        chart_dashboard = json.loads(
            (
                ROOT
                / "helm/myota/observability/grafana/dashboards"
                / "myota-application-workflows.json"
            ).read_text()
        )
        self.assertEqual(dashboard, chart_dashboard)
        expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]
        self.assertTrue(
            any("myota_outbox_pending_events" in e for e in expressions)
        )
        self.assertTrue(
            any("myota_activity_jobs_total" in e for e in expressions)
        )
        self.assertTrue(
            any("myota_geodata_import_queue_depth" in e for e in expressions)
        )
        self.assertTrue(
            any(
                "nats_core_account_jetstream_consumer_count" in e
                for e in expressions
            )
        )
        self.assertFalse(
            any("myota_jetstream_consumer_pending" in e for e in expressions)
        )

    def test_postgresql_dashboard_uses_current_bounded_metrics(self):
        dashboard = json.loads(
            (
                ROOT
                / "observability/grafana/dashboards"
                / "myota-postgresql-postgis.json"
            ).read_text()
        )
        self.assertEqual(dashboard["time"], {"from": "now-30m", "to": "now"})
        expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]
        self.assertTrue(any("postgresql_backends" in e for e in expressions))
        self.assertTrue(
            any("postgresql_connection_max" in e for e in expressions)
        )
        self.assertTrue(
            any(
                "myota_geodata_postgres_pool_waiting_requests" in e
                for e in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_geodata_postgres_lock_waiting_connections" in e
                for e in expressions
            )
        )
        self.assertFalse(any("myota_postgresql_" in e for e in expressions))
        config = (ROOT / "observability" / "otel-collector.yaml").read_text()
        for database in ("core", "activity", "geo"):
            self.assertIn(f"postgresql/{database}:", config)
        receivers = config.split("  prometheus:", 1)[0]
        self.assertEqual(receivers.count("tls: {insecure: true}"), 3)
        self.assertIn("collection_interval: 30s", config)
        self.assertIn("db.server.query_sample: {enabled: false}", config)
        self.assertIn("db.server.top_query: {enabled: false}", config)
        self.assertNotIn("operations:8005", config)

    def test_operations_runtime_and_schema_are_retired(self):
        compose = (ROOT / "compose.yaml").read_text()
        chart_values = (ROOT / "helm/myota/values.yaml").read_text()
        chart_deployment = (
            ROOT / "helm/myota/templates/deployment.yaml"
        ).read_text()
        collector = (ROOT / "observability/otel-collector.yaml").read_text()
        self.assertNotIn("myota-operations", compose)
        self.assertNotIn("myota-operations", chart_values)
        self.assertNotIn("myota-operations", chart_deployment)
        self.assertNotIn("operations:8005", collector)
        core_baseline = (
            ROOT / "db/migrations/core/001_core_baseline.sql"
        ).read_text()
        self.assertNotIn("operations_jetstream_snapshot", core_baseline)
        self.assertNotIn("operations_storage_snapshot", core_baseline)


if __name__ == "__main__":
    unittest.main()
