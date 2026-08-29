import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runloop_lab import spec
from runloop_lab.config import LabConfig, load_env_file
from runloop_lab.lab import LabError, RunloopLab
from runloop_lab.state import LabState
from tests.fake_runloop import FakeSDK

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(coroutine):
    return asyncio.run(coroutine)


def quiet_lab(sdk, **config_overrides):
    config = LabConfig(**config_overrides) if config_overrides else LabConfig()
    return RunloopLab(sdk, config, printer=lambda _: None)


class SpecTest(unittest.TestCase):
    def setUp(self):
        self.config = LabConfig()

    def test_network_policy_denies_by_default(self):
        policy = spec.network_policy_spec(self.config)
        self.assertFalse(policy["allow_all"])
        self.assertFalse(policy["allow_devbox_to_devbox"])
        self.assertTrue(policy["allow_runloop_mirrors"])
        self.assertIn("*.docker.io", policy["allowed_hostnames"])
        self.assertIn("deb.debian.org", policy["allowed_hostnames"])

    def test_devbox_params_request_a_tunnel_and_carry_the_policy(self):
        params = spec.devbox_params(self.config, "bp-name", "npol_1")
        self.assertEqual(params["tunnel"]["auth_mode"], "open")
        self.assertEqual(params["blueprint_name"], "bp-name")
        self.assertEqual(
            params["launch_parameters"]["resource_size_request"], "CUSTOM_SIZE"
        )
        self.assertEqual(params["launch_parameters"]["network_policy_id"], "npol_1")
        self.assertEqual(params["metadata"]["project"], "agentdns-sentinel")

    def test_devbox_params_omit_the_blueprint_when_not_requested(self):
        self.assertNotIn("blueprint_name", spec.devbox_params(self.config))

    def test_the_blueprint_warms_the_image_cache(self):
        params = spec.blueprint_params(self.config, dockerfile="FROM x")
        commands = params["system_setup_commands"]
        self.assertTrue(any("docker compose build" in command for command in commands))
        self.assertTrue(all(self.config.workdir in command for command in commands))

    def test_setup_commands_can_be_overridden(self):
        config = LabConfig(setup_commands=("echo hello",))
        params = spec.blueprint_params(config, dockerfile="FROM x")
        self.assertEqual(params["system_setup_commands"], ["echo hello"])

    def test_blueprint_params_carry_the_build_context(self):
        params = spec.blueprint_params(
            self.config, dockerfile="FROM x", build_context={"object_id": "obj_1", "type": "object"}
        )
        self.assertEqual(params["build_context"]["object_id"], "obj_1")
        self.assertEqual(params["dockerfile"], "FROM x")

    def test_commands_are_quoted_and_scoped_to_the_workdir(self):
        command = spec.compose_up_command(self.config, "https://3000-x.tunnel.runloop.ai")
        self.assertTrue(command.startswith("cd /workspace/agentdns-sentinel &&"))
        self.assertIn("REFLEX_API_URL=https://3000-x.tunnel.runloop.ai", command)
        self.assertIn("CONTROL_TOKEN=demo-control-token", command)
        self.assertIn("RESEARCHER_AGENT_TOKEN=demo-researcher-token", command)
        # The blueprint already built the images, so a normal start reuses them.
        self.assertIn("docker compose up -d", command)
        self.assertNotIn("--build", command)
        self.assertIn(
            "docker compose up -d --build",
            spec.compose_up_command(self.config, "https://8000-x.tunnel.runloop.ai", rebuild=True),
        )

    def test_demo_command_passes_the_selected_scenarios(self):
        command = spec.demo_command(self.config, ["failover", "live-policy"], reset=False)
        self.assertIn("run failover live-policy", command)
        self.assertIn("--no-reset", command)
        self.assertIn("--json", command)

    def test_source_filter_drops_local_junk(self):
        for path in [
            ".git/config",
            ".env",
            "dns_manager/__pycache__/a.pyc",
            "artifacts/x.json",
            "data.db",
        ]:
            self.assertTrue(spec.is_excluded(path), path)
        for path in ["demo/runner.py", "config/policies.json", "Dockerfile"]:
            self.assertFalse(spec.is_excluded(path), path)


