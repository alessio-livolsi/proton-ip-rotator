"""Tests for the Proton IP rotator."""

import argparse
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

import script


def make_config(tmp_path: Path, country: str, name: str) -> Path:
    """Create an empty WireGuard configuration for a test."""
    country_dir = tmp_path / country
    country_dir.mkdir(exist_ok=True)

    config = country_dir / f"{name}.conf"
    config.touch()

    return config


def test_positive_int() -> None:
    assert script.positive_int("10") == 10


@pytest.mark.parametrize("value", ["0", "-1"])
def test_positive_int_rejects_non_positive_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        script.positive_int(value)


def test_parse_args_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "script.py",
            "--rotate",
            "--country",
            "Italy",
            "--interval",
            "60",
        ],
    )

    args = script.parse_args()

    assert args.rotate is True
    assert args.country == "Italy"
    assert args.interval == 60
    assert args.random_interval is None


@pytest.mark.parametrize(
    "country",
    [
        "United Kingdom",
        "United States",
    ],
)
def test_parse_args_country_with_spaces(
    monkeypatch: pytest.MonkeyPatch,
    country: str,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "script.py",
            "--rotate",
            "--country",
            country,
        ],
    )

    args = script.parse_args()

    assert args.rotate is True
    assert args.country == country


def test_parse_args_random_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "script.py",
            "--rotate",
            "--random-interval",
            "30",
            "60",
        ],
    )

    args = script.parse_args()

    assert args.rotate is True
    assert args.interval is None
    assert args.random_interval == [30, 60]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--country", "Italy"],
        ["--interval", "60"],
        ["--random-interval", "30", "60"],
        ["--rotate", "--random-interval", "60", "30"],
        ["--rotate", "--interval", "60", "--random-interval", "30", "60"],
    ],
)
def test_parse_args_rejects_invalid_arguments(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["script.py", *arguments])

    with pytest.raises(SystemExit) as error:
        script.parse_args()

    assert error.value.code == 2


def test_discover_configs(tmp_path: Path) -> None:
    italy = make_config(tmp_path, "Italy", "IT-52")
    china = make_config(tmp_path, "China", "CN-2")

    assert script.discover_configs(tmp_path) == [china, italy]


def test_filter_configs_by_country_is_case_insensitive(tmp_path: Path) -> None:
    italy = make_config(tmp_path, "Italy", "IT-52")
    china = make_config(tmp_path, "China", "CN-2")

    configs = [italy, china]

    assert script.filter_configs_by_country(configs, "italy") == [italy]


@pytest.mark.parametrize(
    "country",
    [
        "United Kingdom",
        "United States",
    ],
)
def test_filter_configs_by_country_handles_spaces(
    tmp_path: Path,
    country: str,
) -> None:
    config = make_config(tmp_path, country, "SERVER")

    assert script.filter_configs_by_country(
        [config],
        country,
    ) == [config]


def test_get_config_is_case_insensitive(tmp_path: Path) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")

    assert script.get_config("it-52", tmp_path) == config


def test_get_config_rejects_unknown_config(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown VPN configuration"):
        script.get_config("DOES-NOT-EXIST", tmp_path)


def test_get_config_rejects_ambiguous_config(tmp_path: Path) -> None:
    make_config(tmp_path, "Italy", "SERVER")
    make_config(tmp_path, "Spain", "SERVER")

    with pytest.raises(ValueError, match="Ambiguous VPN configuration"):
        script.get_config("SERVER", tmp_path)


def test_fetch_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return b"203.0.113.10\n"

    monkeypatch.setattr(
        script.urllib.request,
        "urlopen",
        lambda request, timeout: Response(),
    )

    assert script.fetch_public_ip() == "203.0.113.10"


def test_fetch_public_ip_handles_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(request, timeout):
        raise urllib.error.URLError("network unavailable")

    monkeypatch.setattr(script.urllib.request, "urlopen", fail)

    with pytest.raises(RuntimeError, match="Unable to determine public IP"):
        script.fetch_public_ip()


def test_get_public_ip_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def fetch() -> str:
        nonlocal attempts
        attempts += 1

        if attempts < 3:
            raise RuntimeError("temporary failure")

        return "203.0.113.10"

    monkeypatch.setattr(script, "fetch_public_ip", fetch)
    monkeypatch.setattr(script.time, "sleep", lambda seconds: None)

    assert script.get_public_ip() == "203.0.113.10"
    assert attempts == 3


def test_get_public_ip_raises_after_final_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def fetch() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(script, "fetch_public_ip", fetch)
    monkeypatch.setattr(script.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="temporary failure"):
        script.get_public_ip()

    assert attempts == script.IP_RETRY_ATTEMPTS


def test_find_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script.shutil, "which", lambda name: "/usr/local/bin/wg")

    assert script.find_executable("wg") == "/usr/local/bin/wg"


