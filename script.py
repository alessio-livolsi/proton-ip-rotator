"""Rotate public IP addresses using Proton VPN WireGuard configurations."""

import argparse
import random
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent / "proton_configs"
WIREGUARD_RUNTIME_DIR = Path("/var/run/wireguard")
IP_URL = "https://api.ipify.org"
REQUEST_TIMEOUT = 10
IP_RETRY_ATTEMPTS = 5
IP_RETRY_DELAY = 1


def positive_int(value: str) -> int:
    """Return a positive integer."""
    number = int(value)

    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")

    return number


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Rotate public IP addresses using Proton VPN.",
    )

    parser.add_argument(
        "--ip",
        action="store_true",
        help="Show the current public IP address.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available Proton VPN configurations.",
    )
    parser.add_argument(
        "--connect",
        metavar="CONFIG",
        help="Connect using a Proton VPN configuration.",
    )
    parser.add_argument(
        "--disconnect",
        nargs="?",
        const="",
        metavar="CONFIG",
        help="Disconnect the active VPN, or a specific configuration.",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Switch to a different Proton VPN configuration.",
    )
    parser.add_argument(
        "--country",
        metavar="COUNTRY",
        help="Limit rotation to configurations from a country.",
    )

    interval_group = parser.add_mutually_exclusive_group()

    interval_group.add_argument(
        "--interval",
        type=positive_int,
        metavar="SECONDS",
        help="Rotate repeatedly at a fixed interval.",
    )
    interval_group.add_argument(
        "--random-interval",
        type=positive_int,
        nargs=2,
        metavar=("MIN", "MAX"),
        help="Rotate repeatedly at random intervals between MIN and MAX seconds.",
    )

    args = parser.parse_args()

    if args.country and not args.rotate:
        parser.error("--country requires --rotate")

    if args.interval and not args.rotate:
        parser.error("--interval requires --rotate")

    if args.random_interval and not args.rotate:
        parser.error("--random-interval requires --rotate")

    if args.random_interval:
        minimum, maximum = args.random_interval

        if minimum > maximum:
            parser.error("--random-interval MIN must not be greater than MAX")

    return args


def discover_configs(config_dir: Path = CONFIG_DIR) -> list[Path]:
    """Return available WireGuard configuration files."""
    return sorted(config_dir.rglob("*.conf"))


def filter_configs_by_country(
    configs: list[Path],
    country: str,
) -> list[Path]:
    """Return configurations belonging to a country."""
    return [
        config
        for config in configs
        if config.parent.name.casefold() == country.casefold()
    ]


def get_config(name: str, config_dir: Path = CONFIG_DIR) -> Path:
    """Return a WireGuard configuration by name."""
    config_name = Path(name).stem

    matches = [
        config
        for config in discover_configs(config_dir)
        if config.stem.casefold() == config_name.casefold()
    ]

    if not matches:
        raise ValueError(f"Unknown VPN configuration: {name}")

    if len(matches) > 1:
        raise ValueError(f"Ambiguous VPN configuration: {name}")

    return matches[0]


def fetch_public_ip() -> str:
    """Fetch the current public IP address."""
    request = urllib.request.Request(
        IP_URL,
        headers={"User-Agent": "proton-ip-rotator"},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            return response.read().decode().strip()
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(
            f"Unable to determine public IP: {error}",
        ) from error


def get_public_ip() -> str:
    """Return the current public IP address, retrying temporary failures."""
    for attempt in range(1, IP_RETRY_ATTEMPTS + 1):
        try:
            return fetch_public_ip()
        except RuntimeError:
            if attempt == IP_RETRY_ATTEMPTS:
                raise

            time.sleep(IP_RETRY_DELAY)

    raise RuntimeError("Unable to determine public IP.")


def find_executable(name: str) -> str:
    """Return the path to an executable."""
    executable = shutil.which(name)

    if executable is None:
        raise RuntimeError(f"{name} is not installed or not in PATH.")

    return executable


def run_command(command: list[str]) -> str:
    """Run a command and return its standard output."""
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or error.stdout.strip()

        if message:
            raise RuntimeError(message) from error

        raise RuntimeError(f"Command failed: {' '.join(command)}") from error

    return result.stdout.strip()


def run_wg_quick(action: str, config: Path) -> None:
    """Run wg-quick for a WireGuard configuration."""
    command = [
        "sudo",
        find_executable("wg-quick"),
        action,
        str(config),
    ]

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"wg-quick {action} failed for {config.name}.",
        ) from error


def connect_vpn(config: Path) -> None:
    """Connect to a VPN configuration."""
    run_wg_quick("up", config)


def disconnect_vpn(config: Path) -> None:
    """Disconnect a VPN configuration."""
    run_wg_quick("down", config)


def get_wireguard_interfaces() -> set[str]:
    """Return active WireGuard interface names."""
    wg = find_executable("wg")

    output = run_command(
        [
            wg,
            "show",
            "interfaces",
        ]
    )

    return set(output.split())


