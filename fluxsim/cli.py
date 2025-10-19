# fluxsim/cli.py
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
_HELP = _commands.register(cli)  # rich metadata

# ---- base utilities ----
@cli.command("exit","Exit.")
def _do_exit():
    import sys; sys.exit(0)

@cli.command("quit","Exit.")
def _do_quit():
    import sys; sys.exit(0)

@cli.command("clear","Clear the console screen.")
def _cmd_clear():
    import os; os.system('cls' if os.name == 'nt' else 'clear')

@cli.command("cls","Clear the console screen (alias).")
def _cmd_cls():
    import os; os.system('cls' if os.name == 'nt' else 'clear')

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
    groups = {}
    for meta in _HELP.values():
        groups.setdefault(meta.get("group","General"), []).append(meta)
    for group in sorted(groups):
        cli.print(f"\n{group}:")
        for meta in sorted(groups[group], key=lambda m: m["name"]):
            cli.print(f"  {meta['name']:<18} {meta['desc']}")
    cli.print("\nTip: type 'help <command>' for details.\n")

@cli.command("help","Show available commands or details for a specific command.")
def _help(*args):
    if len(args) == 0:
        _print_index()
    elif len(args) == 1:
        _print_topic(args[0])
    else:
        cli.error("Usage: help [command]")

# aliases
@cli.command("?","Alias for help.")
def _help_alias(*args): _help(*args)

@cli.command("h","Alias for help.")
def _h_alias(*args): _help(*args)

@cli.command("--help","Alias for help.")
def _dash_help_alias(*args): _help(*args)

@cli.command("doctor", "Diagnose state singletons & import paths.")
def doctor():
    import sys, fluxsim.state as S, fluxsim.deploy as D, fluxsim.compose_gen as G
    cli.print(f"python: {sys.executable}")
    cli.print(f"state module:   {S.__file__}")
    cli.print(f"deploy module:  {D.__file__}")
    cli.print(f"compose module: {G.__file__}")
    cli.print(f"NETWORKS ids:   state={id(S.NETWORKS)} deploy={id(D.NETWORKS)} compose={id(G.NETWORKS)}")
    cli.print(f"NETWORKS sizes: state={len(S.NETWORKS)} deploy={len(D.NETWORKS)} compose={len(G.NETWORKS)}")

def main():
    print("Type 'help' for commands.")
    print("-------------------------------------")
    cli.run()
