import argparse
import logging
import os
import sys

import topogen
from topogen.models import TopogenError
from topogen.render import Renderer, get_templates
from topogen.colorlog import CustomFormatter

_LOGGER = logging.getLogger(__name__)


def create_argparser():
    parser = argparse.ArgumentParser(
        prog=topogen.__name__, description=topogen.__description__
    )
    config_settings = parser.add_argument_group("configuration")

    config_settings.add_argument(
        "-c",
        "--config",
        dest="configfile",
        help="Use the configuration from this file, defaults to %(default)s",
        default="config.toml",
    )
    config_settings.add_argument(
        "-w",
        "--write",
        dest="writeconfig",
        action="store_true",
        help="Write the default configuration to a file and exit",
        default=False,
    )
    config_settings.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {topogen.__version__}"
    )
    config_settings.add_argument(
        "-l",
        "--loglevel",
        type=str,
        default=os.environ.get("LOG_LEVEL", "WARN"),
        help="DEBUG, INFO, WARN, ERROR, CRITICAL, defaults to %(default)s",
    )
    config_settings.add_argument(
        "-p",
        "--progress",
        action="store_true",
        help="show a progress bar",
    )

    parser.add_argument(
        "--ca",
        dest="cafile",
        help="Use the CA certificate from this file (PEM format), defaults to %(default)s",
        default="ca.pem",
    )
    parser.add_argument(
        "-i",
        "--insecure",
        action="store_true",
        help="If no CA provided, do not verify TLS (insecure!)",
        default=False,
    )
    parser.add_argument(
        "-d",
        "--distance",
        type=int,
        default=200,
        help="Node distance, default %(default)d",
    )
    parser.add_argument(
        "-L",
        "--labname",
        type=str,
        default="topogen lab",
        help='Lab name to create, default "%(default)s"',
    )
    parser.add_argument(
        "-T",
        "--template",
        type=str,
        help='Template name to use, defaults to "%(default)s"',
        default="iosv",
    )
    parser.add_argument(
        "--list-templates",
        dest="listtemplates",
        action="store_true",
        help="List all available templates",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=("nx", "simple"),
        default="simple",
        help='mode of operation, default is "%(default)s"',
    )
    parser.add_argument(
        "nodes", nargs="?", type=int, help="Number of nodes to generate"
    )
    return parser


def setup_logging(loglevel: str):
    logging.basicConfig(level=logging.WARN)
    level = logging.getLevelName(loglevel.upper())
    unknown_loglevel = False
    if isinstance(level, str) and level.startswith("Level"):
        unknown_loglevel = True
        level = logging.WARN
    logging.root.setLevel(level)
    cf = CustomFormatter()
    for handler in logging.root.handlers:
        handler.setFormatter(cf)
    if unknown_loglevel:
        _LOGGER.warning("Unknown log level: %s", level)


def main():
    parser = create_argparser()
    args = parser.parse_args()
    setup_logging(args.loglevel)

    cfg = topogen.Config.load(args.configfile)
    if args.writeconfig:
        cfg.save(args.configfile)
        return 0

    if args.listtemplates:
        print("Available templates: ", ", ".join(get_templates()))
        return 0

    try:
        r = Renderer(args, cfg)
        # argparse ensures correct mode
        if args.mode == "simple":
            retval = r.render_node_sequence()
        else:  # args.mode == "nx":
            retval = r.render_node_network()
    except TopogenError as exc:
        _LOGGER.error(exc)
        retval = 1
    return retval


if __name__ == "__main__":
    sys.exit(main())
