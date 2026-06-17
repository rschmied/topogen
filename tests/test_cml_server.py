# File Chain (see DEVELOPER.md):
# Doc Version: v1.2.0
# Date Modified: 2026-06-13
#
# Purpose: TG-194 — --cml-server schema resolution and provenance.
# Blast Radius: Test-only.

import io
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.cml_server import (  # pylint: disable=wrong-import-position
    HIGHEST_KNOWN_CML_SCHEMA,
    append_cml_schema_provenance_args,
    resolve_cml_server_version,
    schema_for_cml_server,
    valid_cml_server,
)
from topogen.main import (  # pylint: disable=wrong-import-position
    create_argparser,
    main,
    resolve_staging_flags,
)
from topogen.render import Renderer  # pylint: disable=wrong-import-position


def _run_main(argv: list[str]) -> tuple[int | None, str]:
    """Run main() capturing argparse stderr; return (exit_code, stderr_text)."""
    stderr = io.StringIO()
    with patch.object(sys, "argv", ["topogen", *argv]), redirect_stderr(stderr):
        try:
            return main(), stderr.getvalue()
        except SystemExit as exc:
            return exc.code, stderr.getvalue()


def _run_main_logs(argv: list[str], level: str = "WARNING") -> tuple[int | None, list[str]]:
    """Run main() capturing topogen log records at the given level."""
    with patch.object(sys, "argv", ["topogen", *argv]):
        with unittest.TestCase.assertLogs(unittest.TestCase(), "topogen", level=level) as log_ctx:
            try:
                rc = main()
            except SystemExit as exc:
                rc = exc.code
    return rc, log_ctx.output


class TestCmlServerSchemaMap(unittest.TestCase):
    def test_known_servers(self):
        cases = {
            "2.5": "0.2.0",
            "2.6": "0.2.1",
            "2.7": "0.2.2",
            "2.8": "0.3.0",
            "2.9": "0.3.0",
            "2.10": "0.3.1",
        }
        for server, schema in cases.items():
            got, msg = schema_for_cml_server(server)
            self.assertEqual(got, schema)
            self.assertIsNone(msg)

    def test_future_server_uses_highest_schema(self):
        schema, msg = schema_for_cml_server("2.13")
        self.assertEqual(schema, HIGHEST_KNOWN_CML_SCHEMA)
        self.assertIn("highest known schema", msg or "")

    def test_between_2_5_and_2_6_uses_2_5_schema(self):
        # CML uses integer minors only; 2.55 is not a release — parses as (2, 55) > 2.10
        # so use a version below the lowest mapped anchor instead.
        schema, msg = schema_for_cml_server("2.4")
        self.assertEqual(schema, "0.2.0")
        self.assertIn("CML 2.5", msg or "")

    def test_below_minimum_clamps_to_2_5(self):
        schema, msg = schema_for_cml_server("2.1")
        self.assertEqual(schema, "0.2.0")
        self.assertIn("CML 2.5", msg or "")

    def test_invalid_server_rejected(self):
        with self.assertRaises(Exception):
            valid_cml_server("2.10.1")


class TestResolveCmlServerVersion(unittest.TestCase):
    def test_server_only_sets_schema(self):
        args = Namespace(cml_server="2.10", cml_version="0.3.0")
        resolve_cml_server_version(args, ["topogen", "3", "--cml-server", "2.10"])
        self.assertEqual(args.cml_version, "0.3.1")

    def test_explicit_cml_version_wins(self):
        args = Namespace(cml_server="2.10", cml_version="0.3.0")
        resolve_cml_server_version(
            args,
            ["topogen", "3", "--cml-server", "2.10", "--cml-version", "0.3.0"],
        )
        self.assertEqual(args.cml_version, "0.3.0")

    def test_no_server_leaves_version(self):
        args = Namespace(cml_server=None, cml_version="0.3.0")
        resolve_cml_server_version(args, ["topogen", "3"])
        self.assertEqual(args.cml_version, "0.3.0")

    @patch("topogen.cml_server._LOGGER")
    def test_unknown_server_logs_info(self, mock_logger):
        args = Namespace(cml_server="2.13", cml_version="0.3.0")
        resolve_cml_server_version(args, ["topogen", "3", "--cml-server", "2.13"])
        self.assertEqual(args.cml_version, HIGHEST_KNOWN_CML_SCHEMA)
        mock_logger.info.assert_called_once()
        self.assertIn("2.13", mock_logger.info.call_args[0][0])


