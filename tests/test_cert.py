import unittest

from cryptography import x509

import gen_cert


class CertificateHelperTestCase(unittest.TestCase):
    def test_discover_ip_addresses_contains_loopback(self) -> None:
        discovered = {str(address) for address in gen_cert.discover_ip_addresses()}
        self.assertIn("127.0.0.1", discovered)

    def test_subject_alt_names_include_localhost(self) -> None:
        san = gen_cert.build_subject_alt_names()
        san_values = san.get_values_for_type(x509.DNSName)
        self.assertIn("localhost", san_values)


if __name__ == "__main__":
    unittest.main()
