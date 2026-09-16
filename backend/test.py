#!/usr/bin/env python3

import json
import socket
import subprocess
import sys
import time

try:
    import requests
    import pyotp
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([
        sys.executable,
        "-m",
        "pip",
        "install",
        "requests",
        "pyotp"
    ])
    import requests
    import pyotp


# ============================================================
# ANGEL ONE CONFIGURATION
# ============================================================
# Put your REAL values between the quotes.
#
# IMPORTANT:
# TOTP_SECRET must be the TOTP SECRET/KEY used to generate
# your Angel One OTP, NOT the current 6-digit OTP.
# ============================================================

CLIENT_CODE = "CLIENT_CODE"
MPIN = "MPIN"
API_KEY = "API_KEY"

# Example:
# TOTP_SECRET = "JBSWY3DPEHPK3PXP"
TOTP_SECRET = "TOTP_SECRET"


# ============================================================
# ANGEL ONE API
# ============================================================

BASE_URL = (
    "https://apiconnect.angelone.in"
    "/rest/auth/angelbroking/user/v1"
)


def get_local_ip():
    """Get EC2 private/local IP."""

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def get_public_ip():
    """Get EC2 public IP."""

    try:
        result = subprocess.run(
            [
                "curl",
                "-4",
                "-fsS",
                "--max-time",
                "10",
                "https://checkip.amazonaws.com"
            ],
            capture_output=True,
            text=True,
            check=True
        )

        return result.stdout.strip()

    except Exception as exc:
        print(f"Could not automatically determine public IP: {exc}")
        return ""


def get_mac_address():
    """Get MAC address of the interface used by EC2."""

    try:
        route = subprocess.run(
            ["ip", "route", "get", "1.1.1.1"],
            capture_output=True,
            text=True,
            check=True
        )

        parts = route.stdout.split()

        interface = None

        if "dev" in parts:
            interface = parts[parts.index("dev") + 1]

        if not interface:
            return ""

        link = subprocess.run(
            ["ip", "link", "show", interface],
            capture_output=True,
            text=True,
            check=True
        )

        for line in link.stdout.splitlines():
            if "link/ether" in line:
                return line.split()[1]

    except Exception:
        pass

    return ""


def generate_totp():
    """Generate the current Angel One TOTP."""

    try:
        totp = pyotp.TOTP(TOTP_SECRET)

        current_otp = totp.now()

        remaining = 30 - (int(time.time()) % 30)

        print()
        print(f"Generated TOTP: {current_otp}")
        print(f"TOTP validity remaining: ~{remaining} seconds")

        return current_otp

    except Exception as exc:
        print()
        print("ERROR generating TOTP.")
        print()
        print("Check that TOTP_SECRET is your actual")
        print("TOTP secret/key and not a 6-digit OTP.")
        print()
        print(f"Details: {exc}")

        sys.exit(1)


def redact(data):
    """Remove authentication tokens before displaying response."""

    if isinstance(data, dict):

        sensitive = {
            "jwtToken",
            "refreshToken",
            "feedToken",
            "accessToken",
            "access_token",
            "refresh_token",
            "feed_token"
        }

        result = {}

        for key, value in data.items():

            if key in sensitive:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact(value)

        return result

    if isinstance(data, list):
        return [redact(x) for x in data]

    return data


