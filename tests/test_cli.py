from mempalace.cli import build_parser


def test_init_defaults_to_current_directory():
    parser = build_parser()

    args = parser.parse_args(["init"])

    assert args.command == "init"
    assert args.dir == "."
    assert args.yes is False


def test_init_accepts_explicit_directory():
    parser = build_parser()

    args = parser.parse_args(["init", "~/projects/demo", "--yes"])

    assert args.command == "init"
    assert args.dir == "~/projects/demo"
    assert args.yes is True
