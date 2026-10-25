{
  runCommand,
  bash,
  python3,
  shellcheck,
  findutils,
  jq,
  zsh,
  ...
}:
runCommand "flake-cli-checks"
  {
    nativeBuildInputs = [
      bash
      python3
      shellcheck
      findutils
      jq
      zsh
    ];
  }
  ''
    cd ${../..}
    shellcheck --shell=bash packages/flake/*.sh
    zsh -n packages/flake/_flake
    python3 tests/test_cli.py
    touch "$out"
  ''
