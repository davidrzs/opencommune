"""Complete the issuer chains some commune sites leave out, without adding new trust roots.

Each supplied issuer must verify against certifi's existing Mozilla roots before
it is included. No network access; the resulting bundle is used by HTTPX via
SSL_CERT_FILE. It completes chains; it never skips verification for a site.
"""

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

import certifi

from opencommune.config import settings


def build(output: Path, directory: Path) -> Path:
    roots = Path(certifi.where())
    certificates = []
    for path in sorted(directory.glob("*.pem")):
        text = path.read_text()
        blocks = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.S)
        if len(blocks) != 1:
            raise ValueError(f"Expected one reviewed issuer certificate: {path}")
        certificates.append(blocks[0])
    if not certificates:
        raise ValueError("No reviewed issuer certificates found")
    # A server can omit multiple intermediate levels. Supply the reviewed chain
    # as untrusted input; only certifi's existing roots can anchor verification.
    with tempfile.TemporaryDirectory() as directory_name:
        chain = Path(directory_name) / "issuers.pem"
        chain.write_text("\n".join(certificates) + "\n")
        for path in sorted(directory.glob("*.pem")):
            subprocess.run(
                [
                    "openssl",
                    "verify",
                    "-CAfile",
                    str(roots),
                    "-no-CApath",
                    "-no-CAstore",
                    "-untrusted",
                    str(chain),
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
    bundle = roots.read_text() + "\n" + "\n".join(certificates) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=output.parent, delete=False) as f:
        f.write(bundle)
        temporary = Path(f.name)
    temporary.replace(output)
    return output.resolve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=settings.data_dir / "cache" / "download-ca-bundle.pem"
    )
    parser.add_argument("--issuers", type=Path, default=Path("deploy/tls-intermediates"))
    args = parser.parse_args()
    print(build(args.output, args.issuers))