def test_find_executable_rejects_missing_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="wg is not installed"):
        script.find_executable("wg")


def test_run_command_returns_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    result = subprocess.CompletedProcess(
        args=["wg"],
        returncode=0,
        stdout="utun4\n",
        stderr="",
    )

    monkeypatch.setattr(script.subprocess, "run", lambda *args, **kwargs: result)

    assert script.run_command(["wg"]) == "utun4"


def test_run_command_reports_command_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = subprocess.CalledProcessError(
        1,
        ["wg"],
        stderr="WireGuard failed\n",
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(script.subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="WireGuard failed"):
        script.run_command(["wg"])


def test_run_command_reports_command_when_no_error_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = subprocess.CalledProcessError(
        1,
        ["wg", "show"],
        output="",
        stderr="",
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(script.subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="Command failed: wg show"):
        script.run_command(["wg", "show"])


def test_run_wg_quick(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    commands = []

    monkeypatch.setattr(
        script,
        "find_executable",
        lambda name: "/usr/local/bin/wg-quick",
    )
    monkeypatch.setattr(
        script.subprocess,
        "run",
        lambda command, check: commands.append(command),
    )

    script.run_wg_quick("up", config)

    assert commands == [
        [
            "sudo",
            "/usr/local/bin/wg-quick",
            "up",
            str(config),
        ]
    ]


def test_run_wg_quick_handles_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")

    monkeypatch.setattr(
        script,
        "find_executable",
        lambda name: "/usr/local/bin/wg-quick",
    )

    def fail(command, check):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(script.subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="wg-quick up failed for IT-52.conf"):
        script.run_wg_quick("up", config)


def test_connect_and_disconnect_vpn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    actions = []

    monkeypatch.setattr(
        script,
        "run_wg_quick",
        lambda action, selected: actions.append((action, selected)),
    )

    script.connect_vpn(config)
    script.disconnect_vpn(config)

    assert actions == [
        ("up", config),
        ("down", config),
    ]


def test_get_wireguard_interfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "find_executable", lambda name: "/usr/bin/wg")
    monkeypatch.setattr(
        script,
        "run_command",
        lambda command: "utun4 utun5",
    )

    assert script.get_wireguard_interfaces() == {"utun4", "utun5"}


def test_get_runtime_interface_returns_none_without_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    monkeypatch.setattr(script, "WIREGUARD_RUNTIME_DIR", runtime_dir)

    assert script.get_runtime_interface(config) is None


def test_get_runtime_interface_reads_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "IT-52.name").touch()

    monkeypatch.setattr(script, "WIREGUARD_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(script, "run_command", lambda command: "utun4")

    assert script.get_runtime_interface(config) == "utun4"


def test_remove_stale_runtime_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    name_file = runtime_dir / "IT-52.name"
    name_file.touch()
    commands = []

    monkeypatch.setattr(script, "WIREGUARD_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(
        script.subprocess,
        "run",
        lambda command, check: commands.append(command),
    )

    script.remove_stale_runtime_files([config])

    assert commands == [
        [
            "sudo",
            "rm",
            "-f",
            str(name_file),
        ]
    ]


def test_remove_stale_runtime_files_handles_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "IT-52.name").touch()

    monkeypatch.setattr(script, "WIREGUARD_RUNTIME_DIR", runtime_dir)

    def fail(command, check):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(script.subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="Unable to remove stale runtime file"):
        script.remove_stale_runtime_files([config])


def test_get_active_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    italy = make_config(tmp_path, "Italy", "IT-52")
    china = make_config(tmp_path, "China", "CN-2")

    monkeypatch.setattr(
        script,
        "get_wireguard_interfaces",
        lambda: {"utun4"},
    )
    monkeypatch.setattr(
        script,
        "get_runtime_interface",
        lambda config: "utun4" if config == italy else None,
    )

    assert script.get_active_config([italy, china]) == italy


def test_get_active_config_returns_none_without_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")

    monkeypatch.setattr(
        script,
        "get_wireguard_interfaces",
        lambda: {"utun4"},
    )
    monkeypatch.setattr(
        script,
        "get_runtime_interface",
        lambda selected: None,
    )

    assert script.get_active_config([config]) is None


def test_get_active_config_cleans_stale_markers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    cleaned = []

    monkeypatch.setattr(script, "get_wireguard_interfaces", lambda: set())
    monkeypatch.setattr(
        script,
        "remove_stale_runtime_files",
        lambda configs: cleaned.extend(configs),
    )

    assert script.get_active_config([config]) is None
    assert cleaned == [config]


def test_get_active_config_rejects_multiple_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = make_config(tmp_path, "Italy", "IT-52")
    second = make_config(tmp_path, "Italy", "IT-81")

    monkeypatch.setattr(
        script,
        "get_wireguard_interfaces",
        lambda: {"utun4"},
    )
    monkeypatch.setattr(
        script,
        "get_runtime_interface",
        lambda config: "utun4",
    )

    with pytest.raises(RuntimeError, match="Multiple Proton VPN"):
        script.get_active_config([first, second])


def test_get_disconnect_config_by_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")

    monkeypatch.setattr(script, "get_config", lambda name: config)

    assert script.get_disconnect_config("IT-52") == config


def test_get_disconnect_config_uses_active_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")

    monkeypatch.setattr(script, "discover_configs", lambda: [config])
    monkeypatch.setattr(
        script,
        "get_active_config",
        lambda configs: config,
    )

    assert script.get_disconnect_config(None) == config


def test_get_disconnect_config_rejects_missing_active_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script, "discover_configs", list)
    monkeypatch.setattr(script, "get_active_config", lambda configs: None)

    with pytest.raises(RuntimeError, match="No Proton VPN configuration is active"):
        script.get_disconnect_config(None)


