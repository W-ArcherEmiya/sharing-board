import datetime
import ipaddress
import socket
import sys
from pathlib import Path
from typing import List, Union

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtensionOID
from cryptography.x509.oid import NameOID

import launch_config


IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def discover_ip_addresses() -> List[IPAddress]:
    candidates = {
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("::1"),
    }

    for candidate in launch_config.windows_ip_candidates():
        parsed = launch_config.parse_ipv4(candidate.get("ip", ""))
        if parsed and launch_config.is_usable_ipv4(parsed):
            candidates.add(parsed)

    hostname = socket.gethostname()
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            candidates.add(ipaddress.ip_address(sockaddr[0]))
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            candidates.add(ipaddress.ip_address(sock.getsockname()[0]))
    except OSError:
        pass

    return sorted(candidates, key=lambda item: (item.version, str(item)))


def certificate_covers_host(host: str, cert_path: str = "cert.pem") -> bool:
    path = Path(cert_path)
    if not path.exists():
        return False

    try:
        cert = x509.load_pem_x509_certificate(path.read_bytes())
        if cert.not_valid_after_utc <= datetime.datetime.now(datetime.timezone.utc):
            return False
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    except Exception:
        return False

    host = host.strip()
    if not host:
        return False

    try:
        parsed_ip = ipaddress.ip_address(host)
    except ValueError:
        return host in san.get_values_for_type(x509.DNSName)

    return parsed_ip in san.get_values_for_type(x509.IPAddress)


def build_subject_alt_names() -> x509.SubjectAlternativeName:
    hostname = socket.gethostname()
    general_names = [x509.DNSName("localhost")]

    if hostname and hostname.lower() != "localhost":
        general_names.append(x509.DNSName(hostname))

    general_names.extend(x509.IPAddress(ip_address) for ip_address in discover_ip_addresses())
    return x509.SubjectAlternativeName(general_names)


def generate_self_signed_cert() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    hostname = socket.gethostname() or "localhost"
    san_extension = build_subject_alt_names()

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "LAN"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Sharing Board"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )

    valid_from = datetime.datetime.now(datetime.timezone.utc)
    valid_until = valid_from + datetime.timedelta(days=365)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_until)
        .add_extension(san_extension, critical=False)
        .sign(key, hashes.SHA256())
    )

    with open("key.pem", "wb") as key_file:
        key_file.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    with open("cert.pem", "wb") as cert_file:
        cert_file.write(cert.public_bytes(serialization.Encoding.PEM))

    print("Generated key.pem and cert.pem with localhost and LAN IP SAN entries.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--covers":
        raise SystemExit(0 if certificate_covers_host(sys.argv[2]) else 1)
    generate_self_signed_cert()
