"""The client certificate the appliances accept.

Samsung appliances authorise a DTLS client by the UUID in its certificate
subject, matched against the access control list set at the factory, and do not
validate the signer. A self-signed certificate carrying the UUID that list
grants full access to is therefore enough, and it is minted at startup instead
of being stored.
"""

import datetime
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# The subject UUID the factory ACL of Samsung appliances grants every permission.
CLIENT_UUID = "ab0b0ac4-aae9-4958-a04d-8ec36fe1b2f9"

VALIDITY = datetime.timedelta(days=3650)


@dataclass(frozen=True)
class ClientCertificate:
    """A PEM encoded certificate and its private key"""

    certificate_pem: str
    private_key_pem: str


def mint_client_certificate(uuid: str = CLIENT_UUID) -> ClientCertificate:
    """Create a self-signed client certificate carrying `uuid`"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, f"uuid:{uuid}"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"urn:uuid:{uuid}"),
        ]
    )
    now = datetime.datetime.now(datetime.timezone.utc)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        # Tolerates an appliance clock running behind this host's.
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.UniformResourceIdentifier(f"urn:uuid:{uuid}"),
                    x509.UniformResourceIdentifier(f"uri:uuid:{uuid}"),
                    x509.UniformResourceIdentifier(f"uuid:{uuid}"),
                    x509.DNSName(uuid),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    return ClientCertificate(
        certificate_pem=certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        private_key_pem=key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode("ascii"),
    )