def test_choose_config_excludes_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current = make_config(tmp_path, "Italy", "IT-52")
    alternative = make_config(tmp_path, "Italy", "IT-81")

    monkeypatch.setattr(script.random, "choice", lambda configs: configs[0])

    assert script.choose_config([current, alternative], current) == alternative


def test_choose_config_requires_alternative(tmp_path: Path) -> None:
    current = make_config(tmp_path, "Italy", "IT-52")

    with pytest.raises(RuntimeError, match="No alternative"):
        script.choose_config([current], current)


def test_rotate_ip_changes_vpn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    current = make_config(tmp_path, "Italy", "IT-52")
    selected = make_config(tmp_path, "Italy", "IT-81")
    disconnected = []
    connected = []
    ips = iter(["203.0.113.10", "203.0.113.20"])

    monkeypatch.setattr(script, "discover_configs", lambda: [current, selected])
    monkeypatch.setattr(script, "get_active_config", lambda configs: current)
    monkeypatch.setattr(script, "choose_config", lambda configs, active: selected)
    monkeypatch.setattr(script, "get_public_ip", lambda: next(ips))
    monkeypatch.setattr(script, "disconnect_vpn", disconnected.append)
    monkeypatch.setattr(script, "connect_vpn", connected.append)

    script.rotate_ip()

    output = capsys.readouterr().out

    assert disconnected == [current]
    assert connected == [selected]
    assert "New IP:      203.0.113.20" in output
    assert "Connected:   Italy / IT-81" in output


def test_rotate_ip_connects_when_no_vpn_is_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    selected = make_config(tmp_path, "Italy", "IT-81")
    connected = []
    ips = iter(["203.0.113.10", "203.0.113.20"])

    monkeypatch.setattr(script, "discover_configs", lambda: [selected])
    monkeypatch.setattr(script, "get_active_config", lambda configs: None)
    monkeypatch.setattr(script, "choose_config", lambda configs, active: selected)
    monkeypatch.setattr(script, "get_public_ip", lambda: next(ips))
    monkeypatch.setattr(script, "connect_vpn", connected.append)

    script.rotate_ip()

    output = capsys.readouterr().out

    assert connected == [selected]
    assert "Current VPN: none" in output


