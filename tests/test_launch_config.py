import unittest

import launch_config


class LaunchConfigTestCase(unittest.TestCase):
    def test_choose_best_ip_prefers_real_lan_adapter_over_vpn(self) -> None:
        candidates = [
            {
                "ip": "130.209.150.162",
                "alias": "gucsasa1.cent.gla.ac.uk_a1db8315",
                "description": "OpenConnect Tunnel",
                "gateway": "0.0.0.0",
            },
            {
                "ip": "10.217.198.231",
                "alias": "以太网",
                "description": "Realtek PCIe 2.5GbE Family Controller",
                "gateway": "10.217.192.1",
            },
        ]

        self.assertEqual(launch_config.choose_best_ip(candidates), "10.217.198.231")

    def test_choose_best_ip_ignores_link_local_addresses(self) -> None:
        candidates = [
            {
                "ip": "169.254.145.61",
                "alias": "WLAN",
                "description": "Intel Wi-Fi",
                "gateway": "",
            }
        ]

        self.assertIsNone(launch_config.choose_best_ip(candidates))


if __name__ == "__main__":
    unittest.main()
