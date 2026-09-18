# Proton IP Rotator

A small Python CLI for rotating public IP addresses through Proton VPN WireGuard configurations on macOS.

The project uses Proton VPN WireGuard `.conf` files together with `wg`, `wg-quick`, and `wireguard-go` to connect to different Proton VPN servers, verify the resulting public IP address, and optionally rotate between servers at fixed or random intervals.

> [!IMPORTANT]
> This project was developed and tested on an **Intel Mac (x86_64)** running macOS. It has not been tested on Apple Silicon, Linux, or Windows.

> [!WARNING]
> Proton VPN WireGuard configuration files contain private credentials. Never commit your `.conf` files to Git or publish them anywhere. This repository ignores `proton_configs/**/*.conf` for this reason.

## Features

* Show the current public IP address.
* Discover Proton VPN WireGuard configurations recursively.
* Connect to a specific Proton VPN server.
* Disconnect from a specific or currently active server.
* Rotate to a different VPN server.
* Restrict rotation to a specific country.
* Rotate repeatedly at a fixed interval.
* Rotate repeatedly at a random interval.
* Verify that the public IP actually changed after rotation.
* Retry temporary public-IP lookup failures.
* Restore the previous VPN connection when a rotation fails.
* Detect the active WireGuard interface on macOS.
* Clean up stale WireGuard runtime markers when no WireGuard interface is active.
* Handle `Ctrl+C` during timed rotation.
* Unit-tested with pytest without making real VPN or network changes during the test suite.

## Requirements

This project was developed for an Intel Mac.

You will need:

* macOS on Intel (`x86_64`)
* Python 3
* Proton VPN account
* Proton VPN WireGuard configuration files
* WireGuard command-line tools
* `wireguard-go`
* `sudo` access

Check your Mac architecture with:

```bash
uname -m
```

On an Intel Mac this should return:

```text
x86_64
```

## Installing WireGuard on an Intel Mac

The project does not use the Proton VPN macOS application to perform rotations. It controls WireGuard from the command line using `wg-quick`.

The simplest setup with Homebrew is:

```bash
brew install wireguard-tools
```

The Homebrew `wireguard-tools` package provides the `wg` and `wg-quick` commands and currently depends on `wireguard-go`, the userspace WireGuard implementation used on macOS.

Verify the installation:

```bash
which wg
which wg-quick
which wireguard-go
```

Then check that the commands work:

```bash
wg --version
wg-quick --version
wireguard-go --version
```

WireGuard on macOS uses `utun` interfaces. When a tunnel is active you may therefore see an interface such as:

```text
utun4
```

rather than a Linux-style interface such as `wg0`.

You can inspect active WireGuard interfaces with:

```bash
sudo wg show
```

or:

```bash
sudo wg show interfaces
```

The upstream `wireguard-go` implementation documents macOS support through the operating system's `utun` driver.

## Downloading Proton VPN WireGuard Configurations

The program does not contain Proton VPN credentials and does not download VPN configurations for you.

Download the configurations manually from your Proton VPN account.

1. Sign in to your Proton VPN account.
2. Open **Downloads**.
3. Go to **WireGuard configuration**.
4. Give the configuration a name.
5. Select the appropriate platform and VPN options.
6. Select the Proton VPN server you want to use.
7. Create the configuration.
8. Download the generated `.conf` file.

Repeat this for every server you want the rotator to be able to use.

Proton VPN's official instructions are available here:

https://protonvpn.com/support/wireguard-configurations

Proton also documents manual WireGuard configuration on macOS here:

https://protonvpn.com/support/wireguard-manual-macos

### Organising the configurations

Create a `proton_configs` directory in the project and organise the configurations by country.

For example:

```text
proton-ip-rotator/
├── script.py
├── test_script.py
├── requirements.txt
├── pytest.ini
└── proton_configs/
    ├── China/
    │   ├── CN-2.conf
    │   └── CN-12.conf
    ├── Italy/
    │   ├── IT-52.conf
    │   └── IT-81.conf
    ├── Spain/
    │   └── ES-94.conf
    ├── United Kingdom/
    │   └── UK-914.conf
    └── United States/
        └── US-NY-652.conf
```

The directory name is used as the country name by the `--country` option.

Country matching is case-insensitive.

For country names containing spaces, quote the value on the command line:

```bash
python script.py --rotate --country "United Kingdom"
```

### Protect the configuration files

WireGuard `.conf` files contain private key material and must be treated as secrets.

Set restrictive permissions:

```bash
find proton_configs -type f -name '*.conf' -exec chmod 600 {} +
```

Check them with:

```bash
find proton_configs -type f -name '*.conf' -exec ls -l {} \;
```


## Project Setup

Clone the repository:

```bash
git clone <repository-url>
cd proton-ip-rotator
```

Create a virtual environment, I use `uv`:

```bash
uv venv
```

Activate it:

```bash
source .venv/bin/activate
```

Install the project requirements:

```bash
uv pip install -r requirements.txt
```

Check the CLI:

```bash
python script.py --help
```

## Usage

### Show the current public IP

```bash
python script.py --ip
```

The IP is retrieved from:

```text
https://api.ipify.org
```

### List available configurations

```bash
python script.py --list
```

Example:

```text
China: CN-2
Italy: IT-52
Italy: IT-81
United Kingdom: UK-914
United States: US-NY-652
```

