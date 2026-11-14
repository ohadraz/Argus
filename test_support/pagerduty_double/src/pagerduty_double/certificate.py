"""The certificate the double answers TLS with, minted when it starts.

TLS at all because the client insists on it: PagerDuty's SDK refuses any base
URL that is not `https://`, and the whole point of the double is that the code
reading it is the code that would read the real thing - so the double answers
the scheme the client demands rather than the client being talked out of it.

Self-signed and thrown away, because it is a credential for `localhost` in a
suite and there is nothing about it worth keeping between runs. Whatever reads
the double is told not to verify it.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import tempfile
from pathlib import Path
from typing import Final

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# How long the certificate is good for. Long enough that a stack held open for
# a demo does not expire mid-sentence, short enough that it is obviously not
# meant to be kept.
_CERTIFICATE_DAYS: Final = 30

_LOCALHOST: Final = "localhost"
_LOOPBACK: Final = "127.0.0.1"


def a_self_signed_certificate() -> tuple[Path, Path]:
    """A fresh certificate for `localhost` and its key, written where this process can read them.

    Minted rather than committed: a private key in a repository is a private
    key in a repository, whatever it is for, and this one is worth nothing to
    anybody who has it. Named for both `localhost` and the loopback address,
    because a client may reach the double by either.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _LOCALHOST)])
    now = dt.datetime.now(dt.UTC)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=_CERTIFICATE_DAYS))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(_LOCALHOST),
                x509.IPAddress(ipaddress.ip_address(_LOOPBACK))
            ]),
            critical=False
        )
        .sign(key, hashes.SHA256())
    )

    written_to = Path(tempfile.mkdtemp(prefix="pagerduty-double-tls-"))
    certificate_file = written_to / "certificate.pem"
    key_file = written_to / "key.pem"

    certificate_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )
    )

    return certificate_file, key_file
