"""The client certificate."""

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from smartthings_local.protocol.auth import CertificateAuth

from smartthings_ws.certificate import CLIENT_UUID, ClientCertificate


def test_certificate_carries_the_uuid(certificate: ClientCertificate) -> None:
    """Test that the subject and the alternative names carry the client UUID"""
    cert = x509.load_pem_x509_certificate(certificate.certificate_pem.encode())
    names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value

    assert cert.subject.rfc4514_string() == f"CN=urn:uuid:{CLIENT_UUID},OU=uuid:{CLIENT_UUID}"
    assert cert.issuer == cert.subject
    assert f"urn:uuid:{CLIENT_UUID}" in names.get_values_for_type(x509.UniformResourceIdentifier)
    assert names.get_values_for_type(x509.DNSName) == [CLIENT_UUID]


def test_certificate_matches_its_key(certificate: ClientCertificate) -> None:
    """Test that the key belongs to the certificate and the library accepts the pair"""
    cert = x509.load_pem_x509_certificate(certificate.certificate_pem.encode())
    key = serialization.load_pem_private_key(certificate.private_key_pem.encode(), password=None)

    assert cert.public_key() == key.public_key()
    CertificateAuth.from_memory(certificate.certificate_pem, certificate.private_key_pem)
