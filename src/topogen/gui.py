"""
File Chain (see DEVELOPER.md):
Doc Version: v1.0.1
Date Modified: 2026-02-16

- Called by: topogen-gui console script
- Purpose: Optional Gooey-based GUI wrapper for topogen CLI

TopoGen GUI Launcher - Gooey-Based Graphical User Interface

PURPOSE:
    Provides optional GUI wrapper for topogen using Gooey framework.
    Wraps the same CLI argument parser with a graphical form interface
    for users who prefer GUI over command-line interaction.

WHO READS ME:
    - Users: via command `topogen-gui`
    - Entry point: topogen[gui] extra installation

WHO I READ:
    - main.py: create_argparser() to build GUI from CLI parser
    - models.py: TopogenError for exception handling

DEPENDENCIES:
    - gooey: Gooey decorator, GooeyParser (optional dependency)
    - sys: System operations

KEY EXPORTS:
    - main(): Entry point for GUI application

INSTALLATION:
    pip install 'topogen[gui]'

FEATURES:
    - Automatic form generation from argparse parser
    - File choosers for YAML paths
    - Dropdown menus for templates and device types
    - Clear before run, no success/failure modals
    - Reuses entire CLI argument structure

BEHAVIOR:
    - If Gooey not installed, prints error and exits
    - Calls main.main() with parsed arguments
    - Returns exit code from main application
"""

from __future__ import annotations

import sys


def main() -> int:
    """Entry point for the optional Gooey GUI.

    Uses Gooey's GooeyParser to build the same argparse UI as the CLI.
    """

    try:
        from gooey import Gooey, GooeyParser  # type: ignore
    except Exception:
        print(
            "Gooey is not installed. Install with: pip install 'topogen[gui]'",
            file=sys.stderr,
        )
        return 1

    # Late imports so CLI use doesn't require Gooey.
    from topogen.main import create_argparser
    from topogen.models import TopogenError

    @Gooey(
        program_name="topogen",
        show_success_modal=False,
        show_failure_modal=False,
        clear_before_run=True,
    )
    def _run() -> int:
        parser = create_argparser(parser_class=GooeyParser)
        args = parser.parse_args()

        def _replace_flag(argv: list[str], flags: tuple[str, ...], value: str) -> list[str]:
            argv = list(argv)
            for flag in flags:
                if flag in argv:
                    idx = argv.index(flag)
                    if idx + 1 < len(argv):
                        argv[idx + 1] = value
                    else:
                        argv.append(value)
                    return argv
            argv.extend([flags[0], value])
            return argv

        if getattr(args, "labname", None) == "topogen lab":
            mode = getattr(args, "mode", "")
            nodes = getattr(args, "nodes", None)
            if mode == "dmvpn" and nodes:
                dev_template = str(getattr(args, "dev_template", "")).strip().lower()
                platform = "IOSXE" if dev_template == "csr1000v" else dev_template.upper() if dev_template else "CML"
                phase = int(getattr(args, "dmvpn_phase", 2))
                routing = str(getattr(args, "dmvpn_routing", "eigrp")).upper()
                hubs_raw = getattr(args, "dmvpn_hubs", None)
                if hubs_raw:
                    hubs = [p.strip() for p in str(hubs_raw).split(",") if p.strip()]
                    hcount = len(hubs)
                    suggested = f"{platform}-DMVPN-{hcount}H-P{phase}-{routing}-N{int(nodes)}"
                else:
                    suggested = f"{platform}-DMVPN-P{phase}-{routing}-N{int(nodes)}"
                sys.argv = _replace_flag(sys.argv, ("-L", "--labname"), suggested)

        # Reuse the existing CLI logic by invoking topogen.main.main().
        # Easiest approach: temporarily replace sys.argv with the parsed args.
        # But argparse doesn't expose a clean round-trip; instead we call
        # topogen.main.main() directly with the already-parsed Namespace.
        # For MVP, we re-run parsing in main() by rebuilding argv.
        # This keeps behavior identical to the CLI.
        #
        # NOTE: Gooey already parsed args from sys.argv, so this argv rebuild
        # is mostly for internal consistency.
        from topogen.main import main as cli_main

        try:
            # cli_main parses sys.argv; Gooey injects args there already.
            return int(cli_main())
        except TopogenError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    return int(_run())


if __name__ == "__main__":
    raise SystemExit(main())