## Connecting

Connect to a specific configuration by its filename without the `.conf` extension:

```bash
python script.py --connect IT-52
```

Other examples:

```bash
python script.py --connect CN-2
python script.py --connect UK-914
```

The configuration lookup is case-insensitive.

After connecting, the program retrieves the new public IP and displays the active server.

Because `wg-quick` modifies system networking, macOS may ask for your password through `sudo`.

## Disconnecting

Automatically detect and disconnect the currently active Proton VPN configuration:

```bash
python script.py --disconnect
```

Or disconnect a specific configuration:

```bash
python script.py --disconnect IT-52
```

## Rotating the Public IP

Rotate once to a different available VPN configuration:

```bash
python script.py --rotate
```

The program:

1. Discovers the available WireGuard configurations.
2. Detects the currently active configuration, if any.
3. Selects a different configuration.
4. Records the current public IP.
5. Disconnects the current VPN.
6. Connects to the selected VPN.
7. Retrieves the new public IP.
8. Verifies that the public IP changed.

If the new connection fails, the program attempts to reconnect the previous VPN.

If the new VPN connects but the public IP cannot be determined, the new connection is disconnected and the previous VPN is restored.

If the reported public IP does not change, the new connection is also rejected and the previous VPN is restored.

## Country Restricted Rotation

Restrict a rotation to configurations stored under a specific country directory:

```bash
python script.py --rotate --country Italy
```

Examples:

```bash
python script.py --rotate --country China
python script.py --rotate --country Spain
python script.py --rotate --country "United Kingdom"
python script.py --rotate --country "United States"
```

`--country` can only be used together with `--rotate`.

## Fixed Interval Rotation

Rotate immediately and then continue rotating every 60 seconds:

```bash
python script.py --rotate --interval 60
```

Restrict the timed rotation to one country:

```bash
python script.py --rotate --country Italy --interval 60
```

The first rotation happens immediately. The interval is the delay between subsequent rotations.

Intervals must be positive integers.

## Random Interval Rotation

Rotate immediately, then wait for a randomly selected number of seconds between `MIN` and `MAX` before each subsequent rotation:

```bash
python script.py --rotate --random-interval 30 60
```

Restrict it to a country:

```bash
python script.py --rotate --country Italy --random-interval 30 60
```

`MIN` and `MAX` must both be positive integers, and `MIN` cannot be greater than `MAX`.

`--interval` and `--random-interval` are mutually exclusive.

## Stopping Rotation

Press:

```text
Ctrl+C
```

The program will stop the rotation loop.

On macOS, interrupting WireGuard while it is changing tunnel state can leave a stale runtime `.name` marker behind. The program accounts for this when detecting the active Proton VPN configuration; if WireGuard reports no active interfaces, stale configuration markers belonging to the project's known configurations are removed.

## macOS WireGuard Runtime State

`wireguard-go` uses macOS `utun` interfaces.

Runtime information may be visible under:

```text
/var/run/wireguard/
```

Inspect it with:

```bash
sudo ls -la /var/run/wireguard/
```

An active configuration may have a marker such as:

```text
/var/run/wireguard/IT-52.name
```

Read it with:

```bash
sudo cat /var/run/wireguard/IT-52.name
```

For example, it may contain:

```text
utun4
```

The project compares these markers against the interfaces actually reported by:

```bash
wg show interfaces
```

This avoids treating a stale marker as proof that a VPN configuration is still active.

## Public IP Lookup and Retries

The project uses `api.ipify.org` to determine the current public IP address.

Immediately after changing a VPN connection, DNS or networking may take a short time to become ready. Public IP lookup therefore retries temporary failures before treating the operation as unsuccessful.

This is especially important during rotation, where an IP lookup failure triggers cleanup and restoration of the previous connection.

## Testing

The project uses pytest.

Run the test suite with:

```bash
pytest
```

The tests mock external boundaries such as:

* network requests
* subprocesses
* WireGuard commands
* `sudo` operations
* sleep calls
* random selection

The unit tests therefore do not intentionally connect or disconnect a real VPN.

Coverage is collected through `pytest-cov`.

After running the tests:

```bash
coverage report -m
```

To open the HTML coverage report on macOS:

```bash
open htmlcov/index.html
```

## Security

Treat every Proton VPN WireGuard `.conf` file as a secret.

In particular:

* Never commit `.conf` files.
* Never paste their contents into issues or logs.
* Never publish WireGuard private keys.
* Keep configuration permissions restrictive.
* Check staged changes before pushing to a public repository.


If a WireGuard private key is ever accidentally committed or published, assume it has been compromised and replace the affected Proton VPN configuration rather than merely deleting the key from the latest commit.

## Limitations

* Developed and tested on an Intel Mac (`x86_64`).
* Apple Silicon has not been tested.
* Linux and Windows have not been tested.
* Requires manually downloaded Proton VPN WireGuard configurations.
* Requires administrative privileges for WireGuard network changes.
* This is not a replacement for the official Proton VPN application.
* Features provided by the official Proton VPN application are not automatically reproduced by this script.
* Only one project managed Proton VPN configuration is expected to be active during normal rotation.

## Disclaimer

This is an independent project and is not affiliated with, endorsed by, or maintained by Proton AG or the WireGuard project.

Use it only on systems and VPN accounts you are authorised to control.

Enjoy 🙃
