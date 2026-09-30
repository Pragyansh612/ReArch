import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="analyzer")
    parser.add_argument("repo")
    parser.add_argument("--out", default="out/")
    parser.parse_args()
    raise SystemExit("analyzer not implemented yet (Phase 2)")


if __name__ == "__main__":
    main()
