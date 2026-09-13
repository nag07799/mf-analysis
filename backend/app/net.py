"""Shared TLS setup for every outbound request to an official source.

Certificate verification stays on.  Two local realities force the adjustments
made here.  A TLS-inspecting endpoint agent (Avast Web/Mail Shield on this PC)
re-signs every chain with a root that exists only in the Windows certificate
store, so certifi alone can never build a path; and that root omits the critical
flag on its basic constraints, which Python 3.13+ rejects because it enables
VERIFY_X509_STRICT by default.  The bundle below is therefore certifi plus the
machine's own trusted roots, and only the strict *structural* flag is cleared.
Signature, expiry and hostname checks are untouched.
"""
from pathlib import Path
import os
import ssl

import certifi
import httpx

SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"
USER_AGENT = "Mozilla/5.0 (compatible; LocalFactsheetArchive/1.0)"
_BUNDLE: Path | None = None


def _trusted_for_server_auth(trust) -> bool:
    # enum_certificates reports True for "all purposes" or a frozenset of OIDs.
    if trust is True:
        return True
    return not isinstance(trust, str) and hasattr(trust, "__contains__") and SERVER_AUTH_OID in trust


def ca_bundle() -> str:
    """certifi plus the Windows trust store, written once per process."""
    global _BUNDLE
    configured = os.getenv("SSL_CERT_FILE")
    if configured and Path(configured).exists():
        return configured
    if _BUNDLE and _BUNDLE.exists():
        return str(_BUNDLE)
    from app.config import settings

    chunks = [Path(certifi.where()).read_text(encoding="utf-8")]
    if hasattr(ssl, "enum_certificates"):
        for store in ("ROOT", "CA"):
            try:
                entries = ssl.enum_certificates(store)
            except (OSError, ValueError):
                continue
            for der, encoding, trust in entries:
                if encoding == "x509_asn" and _trusted_for_server_auth(trust):
                    chunks.append(ssl.DER_cert_to_PEM_cert(der))
    target = settings.archive_root() / "ca-bundle.pem"
    target.write_text("\n".join(chunks), encoding="utf-8")
    _BUNDLE = target
    return str(target)


def ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=ca_bundle())
    # Only the structural strictness added in Python 3.13 is relaxed; an
    # interception root is otherwise well-formed enough to chain correctly.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def client(timeout=90, follow_redirects=False, headers=None) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=follow_redirects,
                        headers={"User-Agent": USER_AGENT, **(headers or {})},
                        verify=ssl_context())
