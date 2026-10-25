{
  runCommand,
  bash,
  python3,
  shellcheck,
  findutils,
  ...
}:
runCommand "flake-cli-checks"
  {
    nativeBuildInputs = [
      bash
      python3
      shellcheck
      findutils
    ];
  }
  ''
    cd ${../..}
    shellcheck --shell=bash packages/flake/*.sh
    python3 tests/test_cli.py
    touch "$out"
  ''
