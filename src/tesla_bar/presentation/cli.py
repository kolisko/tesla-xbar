"""CLI input/output adapter. Application work is delegated to the supplied service."""
import argparse
import sys
from ..application.ports import Request


def parse_request(argv=None):
    parser = argparse.ArgumentParser(description="Tesla xBar")
    parser.add_argument("command", nargs="?", default="menu", choices=["menu", "refresh", "wake-refresh", "command", "command-setup", "configure", "provision", "register", "authorize", "location-enable", "location-disable", "map-enable", "map-disable", "select", "display", "demo"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--vin", help="Vehicle bound to the clicked menu item")
    parser.add_argument("--temperature", help="Target Celsius temperature for climate-set-temp")
    parser.add_argument("--no-browser", action="store_true")
    return Request(**vars(parser.parse_args(argv)))


def run(service, present, argv=None):
    result = service.handle(parse_request(argv))
    for message in result.messages:
        print(message)
    if result.cache is not None:
        print(present(result))
    if result.error:
        print(result.error, file=sys.stderr)
        return 1
    return 0
