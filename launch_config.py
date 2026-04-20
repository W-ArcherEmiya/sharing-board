import secrets
import socket

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789abcdefghijkmnpqrstuvwxyz"


def get_host_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return "localhost"


def random_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


if __name__ == "__main__":
    print(f"{get_host_ip()}|{random_code(8)}|{random_code(12)}")
