# fluxsim/cli.py
from typing import Any, cast

from riposte import Riposte

from . import commands as _commands

BANNER = r"""
Network Behavior Simulator (Flux, LB, CDN, Static)
███████╗██╗     ██╗   ██╗██╗  ██╗██╗      █████╗ ██████╗ 
██╔════╝██║     ██║   ██║╚██╗██╔╝██║     ██╔══██╗██╔══██╗
█████╗  ██║     ██║   ██║ ╚███╔╝ ██║     ███████║██████╔╝
██╔══╝  ██║     ██║   ██║ ██╔██╗ ██║     ██╔══██║██╔══██╗
██║     ███████╗╚██████╔╝██╔╝ ██╗███████╗██║  ██║██████╔╝
╚═╝     ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝ 
                                         By Leslie Etubo
Codename   : Catch Me If You Can
Version    : 0.1.0
Homepage   : https://www.logstr.io - @lesliexyz
"""

# We print the banner ourselves to avoid duplicates across Riposte versions.
cli = Riposte(prompt="FluxLab:~ ", banner=BANNER)
_HELP = cast(dict[str, dict[str, Any]], _commands.register(cli))  # rich metadata


# ---- base utilities ----
@cli.command("exit", "Exit.")
def _do_exit():
    import sys

    sys.exit(0)


@cli.command("quit", "Exit.")
def _do_quit():
    import sys

    sys.exit(0)


@cli.command("clear", "Clear the console screen.")
def _cmd_clear():
    import os

    os.system("cls" if os.name == "nt" else "clear")


@cli.command("cls", "Clear the console screen (alias).")
def _cmd_cls():
    import os

    os.system("cls" if os.name == "nt" else "clear")


# ---- help commands ----
def _print_topic(name: str):
    meta = _HELP.get(name)
    if not meta:
        cli.error(f"Unknown command: {name}")
        return
    cli.print(f"\n{name}")
    cli.print("-" * len(name))
    cli.print(f"Description: {meta['desc']}")
    cli.print(f"Usage:       {meta['usage']}")
    if meta.get("long"):
        cli.print("\nDetails:")
        for line in str(meta["long"]).splitlines():
            cli.print(f"  {line}")
    if meta.get("examples"):
        cli.print("\nExamples:")
        for ex in meta["examples"]:
            cli.print(f"  {ex}")
    cli.print("")


def _print_index():
    cli.print("\nCommands:")
    # group by category
    groups: dict[str, list[dict[str, Any]]] = {}
    for meta in _HELP.values():
        group_name = str(meta.get("group", "General"))
        groups.setdefault(group_name, []).append(dict(meta))
    for group, metas in sorted(groups.items()):
        cli.print(f"\n{group}:")
        for meta in sorted(metas, key=lambda m: str(m["name"])):
            cli.print(f"  {meta['name']:<18} {meta['desc']}")
    cli.print("\nTip: type 'help <command>' for details.\n")


@cli.command("help", "Show available commands or details for a specific command.")
def _help(*args):
    if len(args) == 0:
        _print_index()
    elif len(args) == 1:
        _print_topic(args[0])
    else:
        cli.error("Usage: help [command]")


# aliases
@cli.command("?", "Alias for help.")
def _help_alias(*args):
    _help(*args)


@cli.command("h", "Alias for help.")
def _h_alias(*args):
    _help(*args)


@cli.command("--help", "Alias for help.")
def _dash_help_alias(*args):
    _help(*args)


@cli.command("doctor", "Diagnose state singletons & import paths.")
def doctor():
    import sys

    import fluxsim.compose_gen as compose_gen
    import fluxsim.deploy as deploy
    import fluxsim.state as state

    cli.print(f"python: {sys.executable}")
    cli.print(f"state module:   {state.__file__}")
    cli.print(f"deploy module:  {deploy.__file__}")
    cli.print(f"compose module: {compose_gen.__file__}")
    cli.print(
        "NETWORKS ids:   "
        f"state={id(state.NETWORKS)} deploy={id(deploy.NETWORKS)} compose={id(compose_gen.NETWORKS)}"
    )
    cli.print(
        "NETWORKS sizes: "
        f"state={len(state.NETWORKS)} deploy={len(deploy.NETWORKS)} compose={len(compose_gen.NETWORKS)}"
    )


def main():
    print("Type 'help' for commands.")
    print("-------------------------------------")
    cli.run()
