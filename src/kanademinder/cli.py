"""CLI entry point — argparse routing for all subcommands."""

from __future__ import annotations

import argparse
import sys

from kanademinder.config import DB_PATH, load_config, write_default_config
from kanademinder.db import open_db
from kanademinder.llm.client import LLMClient


def _make_llm(cfg, *, debug: bool = False) -> LLMClient:
    return LLMClient(
        base_url=cfg.llm.base_url,
        api_key=cfg.llm.api_key,
        model=cfg.llm.model,
        provider=cfg.llm.provider or None,  # None = auto-detect
        debug=debug,
    )


def cmd_chat(args: argparse.Namespace) -> None:
    from kanademinder.app.chat.display import make_error_handler, make_response_renderer, make_turn_handler
    from kanademinder.chat.repl import run_repl

    cfg = load_config()
    conn = open_db(DB_PATH)
    llm = _make_llm(cfg, debug=args.debug)
    try:
        run_repl(
            make_turn_handler(llm, conn, cfg.behavior.default_task_type),
            response_renderer=make_response_renderer(conn),
            error_handler=make_error_handler(),
            welcome="[bold cyan]KanadeMinder[/bold cyan] - type your task or question. Ctrl-C to exit.\n",
        )
    finally:
        conn.close()


def cmd_daemon(args: argparse.Namespace) -> None:
    from kanademinder.daemon.scheduler import run_tick
    from kanademinder.app.daemon.scheduler import make_kanademinder_tick

    cfg = load_config()
    conn = open_db(DB_PATH)
    llm = _make_llm(cfg, debug=args.debug)
    try:
        run_tick(
            make_kanademinder_tick(
                llm,
                conn,
                end_of_day=cfg.schedule.end_of_day,
                notification_mode=cfg.behavior.notification_mode,
            ),
            start_of_day=cfg.schedule.start_of_day,
            end_of_day=cfg.schedule.end_of_day,
            force=args.force,
        )
    finally:
        conn.close()


def _print_windows_setup_guide(interval_minutes: int) -> None:
    print(
        "KanadeMinder daemon setup — Windows\n"
        "====================================\n"
        "To avoid triggering security software, please register the daemon\n"
        "manually using Windows Task Scheduler:\n"
        "\n"
        "  1. Open Task Scheduler (taskschd.msc).\n"
        "  2. Click 'Create Basic Task' in the Actions pane.\n"
        "  3. Name it 'KanadeMinder' and click Next.\n"
        "  4. Set the trigger to 'Daily', then configure a 'Repeat task every'\n"
        f"     interval of {interval_minutes} minutes for a duration of '1 day'.\n"
        "  5. Choose 'Start a program', then browse to the kanademinder\n"
        "     executable (e.g. .venv\\Scripts\\kanademinder.exe).\n"
        "  6. Add the argument:  daemon\n"
        "  7. Finish and confirm.\n"
        "\n"
        "To remove the task, open Task Scheduler and delete 'KanadeMinder'."
    )


def _print_linux_setup_guide(interval_minutes: int) -> None:
    print(
        f"KanadeMinder daemon setup — Linux\n"
        f"==================================\n"
        f"Choose whichever method suits your setup:\n"
        f"\n"
        f"Option A — systemd user service (recommended):\n"
        f"  Create ~/.config/systemd/user/kanademinder.service:\n"
        f"\n"
        f"    [Unit]\n"
        f"    Description=KanadeMinder scheduler\n"
        f"\n"
        f"    [Service]\n"
        f"    ExecStart=/path/to/kanademinder daemon\n"
        f"    Restart=no\n"
        f"\n"
        f"  Create ~/.config/systemd/user/kanademinder.timer:\n"
        f"\n"
        f"    [Unit]\n"
        f"    Description=Run KanadeMinder every {interval_minutes} minutes\n"
        f"\n"
        f"    [Timer]\n"
        f"    OnBootSec=1min\n"
        f"    OnUnitActiveSec={interval_minutes}min\n"
        f"\n"
        f"    [Install]\n"
        f"    WantedBy=timers.target\n"
        f"\n"
        f"  Then enable:\n"
        f"    systemctl --user enable --now kanademinder.timer\n"
        f"\n"
        f"Option B — cron:\n"
        f"  Add this line via 'crontab -e':\n"
        f"    */{interval_minutes} * * * * /path/to/kanademinder daemon\n"
        f"\n"
        f"To remove: disable the timer/service or delete the cron entry."
    )