def test_endpoint(endpoint, payload, headers):

    url = f"{BASE_URL}/{endpoint}"

    print()
    print("=" * 70)
    print(f"TESTING: {endpoint}")
    print("=" * 70)

    print()
    print("Request URL:")
    print(url)

    print()
    print("Request body:")
    print(
        json.dumps(
            {
                key: "[REDACTED]"
                if key in ("password", "mpin", "totp")
                else value
                for key, value in payload.items()
            },
            indent=2
        )
    )

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        print()
        print(f"HTTP STATUS: {response.status_code}")

        if not response.text.strip():

            print()
            print("RESPONSE BODY: [EMPTY]")

            if response.status_code == 200:
                print()
                print(
                    "RESULT: HTTP 200 but the response body is empty."
                )

            return

        try:

            data = response.json()

            print()
            print("RESPONSE JSON:")

            print(
                json.dumps(
                    redact(data),
                    indent=2,
                    ensure_ascii=False
                )
            )

            print()

            if data.get("status") is True:

                print(">>> AUTHENTICATION SUCCESSFUL <<<")

                print()
                print(
                    "The response contains authentication "
                    "tokens."
                )

                print(
                    "Tokens were deliberately REDACTED "
                    "from this output."
                )

            else:

                print(">>> AUTHENTICATION FAILED <<<")

                if data.get("message"):
                    print(
                        f"Message : {data.get('message')}"
                    )

                if data.get("errorcode"):
                    print(
                        f"Errorcode: {data.get('errorcode')}"
                    )

        except json.JSONDecodeError:

            print()
            print("RESPONSE WAS NOT JSON:")
            print(response.text)

    except requests.exceptions.Timeout:

        print()
        print("ERROR: Angel One request timed out.")

    except requests.exceptions.RequestException as exc:

        print()
        print(f"ERROR: Request failed: {exc}")


def main():

    print()
    print("=" * 70)
    print("ANGEL ONE SMARTAPI AUTHENTICATION TEST")
    print("=" * 70)

    # --------------------------------------------------------
    # Validate configuration
    # --------------------------------------------------------

    values = {
        "CLIENT_CODE": CLIENT_CODE,
        "MPIN": MPIN,
        "API_KEY": API_KEY,
        "TOTP_SECRET": TOTP_SECRET
    }

    for name, value in values.items():

        if not value or value.startswith("YOUR_"):

            print()
            print(f"ERROR: Please configure {name} at the top")
            print("of this Python file.")

            sys.exit(1)

    # --------------------------------------------------------
    # Network information
    # --------------------------------------------------------

    print()
    print("Detecting EC2 network information...")

    local_ip = get_local_ip()
    public_ip = get_public_ip()
    mac_address = get_mac_address()

    print()
    print(f"Local IP : {local_ip}")
    print(f"Public IP: {public_ip}")
    print(f"MAC      : {mac_address}")

    if not public_ip:
        print()
        print(
            "WARNING: Could not determine EC2 public IP."
        )
        sys.exit(1)

    if not mac_address:
        print()
        print(
            "WARNING: Could not determine EC2 MAC address."
        )
        sys.exit(1)

    # --------------------------------------------------------
    # Headers
    # --------------------------------------------------------

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": local_ip,
        "X-ClientPublicIP": public_ip,
        "X-MACAddress": mac_address,
        "X-PrivateKey": API_KEY,
    }

    # ========================================================
    # TEST 1
    #
    # Documented loginByPassword endpoint.
    #
    # Angel One expects the PIN/MPIN in "password".
    # ========================================================

    print()
    print("Generating fresh TOTP...")

    totp1 = generate_totp()

    payload_password = {
        "clientcode": CLIENT_CODE,
        "password": MPIN,
        "totp": totp1
    }

    test_endpoint(
        "loginByPassword",
        payload_password,
        headers
    )

    # --------------------------------------------------------
    # Wait before second authentication request
    # --------------------------------------------------------

    print()
    print("Waiting 2 seconds...")
    time.sleep(2)

    # ========================================================
    # TEST 2
    #
    # loginByMPIN
    #
    # Generate a NEW TOTP because the previous request may
    # have consumed/invalidated the OTP.
    # ========================================================

    print()
    print("Generating a NEW TOTP for loginByMPIN...")

    totp2 = generate_totp()

    payload_mpin = {
        "clientcode": CLIENT_CODE,
        "mpin": MPIN,
        "totp": totp2
    }

    test_endpoint(
        "loginByMPIN",
        payload_mpin,
        headers
    )

    print()
    print("=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