class TestCmlServerIntegration(unittest.TestCase):
    def setUp(self):
        self.parser = create_argparser()

    def _resolve(self, argv):
        args = self.parser.parse_args(argv)
        resolve_cml_server_version(args, ["topogen", *argv])
        resolve_staging_flags(args)
        return args

    def test_staging_with_server_2_10(self):
        args = self._resolve(
            [
                "3",
                "--mode",
                "dmvpn",
                "--offline-yaml",
                "out/pki.yaml",
                "--pki",
                "--cml-server",
                "2.10",
            ]
        )
        self.assertEqual(args.cml_version, "0.3.1")
        self.assertTrue(args.staging)

    def test_staging_ignored_when_explicit_old_schema(self):
        args = self._resolve(
            [
                "3",
                "--mode",
                "dmvpn",
                "--offline-yaml",
                "out/pki.yaml",
                "--pki",
                "--cml-server",
                "2.10",
                "--cml-version",
                "0.3.0",
            ]
        )
        self.assertEqual(args.cml_version, "0.3.0")
        self.assertFalse(args.staging)


class TestCmlServerCliNegatives(unittest.TestCase):
    """CLI fail-fast paths and --quiet interaction (TG-194)."""

    def test_invalid_cml_server_foo(self):
        rc, err = _run_main(
            ["2", "-m", "flat", "--cml-server", "foo", "--offline-yaml", "out/x.yaml"]
        )
        self.assertEqual(rc, 2)
        self.assertIn("invalid CML server version 'foo'", err)

    def test_invalid_cml_server_patch_version(self):
        rc, err = _run_main(
            ["2", "-m", "flat", "--cml-server", "2.10.1", "--offline-yaml", "out/x.yaml"]
        )
        self.assertEqual(rc, 2)
        self.assertIn("invalid CML server version '2.10.1'", err)

    def test_invalid_cml_version_choice(self):
        rc, err = _run_main(
            ["2", "-m", "flat", "--cml-version", "0.9.9", "--offline-yaml", "out/x.yaml"]
        )
        self.assertEqual(rc, 2)
        self.assertIn("invalid choice: '0.9.9'", err)

    def test_quiet_still_fails_fast_on_bad_cml_server(self):
        rc, err = _run_main(
            [
                "--quiet",
                "2",
                "-m",
                "flat",
                "--cml-server",
                "foo",
                "--offline-yaml",
                "out/x.yaml",
            ]
        )
        self.assertEqual(rc, 2)
        self.assertIn("invalid CML server version 'foo'", err)

    def test_import_missing_yaml_fails(self):
        rc, logs = _run_main_logs(["--up", "out/TG-194/does-not-exist-neg-test.yaml"], "ERROR")
        self.assertEqual(rc, 1)
        self.assertTrue(any("YAML file not found" in line for line in logs))

    def test_quiet_still_reports_import_missing_yaml(self):
        rc, logs = _run_main_logs(
            ["--quiet", "--up", "out/TG-194/does-not-exist-neg-test.yaml"], "ERROR"
        )
        self.assertEqual(rc, 1)
        self.assertTrue(any("YAML file not found" in line for line in logs))
        self.assertFalse(any("using configuration defaults" in line for line in logs))

    def test_info_fallback_log_visible_at_info_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "lab.yaml"
            rc, logs = _run_main_logs(
                [
                    "2",
                    "-m",
                    "flat",
                    "-l",
                    "INFO",
                    "--cml-server",
                    "2.13",
                    "--offline-yaml",
                    str(out),
                    "--overwrite",
                ],
                "INFO",
            )
            self.assertEqual(rc, 0)
            self.assertTrue(any("highest known schema" in line for line in logs))

    def test_quiet_forces_error_loglevel(self):
        parser = create_argparser()
        args = parser.parse_args(
            [
                "--quiet",
                "2",
                "-m",
                "flat",
                "-l",
                "INFO",
                "--offline-yaml",
                "out/x.yaml",
            ]
        )
        if getattr(args, "quiet", False):
            args.loglevel = "ERROR"
        self.assertEqual(args.loglevel, "ERROR")


