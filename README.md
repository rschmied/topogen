# TopoGen for CML/simple

TopoGen generates CML/simple YAML topologies offline. It does not connect to a
CML controller.

## Features

- generate router topologies with `simple` or `nx` mode
- add an Alpine DNS host and an external connector to every generated lab
- assign router loopbacks and /30 point-to-point networks
- render day-zero configuration for IOSv, IOL-XE, and FRR
- write a YAML file that can be imported into CML/simple

## Installation

```shell
uv sync --all-extras --dev --frozen
```

`nx` mode needs the NumPy and SciPy dependencies in the `all` extra. Run the
CLI with `uv run topogen` if the environment is not active.

## Usage

```shell
uv run topogen 3 --mode nx --template frr --output topogen_lab.yaml
```

`nodes` is the router count. The generated lab also includes an Alpine DNS host
and an external connector.

### Modes

- `simple`: a router chain on square-spiral coordinates
- `nx`: a connected random-shell router graph

Both modes write offline YAML and include the DNS host and external connector.

### Router templates

Offline generation supports these CML node definitions:

- `iosv`
- `iol-xe`
- `frr`

Choose one with `--template`, for example `--template=iosv` or
`--template=frr`. TopoGen uses copied physical-interface maps for these
node definitions and rejects a topology that needs more interfaces than the
selected definition supports.

FRR configuration uses `node.cfg`, `boot.sh`, and `protocols`. IOSv and IOL-XE
configuration uses `ios_config.txt`.

### Configuration

Use `--config` to load an optional TOML file. It controls address pools, domain
name, and device credentials:

```toml
loopbacks = "10.0.0.0/8"
p2pnets = "172.16.0.0/12"
nameserver = "8.8.8.8"
domainname = "virl.lab"
username = "cisco"
password = "cisco"
```

The generated DNS host replaces `nameserver` with its router-facing address.
The user name and password are included in generated device configuration.

## Import and run

Import the resulting YAML file into CML/simple. TopoGen does not upload or
start the lab. The generated DNS host installs dnsmasq at first boot, which
needs Internet access. After the lab starts, configured router loopbacks and
interfaces resolve through that DNS host.
