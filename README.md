# TopoGen for CML2

This package provides a `topogen` command which can create CML2 topologies.
It does this by using the PCL (VIRL Python Client Library) to talk to a live
controller, creating the lab, nodes and links on the fly.

## Features

- create topologies of arbitrary size (up to 400 tested, this is N^2)
- can use templates to provide node configurations (currently a built-in
  DNS host template and an IOSv template exist)
- provide network numbering for all links (/30) and router loopbacks
- provide a DNS configuration so that all loopbacks can be resolved both from
  the DNS host as well as from all routers (provided the template configures
  DNS)

## Configuration

### CML2

CML2 access is provided via the environment.  Like shown with this shell snippet:

```shell
VIRL2_URL="https://cml-controller.cml.lab"
VIRL2_USER="someuser"
VIRL2_PASS="somepass"
export VIRL2_URL VIRL2_USER VIRL2_PASS
```

In addition, a CA file in PEM format can be provided which can be used to verify
the cert presented by the controller... The default CA file of the controller is
included in the repo.

For this to work, it's also required to have proper name resolution (e.g. add
`192.168.254.123 cml-controller.cml.lab` with **the correct IP** into your hosts
file).

### Tool

The tool accepts a variety of command line switches... they are all listed by
providing `-h` or `--help`:

```plain
$ topogen --help
usage: topogen [-h] [-c CONFIGFILE] [-w] [-v] [-l LOGLEVEL] [-p] [--ca CAFILE] [-i] [-d DISTANCE] [-L LABNAME] [-T TEMPLATE]
               [--list-templates] [-m {nx,simple}]
               [nodes]

generate test topology files and configurations for CML2

positional arguments:
  nodes                 Number of nodes to generate

optional arguments:
  -h, --help            show this help message and exit
  --ca CAFILE           Use the CA certificate from this file (PEM format), defaults to ca.pem
  -i, --insecure        If no CA provided, do not verify TLS (insecure!)
  -d DISTANCE, --distance DISTANCE
                        Node distance, default 200
  -L LABNAME, --labname LABNAME
                        Lab name to create, default "topogen lab"
  -T TEMPLATE, --template TEMPLATE
                        Template name to use, defaults to "iosv"
  --list-templates      List all available templates
  -m {nx,simple}, --mode {nx,simple}
                        mode of operation, default is "simple"

configuration:
  -c CONFIGFILE, --config CONFIGFILE
                        Use the configuration from this file, defaults to config.toml
  -w, --write           Write the default configuration to a file and exit
  -v, --version         show program's version number and exit
  -l LOGLEVEL, --loglevel LOGLEVEL
                        DEBUG, INFO, WARN, ERROR, CRITICAL, defaults to WARN
  -p, --progress        show a progress bar
$
```

At a minimum, the amount of nodes to be created must be provided.

#### Modes

There are two modes available right now:

- `nx`: this creates a partially meshed topology.  It also places nodes in clusters
  which is more pronounced with many nodes (>40).
- `simple` (which is the default): this creates a single string of nodes, laid out
  in a square / spiral pattern.

#### Templates

To list the available templates, use the `--list-templates` switch.  Currently,
only an IOSv template is provided.

To choose a specific template, provide the `--template=iosv` switch.

Currently, all router nodes are using the same template.

#### Other Configuration

IP address ranges are configured via a configuration file, if present.  The
defaults are like shown here:

```toml
loopbacks = "10.0.0.0/8"
p2pnets = "172.16.0.0/12"
nameserver = "8.8.8.8"
domainname = "virl.lab"
username = "cisco"
password = "cisco"
```

The username and password are used for the device configurations (e.g. the
Alpine DNS node and the generated routers).  The nameserver value is not used
at the moment (it is actually replaced with the IP address of the DNS host's
second interface / NIC facing the router network).

## Operation

The topology has an external connector and a DNS-host (based on Alpine).  On
that host, a dnsmasq DNS server is running which can resolve all IP addresses
of all topology router loopbacks.  All topology routers are also using this
DNS server (assuming they have connectivity to it).

> **Note:** Since the Alpine node does not include dnsmasq by default, it will pull in and
install this package from the Internet.  Therefore it is required to have Internet
connectivity for this to work!

Once the network has been created and full connectivity is established, it should
be possible to SSH/Telnet to all nodes using their node names:

```plain
$ telnet r1
Connecting to 10.0.0.2...
R1>
```