class EnvironmentFileTest(unittest.TestCase):
    def test_env_file_loads_values_without_overriding_the_shell(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / ".env"
            path.write_text("RUNLOOP_API_KEY=file-key\nCONTROL_TOKEN='file-token'\n")
            with patch.dict(
                "os.environ", {"CONTROL_TOKEN": "shell-token"}, clear=True
            ):
                load_env_file(path)
                self.assertEqual(os.environ["RUNLOOP_API_KEY"], "file-key")
                self.assertEqual(os.environ["CONTROL_TOKEN"], "shell-token")


class NetworkPolicyFlowTest(unittest.TestCase):
    def test_policy_is_created_once_and_then_reused(self):
        sdk = FakeSDK()
        lab = quiet_lab(sdk)
        first = run(lab.ensure_network_policy())
        second = run(lab.ensure_network_policy())
        self.assertEqual(first, second)
        self.assertEqual(sdk.call_names().count("network_policy.create"), 1)


class BlueprintFlowTest(unittest.TestCase):
    def test_blueprint_uses_the_current_storage_object_upload_api(self):
        sdk = FakeSDK()
        lab = quiet_lab(sdk)
        blueprint_id = run(lab.build_blueprint(REPO_ROOT))
        self.assertEqual(blueprint_id, "bpt_1")
        self.assertEqual(
            sdk.call_names(),
            ["storage_object.upload_from_bytes", "blueprint.create"],
        )
        upload = sdk.calls[0][1]
        self.assertEqual(upload["content_type"], "tgz")
        self.assertIsInstance(upload["data"], bytes)

    def test_blueprint_is_created_once_and_then_reused(self):
        sdk = FakeSDK()
        lab = quiet_lab(sdk)
        first = run(lab.ensure_blueprint(REPO_ROOT))
        second = run(lab.ensure_blueprint(REPO_ROOT))
        self.assertEqual(first, second)
        self.assertEqual(sdk.call_names().count("blueprint.create"), 1)


class UpFlowTest(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeSDK()
        self.lab = quiet_lab(self.sdk)

    def test_the_lab_starts_in_the_expected_order(self):
        async def exercise():
            policy_id = await self.lab.ensure_network_policy()
            devbox = await self.lab.create_devbox(self.lab.config.blueprint_name, policy_id)
            urls = await self.lab.tunnel_urls(devbox)
            await self.lab.sync_code(devbox, REPO_ROOT)
            await self.lab.start_lab(devbox, urls["dashboard"])
            return devbox, urls

        devbox, urls = run(exercise())

        self.assertEqual(
            self.sdk.call_names(),
            ["network_policy.create", "devbox.create_from_blueprint_name"],
        )
        self.assertEqual(urls["dashboard"], "https://3000-abc123.tunnel.runloop.ai")
        self.assertEqual(urls["control_api"], "https://8053-abc123.tunnel.runloop.ai")

        self.assertEqual(len(devbox.uploads), 1)
        self.assertEqual(devbox.uploads[0][0], "lab-source.tar.gz")

        extract, compose, wait = devbox.commands
        self.assertIn("tar xzf lab-source.tar.gz", extract)
        self.assertIn(f"REFLEX_API_URL={urls['dashboard']}", compose)
        self.assertIn("LAB_READY", wait)

    def test_a_lab_that_never_answers_is_reported(self):
        async def exercise():
            devbox = await self.lab.create_devbox()
            devbox.never_ready = True
            await self.lab.start_lab(devbox, "https://backend")

        with self.assertRaises(LabError) as context:
            run(exercise())
        self.assertIn("did not become ready", str(context.exception))

    def test_a_devbox_without_a_tunnel_is_reported(self):
        async def exercise():
            devbox = await self.lab.create_devbox()

            async def no_tunnel(_port):
                return None

            devbox.get_tunnel_url = no_tunnel
            await self.lab.tunnel_urls(devbox)

        with self.assertRaises(LabError):
            run(exercise())

    def test_the_uploaded_tarball_excludes_local_junk(self):
        import io
        import tarfile

        payload = self.lab._tarball(REPO_ROOT)
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            names = archive.getnames()
        self.assertIn("demo/runner.py", names)
        self.assertIn("config/policies.json", names)
        self.assertFalse([name for name in names if name.startswith(".git/")])
        self.assertNotIn(".env", names)
        self.assertFalse([name for name in names if "__pycache__" in name])


class DemoFlowTest(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeSDK()
        self.lab = quiet_lab(self.sdk)

    def test_results_survive_docker_noise_on_stdout(self):
        async def exercise():
            devbox = await self.lab.create_devbox()
            return await self.lab.run_demo(devbox, ["all"])

        results = run(exercise())
        self.assertEqual(results[0]["id"], "baseline")

    def test_unparseable_output_raises_a_clear_error(self):
        async def exercise():
            devbox = await self.lab.create_devbox()
            devbox.failures = {}
            devbox.demo_results = None  # produces "null", not a JSON array
            return await self.lab.run_demo(devbox, ["all"])

        with self.assertRaises(LabError) as context:
            run(exercise())
        self.assertIn("Could not parse", str(context.exception))

    def test_evidence_is_written_next_to_the_repo(self):
        async def exercise(out_dir):
            devbox = await self.lab.create_devbox()
            results = await self.lab.run_demo(devbox, ["all"])
            return await self.lab.collect_evidence(devbox, results, out_dir)

        with tempfile.TemporaryDirectory() as tempdir:
            written = run(exercise(Path(tempdir)))
            self.assertEqual(set(written), {"scenarios", "events", "control_events"})
            scenarios = json.loads(written["scenarios"].read_text())
            self.assertEqual(scenarios[0]["verdict"], "PASS")
            self.assertTrue(json.loads(written["events"].read_text()))
            self.assertTrue(json.loads(written["control_events"].read_text()))

    def test_snapshot_and_shutdown(self):
        async def exercise():
            devbox = await self.lab.create_devbox()
            snapshot_id = await self.lab.snapshot(devbox, "checkpoint")
            await self.lab.shutdown(devbox)
            return devbox, snapshot_id

        devbox, snapshot_id = run(exercise())
        self.assertEqual(snapshot_id, "snp_1")
        self.assertEqual(devbox.snapshots[0]["commit_message"], "checkpoint")
        self.assertTrue(devbox.shutdown_called)

    def test_only_this_projects_devboxes_are_listed(self):
        async def exercise():
            await self.lab.create_devbox()
            stray = await self.sdk.devbox.create(name="someone-else", metadata={"project": "other"})
            self.assertTrue(stray.id)
            return await self.lab.list_lab_devboxes()

        listed = run(exercise())
        self.assertEqual(
            [entry["name"] for entry in listed], ["agentdns-sentinel-demo"]
        )

    def test_failed_commands_redact_every_demo_secret(self):
        command = spec.compose_up_command(self.lab.config, "https://backend")
        redacted = self.lab._redact_command(command)
        self.assertIn("<redacted>", redacted)
        for secret in (
            self.lab.config.control_token,
            self.lab.config.service_control_token,
            self.lab.config.researcher_agent_token,
            self.lab.config.deployer_agent_token,
            self.lab.config.untrusted_agent_token,
            self.lab.config.load_tester_agent_token,
            self.lab.config.incident_responder_agent_token,
        ):
            self.assertNotIn(secret, redacted)


class LabStateTest(unittest.TestCase):
    def test_state_round_trips_and_clears(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "lab.json"
            state = LabState(devbox_id="dbx_1", tunnels={"dashboard": "https://x"})
            state.save(path)
            loaded = LabState.load(path)
            self.assertEqual(loaded.devbox_id, "dbx_1")
            self.assertEqual(loaded.require_devbox(), "dbx_1")
            loaded.clear(path)
            self.assertFalse(path.exists())

    def test_corrupt_state_is_ignored_rather_than_fatal(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "lab.json"
            path.write_text("{not json")
            self.assertIsNone(LabState.load(path).devbox_id)

    def test_missing_devbox_explains_the_next_step(self):
        with self.assertRaises(SystemExit) as context:
            LabState().require_devbox()
        self.assertIn("runloop_lab.py up", str(context.exception))


if __name__ == "__main__":
    unittest.main()