def test_rotate_ip_filters_by_country(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    italy = make_config(tmp_path, "Italy", "IT-52")
    spain = make_config(tmp_path, "Spain", "ES-94")
    filtered_configs = []

    monkeypatch.setattr(script, "discover_configs", lambda: [italy, spain])
    monkeypatch.setattr(script, "get_active_config", lambda configs: None)

    def choose(configs, current):
        filtered_configs.extend(configs)
        return configs[0]

    ips = iter(["203.0.113.10", "203.0.113.20"])

    monkeypatch.setattr(script, "choose_config", choose)
    monkeypatch.setattr(script, "get_public_ip", lambda: next(ips))
    monkeypatch.setattr(script, "connect_vpn", lambda config: None)

    script.rotate_ip("Italy")

    assert filtered_configs == [italy]


def test_rotate_ip_rejects_missing_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script, "discover_configs", list)

    with pytest.raises(RuntimeError, match="No WireGuard configurations"):
        script.rotate_ip()


def test_rotate_ip_rejects_unknown_country(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")

    monkeypatch.setattr(script, "discover_configs", lambda: [config])
    monkeypatch.setattr(script, "get_active_config", lambda configs: None)

    with pytest.raises(ValueError, match="No VPN configurations found for country"):
        script.rotate_ip("Spain")


def test_rotate_ip_restores_current_vpn_when_connection_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    current = make_config(tmp_path, "Italy", "IT-52")
    selected = make_config(tmp_path, "Italy", "IT-81")
    connections = []

    def connect(config: Path) -> None:
        connections.append(config)

        if config == selected:
            raise RuntimeError("connection failed")

    monkeypatch.setattr(script, "discover_configs", lambda: [current, selected])
    monkeypatch.setattr(script, "get_active_config", lambda configs: current)
    monkeypatch.setattr(script, "choose_config", lambda configs, active: selected)
    monkeypatch.setattr(script, "get_public_ip", lambda: "203.0.113.10")
    monkeypatch.setattr(script, "disconnect_vpn", lambda config: None)
    monkeypatch.setattr(script, "connect_vpn", connect)

    with pytest.raises(RuntimeError, match="connection failed"):
        script.rotate_ip()

    output = capsys.readouterr()

    assert connections == [selected, current]
    assert "Connection failed. Reconnecting IT-52..." in output.err


def test_rotate_ip_restores_current_vpn_when_ip_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current = make_config(tmp_path, "Italy", "IT-52")
    selected = make_config(tmp_path, "Italy", "IT-81")
    disconnected = []
    connected = []
    calls = 0

    def get_ip() -> str:
        nonlocal calls
        calls += 1

        if calls == 1:
            return "203.0.113.10"

        raise RuntimeError("IP lookup failed")

    monkeypatch.setattr(script, "discover_configs", lambda: [current, selected])
    monkeypatch.setattr(script, "get_active_config", lambda configs: current)
    monkeypatch.setattr(script, "choose_config", lambda configs, active: selected)
    monkeypatch.setattr(script, "get_public_ip", get_ip)
    monkeypatch.setattr(script, "disconnect_vpn", disconnected.append)
    monkeypatch.setattr(script, "connect_vpn", connected.append)

    with pytest.raises(RuntimeError, match="IP lookup failed"):
        script.rotate_ip()

    assert disconnected == [current, selected]
    assert connected == [selected, current]


def test_rotate_ip_restores_current_vpn_when_ip_does_not_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current = make_config(tmp_path, "Italy", "IT-52")
    selected = make_config(tmp_path, "Italy", "IT-81")
    disconnected = []
    connected = []

    monkeypatch.setattr(script, "discover_configs", lambda: [current, selected])
    monkeypatch.setattr(script, "get_active_config", lambda configs: current)
    monkeypatch.setattr(script, "choose_config", lambda configs, active: selected)
    monkeypatch.setattr(script, "get_public_ip", lambda: "203.0.113.10")
    monkeypatch.setattr(script, "disconnect_vpn", disconnected.append)
    monkeypatch.setattr(script, "connect_vpn", connected.append)

    with pytest.raises(RuntimeError, match="Public IP did not change"):
        script.rotate_ip()

    assert disconnected == [current, selected]
    assert connected == [selected, current]


def test_get_rotation_delay_uses_fixed_interval() -> None:
    assert script.get_rotation_delay(60, None) == 60


def test_get_rotation_delay_uses_random_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script.random, "randint", lambda minimum, maximum: 45)

    assert script.get_rotation_delay(None, [30, 60]) == 45


