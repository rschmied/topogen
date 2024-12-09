# TopoGen for CML2

This package provides a `topogen` command which can create CML2 topologies.
It does this by using the PCL (VIRL Python Client Library) to talk to a live
controller, creating the lab, nodes and links on the fly.

![Demo](.images/demo.gif)

## Features

- create topologies of arbitrary size (up to 400 tested, this is N^2)
- can use templates to provide node configurations (currently a built-in
  DNS host template and an IOSv template exist)
- provide network numbering for all links (/30) and router loopbacks
- provide a DNS configuration so that all loopbacks and interface addresses can
  be resolved both from the DNS host as well as from all routers (provided the
  template configures DNS)
- provide a default route via DNS host, distributed via OSPF
- provide outbound NAT on the DNS host for the entire network

## Installation

> **Important** Ensure that the PCL you install is compatible with your controller.
If it doesn't work, then try installing the wheel with Pip manually. The wheel can
be downloaded from your controller at the `/client` location.

Steps:

1. clone this directory
2. create virtual environment in it `python3 -mvenv .venv`
3. activate the venv `source .venv/bin/activate` (or with
   .fish or .bat, ...)
4. install using `python3 -mpip install -e .`

Alternatively, use Astral/uv:

1. clone this directory
2. create the venv: `uv venv`
3. activate the venv `source .venv/bin/activate`
4. install using `uv sync --frozen`

At this point, the `topogen` command should be available.

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

For this to work, it's also required to have proper name resolution for the CML2
controller (e.g. add `192.168.254.123 cml-controller.cml.lab` with **the correct
IP** into your hosts file).

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
be possible to SSH/Telnet to all nodes using their node names.

The below shows logging into the Jumphost (at 192.168.255.100) via the controller
(at 192.168.122.245) and then onward to router `r1` using its name.

```plain
rschmied@delle:~/Projects/topogen$ ssh -tp1122 sysuser@192.168.122.245 ssh cisco@192.168.255.100
cisco@192.168.255.100's password: 
Welcome to Alpine!

The Alpine Wiki contains a large amount of how-to guides and general
information about administrating Alpine systems.
See <http://wiki.alpinelinux.org/>.

You can setup the system with the command: setup-alpine

You may change this message by editing /etc/motd.

dns-host:~$ telnet r1
Connected to r1

Entering character mode
Escape character is '^]'.


**************************************************************************
* IOSv is strictly limited to use for evaluation, demonstration and IOS  *
* education. IOSv is provided as-is and is not supported by Cisco's      *
* Technical Advisory Center. Any use or disclosure, in whole or in part, *
* of the IOSv Software or Documentation to any third party for any       *
* purposes is expressly prohibited except as otherwise authorized by     *
* Cisco in writing.                                                      *
**************************************************************************

User Access Verification

Username: cisco
Password: 
**************************************************************************
* IOSv is strictly limited to use for evaluation, demonstration and IOS  *
* education. IOSv is provided as-is and is not supported by Cisco's      *
* Technical Advisory Center. Any use or disclosure, in whole or in part, *
* of the IOSv Software or Documentation to any third party for any       *
* purposes is expressly prohibited except as otherwise authorized by     *
* Cisco in writing.                                                      *
**************************************************************************
R1#traceroute 192.168.122.1
Type escape sequence to abort.
Tracing the route to 192.168.122.1
VRF info: (vrf in name/id, vrf out name/id)
  1 from-r1-gi0-0-to-r9-gi0-0.virl.lab (172.16.0.2) 3 msec
    from-r1-gi0-1-to-r2-gi0-0.virl.lab (172.16.0.6) 9 msec
    from-r1-gi0-2-to-r4-gi0-0.virl.lab (172.16.0.10) 4 msec
  2 from-r7-gi0-4-to-r9-gi0-2.virl.lab (172.16.0.57) 10 msec
    from-r2-gi0-3-to-r7-gi0-0.virl.lab (172.16.0.22) 18 msec
    from-r4-gi0-2-to-r7-gi0-2.virl.lab (172.16.0.38) 14 msec
  3 172.16.0.77 7 msec 10 msec 11 msec
  4 192.168.255.1 11 msec 14 msec 9 msec
  5 192.168.122.1 13 msec 12 msec 11 msec
R1#
```
