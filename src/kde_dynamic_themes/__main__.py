"""Launch GUI or perform a side-effect-free compatibility diagnosis."""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(prog='kde-dynamic-themes')
    parser.add_argument('--doctor', action='store_true', help='Read-only distro/Plasma compatibility report')
    parser.add_argument('--version', action='store_true', help='Print installed version')
    args = parser.parse_args()
    if args.version:
        from . import __version__
        print(__version__)
        return 0
    if args.doctor:
        from .platform import diagnostic
        print(json.dumps(diagnostic(), indent=2, ensure_ascii=False))
        return 0
    from .ui import main as start
    return start()


if __name__ == '__main__':
    raise SystemExit(main())
