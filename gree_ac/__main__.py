import argparse


def main():
    parser = argparse.ArgumentParser(description="Gree AC Controller for Ubuntu")
    commands = parser.add_subparsers(dest="command", required=True)
    service = commands.add_parser("service", help="Run the background D-Bus service")
    service.add_argument("--demo", action="store_true", help="Simulate two ACs without network traffic")
    service.add_argument("--config", help="Override the device configuration file")
    desktop = commands.add_parser("desktop", help="Run the desktop window and top-bar menu")
    desktop.add_argument("--indicator", action="store_true", help="Start with the window hidden")
    desktop.add_argument("--quit", action="store_true", help="Close the desktop app; keep the service running")
    args = parser.parse_args()
    if args.command == "service":
        from .service import main as run_service
        run_service(config=args.config, demo=args.demo)
    else:
        from .desktop import main as run_desktop
        run_desktop(indicator=args.indicator, quit_app=args.quit)


if __name__ == "__main__":
    main()