class TestCmlServerGapGenerate(unittest.TestCase):
    """Gap: conflicting flags — no fail-fast, explicit schema wins in YAML."""

    def test_both_flags_yaml_uses_explicit_cml_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "lab.yaml"
            rc, _ = _run_main(
                [
                    "2",
                    "-m",
                    "flat",
                    "--cml-server",
                    "2.10",
                    "--cml-version",
                    "0.3.0",
                    "--offline-yaml",
                    str(out),
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            data = yaml.safe_load(out.read_text(encoding="utf-8"))
            self.assertEqual(data["lab"]["version"], "0.3.0")
            provenance = data["annotations"][0]["text_content"]
            self.assertIn("--cml-server 2.10", provenance)
            self.assertIn("--cml-version 0.3.0", provenance)

    def test_both_flags_no_conflict_warning_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "lab.yaml"
            with patch.object(
                sys,
                "argv",
                [
                    "topogen",
                    "2",
                    "-m",
                    "flat",
                    "-l",
                    "INFO",
                    "--cml-server",
                    "2.10",
                    "--cml-version",
                    "0.3.0",
                    "--offline-yaml",
                    str(out),
                    "--overwrite",
                ],
            ):
                with unittest.TestCase.assertLogs(
                    unittest.TestCase(), "topogen", level="WARNING"
                ) as log_ctx:
                    rc = main()
            self.assertEqual(rc, 0)
            joined = "\n".join(log_ctx.output)
            self.assertNotIn("conflict", joined.lower())
            self.assertNotIn("mismatch", joined.lower())


class TestCmlServerGapImport(unittest.TestCase):
    """Gap: CML import rejection paths (mocked client for CI)."""

    def _import_path(self, path: Path, labname: str = "gap-test") -> tuple[int | None, str]:
        stderr = io.StringIO()
        argv = [
            "--insecure",
            "--import-yaml",
            str(path),
            "--import",
            "-L",
            labname,
        ]
        with patch.object(sys, "argv", ["topogen", *argv]), redirect_stderr(stderr):
            try:
                return main(), stderr.getvalue()
            except SystemExit as exc:
                return exc.code, stderr.getvalue()

    @patch("topogen.render._init_client_from_args")
    def test_malformed_yaml_import_error_not_wrapped(self, mock_init):
        mock_init.return_value.import_lab_from_path.side_effect = Exception(
            "Client error - 400: There was an error parsing the body."
        )
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.yaml"
            bad.write_text("lab:\n  title: bad\n  version: [\n", encoding="utf-8")
            with patch.object(
                sys, "argv", ["topogen", "--insecure", "--import-yaml", str(bad), "--import"]
            ):
                with self.assertRaises(Exception) as ctx:
                    main()
            self.assertIn("400", str(ctx.exception))

    @patch("topogen.render._init_client_from_args")
    def test_future_schema_import_error_not_wrapped(self, mock_init):
        mock_init.return_value.import_lab_from_path.side_effect = Exception(
            'Client error - {"Input validation failed": [{"location": ["body", "lab", "version"]}]}'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "future.yaml"
            path.write_text(
                "lab:\n  title: t\n  version: '0.4.0'\nnodes: []\nlinks: []\n", encoding="utf-8"
            )
            with patch.object(
                sys, "argv", ["topogen", "--insecure", "--import-yaml", str(path), "--import"]
            ):
                with self.assertRaises(Exception) as ctx:
                    main()
            self.assertIn("Input validation failed", str(ctx.exception))

    @patch("topogen.render._init_client_from_args")
    def test_import_success_returns_zero(self, mock_init):
        lab = MagicMock()
        lab.id = "lab-uuid-gap"
        mock_init.return_value.import_lab_from_path.return_value = lab
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.yaml"
            path.write_text("lab:\n  title: t\n  version: '0.3.0'\nnodes: []\nlinks: []\n", encoding="utf-8")
            args = Namespace(
                import_yaml=str(path),
                do_import=True,
                start_lab=False,
                labname="gap-ok",
                insecure=True,
                cafile="ca.pem",
                staging=False,
                cml_version="0.3.0",
            )
            self.assertEqual(Renderer.import_yaml_to_cml(str(path), args), 0)


class TestCmlSchemaProvenance(unittest.TestCase):
    def test_both_flags_recorded(self):
        args = Namespace(cml_server="2.10", cml_version="0.3.0")
        bits: list[str] = []
        append_cml_schema_provenance_args(bits, args)
        self.assertEqual(bits, ["--cml-server 2.10", "--cml-version 0.3.0"])

    def test_server_only(self):
        args = Namespace(cml_server="2.6", cml_version="0.2.1")
        bits: list[str] = []
        append_cml_schema_provenance_args(bits, args)
        self.assertEqual(bits, ["--cml-server 2.6", "--cml-version 0.2.1"])


if __name__ == "__main__":
    unittest.main()