def get_runtime_interface(config: Path) -> str | None:
    """Return the runtime interface associated with a configuration."""
    name_file = WIREGUARD_RUNTIME_DIR / f"{config.stem}.name"

    if not name_file.is_file():
        return None

    output = run_command(
        [
            "sudo",
            "cat",
            str(name_file),
        ]
    )

    return output or None


def remove_stale_runtime_files(configs: list[Path]) -> None:
    """Remove stale WireGuard configuration name files."""
    for config in configs:
        name_file = WIREGUARD_RUNTIME_DIR / f"{config.stem}.name"

        if not name_file.is_file():
            continue

        try:
            subprocess.run(
                [
                    "sudo",
                    "rm",
                    "-f",
                    str(name_file),
                ],
                check=True,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"Unable to remove stale runtime file for {config.stem}."
            ) from error


def get_active_config(configs: list[Path]) -> Path | None:
    """Return the active Proton VPN configuration, if any."""
    interfaces = get_wireguard_interfaces()

    if not interfaces:
        remove_stale_runtime_files(configs)
        return None

    matches = []

    for config in configs:
        interface = get_runtime_interface(config)

        if interface in interfaces:
            matches.append(config)

    if not matches:
        return None

    if len(matches) > 1:
        raise RuntimeError("Multiple Proton VPN configurations appear to be active.")

    return matches[0]


def get_disconnect_config(name: str | None) -> Path:
    """Return the VPN configuration to disconnect."""
    if name:
        return get_config(name)

    configs = discover_configs()
    active = get_active_config(configs)

    if active is None:
        raise RuntimeError("No Proton VPN configuration is active.")

    return active


def choose_config(
    configs: list[Path],
    current: Path | None = None,
) -> Path:
    """Choose a random configuration different from the current one."""
    candidates = [config for config in configs if config != current]

    if not candidates:
        raise RuntimeError("No alternative WireGuard configuration is available.")

    return random.choice(candidates)


def rotate_ip(country: str | None = None) -> None:
    """Switch to a different VPN server and verify the public IP changes."""
    configs = discover_configs()

    if not configs:
        raise RuntimeError("No WireGuard configurations are available.")

    current = get_active_config(configs)

    if country:
        configs = filter_configs_by_country(configs, country)

        if not configs:
            raise ValueError(f"No VPN configurations found for country: {country}")

    selected = choose_config(configs, current)
    old_ip = get_public_ip()

    if current is None:
        print("Current VPN: none")
    else:
        print(f"Current VPN: {current.parent.name} / {current.stem}")

    print(f"Current IP:  {old_ip}")
    print(f"Next VPN:    {selected.parent.name} / {selected.stem}")

    if current is not None:
        print(f"Disconnecting {current.stem}...")
        disconnect_vpn(current)

    print(f"Connecting {selected.stem}...")

    try:
        connect_vpn(selected)
    except RuntimeError:
        if current is not None:
            print(
                f"Connection failed. Reconnecting {current.stem}...",
                file=sys.stderr,
            )
            connect_vpn(current)
        raise

    try:
        new_ip = get_public_ip()
    except RuntimeError:
        disconnect_vpn(selected)

        if current is not None:
            connect_vpn(current)

        raise

    if new_ip == old_ip:
        disconnect_vpn(selected)

        if current is not None:
            connect_vpn(current)

        raise RuntimeError(
            f"Public IP did not change after connecting to {selected.stem}."
        )

    print(f"New IP:      {new_ip}")
    print(f"Connected:   {selected.parent.name} / {selected.stem}")


def get_rotation_delay(
    interval: int | None,
    random_interval: list[int] | None,
) -> int | None:
    """Return the delay before the next rotation."""
    if random_interval:
        minimum, maximum = random_interval
        return random.randint(minimum, maximum)

    return interval


def run_rotation_loop(
    country: str | None,
    interval: int | None,
    random_interval: list[int] | None,
) -> None:
    """Rotate IP addresses until interrupted."""
    while True:
        rotate_ip(country)

        delay = get_rotation_delay(
            interval,
            random_interval,
        )

        if delay is None:
            return

        print(f"Next rotation in {delay} seconds.")

        time.sleep(delay)


def print_configs(configs: list[Path]) -> None:
    """Print available WireGuard configurations."""
    if not configs:
        print(f"No WireGuard configurations found in {CONFIG_DIR}")
        return

    for config in configs:
        country = config.parent.name
        print(f"{country}: {config.stem}")


def main() -> int:
    """Run the command-line interface."""
    args = parse_args()

    try:
        if args.ip:
            print(get_public_ip())
            return 0

        if args.list:
            print_configs(discover_configs())
            return 0

        if args.connect:
            config = get_config(args.connect)
            connect_vpn(config)
            new_ip = get_public_ip()
            print(f"New IP:      {new_ip}")
            print(f"Connected:   {config.parent.name} / {config.stem}")
            return 0

        if args.disconnect is not None:
            config = get_disconnect_config(args.disconnect)
            disconnect_vpn(config)
            print(f"Disconnected {config.stem}.")
            return 0

        if args.rotate:
            run_rotation_loop(
                args.country,
                args.interval,
                args.random_interval,
            )
            return 0

    except KeyboardInterrupt:
        print("\nRotation stopped.")
        return 0
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print("Use --help to see available commands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