def test_rotation_loop_rotates_once_without_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rotations = []

    monkeypatch.setattr(script, "rotate_ip", rotations.append)

    script.run_rotation_loop("Italy", None, None)

    assert rotations == ["Italy"]


def test_rotation_loop_waits_before_next_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rotations = []
    sleeps = []

    def rotate(country: str | None) -> None:
        rotations.append(country)

        if len(rotations) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(script, "rotate_ip", rotate)
    monkeypatch.setattr(script.time, "sleep", sleeps.append)

    with pytest.raises(KeyboardInterrupt):
        script.run_rotation_loop("Italy", 60, None)

    assert rotations == ["Italy", "Italy"]
    assert sleeps == [60]


def test_print_configs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    italy = make_config(tmp_path, "Italy", "IT-52")
    china = make_config(tmp_path, "China", "CN-2")

    script.print_configs([china, italy])

    assert capsys.readouterr().out == "China: CN-2\nItaly: IT-52\n"


def test_print_configs_handles_empty_list(
    capsys: pytest.CaptureFixture,
) -> None:
    script.print_configs([])

    assert "No WireGuard configurations found" in capsys.readouterr().out


def make_args(**changes) -> SimpleNamespace:
    """Return command-line arguments for a main-function test."""
    values = {
        "ip": False,
        "list": False,
        "connect": None,
        "disconnect": None,
        "rotate": False,
        "country": None,
        "interval": None,
        "random_interval": None,
    }
    values.update(changes)

    return SimpleNamespace(**values)


def test_main_shows_public_ip(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    monkeypatch.setattr(script, "parse_args", lambda: make_args(ip=True))
    monkeypatch.setattr(script, "get_public_ip", lambda: "203.0.113.10")

    assert script.main() == 0
    assert capsys.readouterr().out == "203.0.113.10\n"


def test_main_lists_configs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")

    monkeypatch.setattr(
        script,
        "parse_args",
        lambda: make_args(list=True),
    )
    monkeypatch.setattr(script, "discover_configs", lambda: [config])

    assert script.main() == 0
    assert capsys.readouterr().out == "Italy: IT-52\n"


def test_main_connects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    connected = []

    monkeypatch.setattr(
        script,
        "parse_args",
        lambda: make_args(connect="IT-52"),
    )
    monkeypatch.setattr(script, "get_config", lambda name: config)
    monkeypatch.setattr(script, "connect_vpn", connected.append)
    monkeypatch.setattr(script, "get_public_ip", lambda: "203.0.113.10")

    assert script.main() == 0

    output = capsys.readouterr().out

    assert connected == [config]
    assert "New IP:      203.0.113.10" in output
    assert "Connected:   Italy / IT-52" in output


def test_main_disconnects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = make_config(tmp_path, "Italy", "IT-52")
    disconnected = []

    monkeypatch.setattr(
        script,
        "parse_args",
        lambda: make_args(disconnect=""),
    )
    monkeypatch.setattr(
        script,
        "get_disconnect_config",
        lambda name: config,
    )
    monkeypatch.setattr(script, "disconnect_vpn", disconnected.append)

    assert script.main() == 0
    assert disconnected == [config]
    assert capsys.readouterr().out == "Disconnected IT-52.\n"


def test_main_rotates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    monkeypatch.setattr(
        script,
        "parse_args",
        lambda: make_args(
            rotate=True,
            country="Italy",
            interval=60,
        ),
    )
    monkeypatch.setattr(
        script,
        "run_rotation_loop",
        lambda country, interval, random_interval: calls.append(
            (country, interval, random_interval)
        ),
    )

    assert script.main() == 0
    assert calls == [("Italy", 60, None)]


def test_main_handles_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    monkeypatch.setattr(script, "parse_args", lambda: make_args(ip=True))

    def fail() -> str:
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(script, "get_public_ip", fail)

    assert script.main() == 1
    assert "Error: network unavailable" in capsys.readouterr().err


def test_main_handles_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    monkeypatch.setattr(script, "parse_args", lambda: make_args(rotate=True))

    def interrupt(country, interval, random_interval):
        raise KeyboardInterrupt

    monkeypatch.setattr(script, "run_rotation_loop", interrupt)

    assert script.main() == 0
    assert "Rotation stopped." in capsys.readouterr().out


def test_main_without_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    monkeypatch.setattr(script, "parse_args", make_args)

    assert script.main() == 0
    assert capsys.readouterr().out == "Use --help to see available commands.\n"
