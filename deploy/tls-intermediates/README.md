# Missing TLS issuer certificates

Some commune web servers send their certificate without the intermediate certificates that link it
to a trusted root, so a client that does not fetch missing issuers itself rejects the connection.
This directory holds those public intermediates, one PEM certificate per file:

1. `digicert-global-g2-tls-rsa-sha256-2020-ca1.pem`: DigiCert Global G2 TLS RSA SHA256 2020 CA1,
   from https://cacerts.digicert.com/DigiCertGlobalG2TLSRSASHA2562020CA1-1.crt.
2. `letsencrypt-ye1.pem`, `letsencrypt-ye2.pem`: Let's Encrypt YE1 and YE2, from
   http://ye1.i.lencr.org/ and http://ye2.i.lencr.org/.
3. `letsencrypt-root-ye-cross-signed.pem`: ISRG Root YE, the issuer of YE1 and YE2, cross-signed by
   ISRG Root X2, from http://ye.i.lencr.org/. It is chain material, not a new trust anchor.

Each was taken from the Authority Information Access URL of the certificate it issues and converted
from DER to PEM with OpenSSL. The files contain public certificates only, never private keys.

`deploy/crawl.sh` builds a CA bundle before each pass with `scripts/build_download_ca_bundle.py`:
certifi's Mozilla roots plus these files. Each file must verify with OpenSSL against certifi's roots,
with the other files offered only as untrusted intermediates; a self-signed certificate that is not
already a root fails. The bundle goes to `$DATA_DIR/cache/download-ca-bundle.pem` and reaches HTTPX
through `SSL_CERT_FILE`. If the build fails (an expired or unverifiable issuer), the pass runs with
the normal roots.

This completes chains; it never disables certificate or hostname verification, adds a root, or
changes the system trust store or other services. The crawler does not fetch issuer URLs from
remote sites. To add an issuer, download it from the Authority Information Access URL of the
certificate it issues, convert it to PEM and add it here; the next build verifies it against the
existing roots.