def cmd_install(args: argparse.Namespace) -> None:
    cfg = load_config()
    interval = cfg.schedule.interval_minutes

    if sys.platform == "win32":
        _print_windows_setup_guide(interval)
        return

    if sys.platform != "darwin":
        _print_linux_setup_guide(interval)
        return

    # macOS — toggle install/uninstall via launchd
    from kanademinder.app.daemon.launchd import install_daemon, is_installed, uninstall_daemon

    if is_installed():
        uninstall_daemon()
        print("KanadeMinder daemon uninstalled.")
    else:
        install_daemon(interval_minutes=interval)
        print(f"KanadeMinder daemon installed (runs every {interval} minutes).")


def cmd_web(args: argparse.Namespace) -> None:
    from kanademinder.app.web.router import make_web_router
    from kanademinder.web.server import run_server

    cfg = load_config()
    llm = _make_llm(cfg, debug=args.debug)
    router = make_web_router(llm, lambda: open_db(DB_PATH))
    run_server(router, host=args.host, port=args.port)


def cmd_gui(args: argparse.Namespace) -> None:
    """Launch the native desktop GUI using pywebview."""
    from kanademinder.gui.app import main as gui_main

    gui_main()


def cmd_config_init(args: argparse.Namespace) -> None:
    written = write_default_config()
    if written:
        from kanademinder.config import CONFIG_PATH
        print(f"Config written to {CONFIG_PATH}")
        print("Edit the [llm] section to add your API key.")
    else:
        from kanademinder.config import CONFIG_PATH
        print(f"Config already exists at {CONFIG_PATH}")


def cmd_config_setup(args: argparse.Namespace) -> None:
    from kanademinder.app.config.setup import run_setup
    from kanademinder.config import CONFIG_PATH
    try:
        run_setup(CONFIG_PATH)
    except KeyboardInterrupt:
        print("\nSetup cancelled.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kanademinder",
        description="Conversational task management with LLM-powered scheduling nudges.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable verbose HTTP logging.")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # chat
    chat_p = sub.add_parser("chat", help="Start the conversational REPL.")
    chat_p.set_defaults(func=cmd_chat)

    # daemon
    daemon_p = sub.add_parser("daemon", help="Run one scheduler tick (called by launchd).")
    daemon_p.add_argument("--force", action="store_true", help="Skip EOD suppression and run regardless of time.")
    daemon_p.set_defaults(func=cmd_daemon)

    # web
    web_p = sub.add_parser("web", help="Start the web frontend server.")
    web_p.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1).")
    web_p.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080).")
    web_p.set_defaults(func=cmd_web)

    # gui
    gui_p = sub.add_parser("gui", help="Launch the native desktop GUI.")
    gui_p.set_defaults(func=cmd_gui)

    # install (toggle: installs if absent, uninstalls if present; shows guide on non-macOS)
    install_p = sub.add_parser(
        "install",
        help="Toggle daemon registration (macOS: launchd; Windows/Linux: setup guide).",
    )
    install_p.set_defaults(func=cmd_install)

    # config init
    config_p = sub.add_parser("config", help="Config management.")
    config_sub = config_p.add_subparsers(dest="config_command", metavar="ACTION")
    config_sub.required = True
    config_init_p = config_sub.add_parser("init", help="Write default config.toml if absent.")
    config_init_p.set_defaults(func=cmd_config_init)

    config_setup_p = config_sub.add_parser("setup", help="Interactive setup wizard.")
    config_setup_p.set_defaults(func=cmd_config_setup)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_usage()
        print(
            "\nAvailable commands:\n"
            "  chat          Start the conversational REPL\n"
            "  web           Start the web frontend server\n"
            "  gui           Launch the native desktop GUI\n"
            "  install       Toggle daemon registration\n"
            "  config init   Write default config.toml\n"
            "  config setup  Interactive setup wizard\n"
            "\nRun 'kanademinder <command> --help' for details on a specific command."
        )
        sys.exit(0)
    # Propagate --debug to subcommands that don't have their own namespace
    if not hasattr(args, "debug"):
        args.debug = False
    args.func(args)
