"""Missing issuer completion must never turn an unknown root into trusted input."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "download_ca", ROOT / "scripts/build_download_ca_bundle.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_reviewed_issuer_chains_to_existing_roots(tmp_path):
    output = module.build(tmp_path / "bundle.pem", ROOT / "deploy/tls-intermediates")
    assert output.read_text().count("BEGIN CERTIFICATE") > 100


def test_nested_reviewed_chain_can_complete_existing_root(tmp_path):
    issuers = tmp_path / "issuers"
    issuers.mkdir()
    source = ROOT / "deploy/tls-intermediates"
    (issuers / "ye1.pem").write_text((source / "letsencrypt-ye1.pem").read_text())
    output = tmp_path / "bundle.pem"
    (issuers / "ye.pem").write_text((source / "letsencrypt-root-ye-cross-signed.pem").read_text())
    assert module.build(output, issuers) == output.resolve()


def test_untrusted_root_rejected_without_replacing_existing_bundle(tmp_path):
    issuers = tmp_path / "issuers"
    issuers.mkdir()
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-nodes",
            "-subj",
            "/CN=Untrusted test root",
            "-days",
            "1",
            "-keyout",
            str(tmp_path / "key.pem"),
            "-out",
            str(issuers / "unknown.pem"),
        ],
        check=True,
        capture_output=True,
    )
    output = tmp_path / "bundle.pem"
    output.write_text("existing")
    with pytest.raises(subprocess.CalledProcessError):
        module.build(output, issuers)
    assert output.read_text() == "existing"
