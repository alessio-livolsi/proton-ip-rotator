"""Rotate public IP addresses using Proton VPN WireGuard configurations."""

import argparse
import random
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent / "proton_configs"
IP_URL = "https://api.ipify.org"
REQUEST_TIMEOUT = 10


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

    return parser.parse_args()


def discover_configs(config_dir: Path = CONFIG_DIR) -> list[Path]:
    """Return available WireGuard configuration files."""
    return sorted(config_dir.rglob("*.conf"))


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


def get_public_ip() -> str:
    """Return the current public IP address."""
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


def find_executable(name: str) -> str:
    """Return the path to an executable."""
    executable = shutil.which(name)

    if executable is None:
        raise RuntimeError(f"{name} is not installed or not in PATH.")

    return executable


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


def get_active_config(configs: list[Path]) -> Path | None:
    """Return the active Proton VPN configuration, if any."""
    runtime_dir = Path("/var/run/wireguard")

    matches = [
        config for config in configs if (runtime_dir / f"{config.stem}.name").is_file()
    ]

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


def rotate_ip() -> None:
    """Switch to a different VPN server and verify the public IP changes."""
    configs = discover_configs()

    if not configs:
        raise RuntimeError("No WireGuard configurations are available.")

    current = get_active_config(configs)
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
            print(f"Connected using {config.stem}.")
            return 0

        if args.disconnect is not None:
            config = get_disconnect_config(args.disconnect)
            disconnect_vpn(config)
            print(f"Disconnected {config.stem}.")
            return 0

        if args.rotate:
            rotate_ip()
            return 0

    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print("Use --help to see available commands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
