"""Real Nix/Gum terminal tests against disposable flakes; no system activation.

Run outside a Nix build sandbox, with access to a Nix store/daemon:
  python3 tests/test_interactive.py --cli /nix/store/...-flake/bin/flake \
      --nixpkgs /nix/store/...-source
"""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest
from urllib.parse import quote

CSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
OSC = re.compile(r'\x1b\][^\x07]*(?:\x07|\x1b\\)')


class Terminal:
    def __init__(self, args, cwd):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(cwd)
            os.execvpe(args[0], args, dict(os.environ, TERM='xterm-256color'))
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
        self.output = ''
        self.cursor = 0
        self.eof = False
        self.status = None

    def read(self, timeout):
        if self.eof or not select.select([self.fd], [], [], timeout)[0]:
            return
        try:
            data = os.read(self.fd, 65536)
        except OSError as error:
            if error.errno != errno.EIO:
                raise
            data = b''
        if not data:
            self.eof = True
        else:
            self.output += data.decode('utf-8', errors='replace')

    def expect(self, text, timeout=60):
        deadline = time.monotonic() + timeout
        while text not in self.output[self.cursor:]:
            if self.eof or time.monotonic() > deadline:
                raise AssertionError(f'Expected {text!r}; terminal output:\n{self.clean()}')
            self.read(0.1)
        self.cursor = self.output.index(text, self.cursor) + len(text)

    def send(self, keys):
        self.cursor = len(self.output)
        os.write(self.fd, keys.encode())

    def finish(self, timeout=60):
        deadline = time.monotonic() + timeout
        while not self.eof and time.monotonic() < deadline:
            self.read(0.1)
        if not self.eof:
            raise AssertionError('Terminal did not exit:\n' + self.clean())
        _, status = os.waitpid(self.pid, 0)
        self.status = os.waitstatus_to_exitcode(status)
        return self.status

    def clean(self):
        return CSI.sub('', OSC.sub('', self.output)).replace('\r', '')

    def close(self):
        if self.status is None:
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            os.waitpid(self.pid, 0)
        os.close(self.fd)


class Interactive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='snowfall-pty-')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.system = subprocess.check_output(['nix', 'eval', '--impure', '--raw', '--expr', 'builtins.currentSystem'], text=True)
        cls.fixture = cls.root / 'project with spaces'
        cls.fixture.mkdir()
        for name in ['alpha', 'beta']:
            directory = cls.root / name
            directory.mkdir()
            (directory / 'flake.nix').write_text('{ outputs = { self }: { marker = "old"; }; }')
        fixture = r'''
{
  inputs.nixpkgs.url = "@NIXPKGS@";
  inputs.alpha.url = "@ALPHA@";
  inputs.beta.url = "@BETA@";
  outputs = { self, nixpkgs, alpha, beta }:
    let
      pkgs = import nixpkgs { system = builtins.currentSystem; };
      system = "@SYSTEM@";
      app = name: {
        type = "app";
        program = toString (pkgs.writeShellScript "pty-${name}" ''
          printf 'APP_${name}\n'
          printf '<%s>\n' "$@"
        '');
      };
      demo = pkgs.lib.evalModules { modules = [{
        options.demo.message = pkgs.lib.mkOption {
          type = pkgs.lib.types.str;
          default = "INTERACTIVE_OPTION_OK";
          description = "Disposable option for terminal testing.";
        };
      }]; };
    in {
      apps.${system} = { alpha = app "ALPHA"; beta = app "BETA"; };
      packages.${system} = {
        alpha = pkgs.writeText "pty-alpha" "BUILT_ALPHA";
        beta = pkgs.writeText "pty-beta" "BUILT_BETA";
      };
      checks.${system} = {
        alpha = pkgs.writeText "pty-check-alpha" "CHECK_ALPHA_@UNIQUE@";
        beta = pkgs.writeText "pty-check-beta" "CHECK_BETA_@UNIQUE@";
      };
      devShells.${system}.default = pkgs.mkShellNoCC { shellHook = "echo SHELL_ACTIVE"; };
      nixosConfigurations.demo = { inherit pkgs; inherit (demo) config options; };
    };
}
'''
        system = cls.system
        # Use an explicit system so nix run/build can evaluate the fixture purely.
        fixture = fixture.replace('system = builtins.currentSystem;', f'system = "{system}";')
        for key, value in {'NIXPKGS': ARGS.nixpkgs, 'ALPHA': cls.root / 'alpha', 'BETA': cls.root / 'beta'}.items():
            fixture = fixture.replace('@' + key + '@', 'path:' + quote(str(value)))
        (cls.fixture / 'flake.nix').write_text(fixture.replace('@SYSTEM@', system).replace('@UNIQUE@', str(cls.root)))
        for command in [['git', 'init', '-q'], ['git', 'add', 'flake.nix'], ['nix', 'flake', 'lock'], ['git', 'add', 'flake.lock']]:
            subprocess.run(command, cwd=cls.fixture, check=True, capture_output=True, text=True)

    def terminal(self, *args):
        terminal = Terminal([ARGS.cli, *args], self.fixture)
        self.addCleanup(terminal.close)
        return terminal

    def test_app_selection_and_arguments(self):
        terminal = self.terminal('run', '--pick', '--', 'two words', '', '*')
        terminal.expect('enter submit')
        terminal.send('\x1b[B\r')
        self.assertEqual(terminal.finish(), 0, terminal.clean())
        self.assertIn('APP_BETA\n<two words>\n<>\n<*>', terminal.clean())

    def test_package_selection(self):
        terminal = self.terminal('build', '--pick')
        terminal.expect('enter submit')
        terminal.send('\x1b[B\r')
        self.assertEqual(terminal.finish(), 0, terminal.clean())
        self.assertEqual((self.fixture / 'result').read_text(), 'BUILT_BETA')

    def test_cancellation(self):
        terminal = self.terminal('build', '--pick')
        terminal.expect('enter submit')
        terminal.send('\x03')
        self.assertEqual(terminal.finish(), 130, terminal.clean())
        self.assertNotIn('Building package', terminal.clean())

    def test_selected_check(self):
        output = subprocess.check_output(['nix', 'eval', '--raw', f'.#checks.{self.system}.beta.outPath'], cwd=self.fixture, text=True, stderr=subprocess.DEVNULL)
        terminal = self.terminal('check', '--pick')
        terminal.expect('enter submit')
        self.assertIn('.#alpha', terminal.clean())
        self.assertIn('.#beta', terminal.clean())
        terminal.send('\x1b[B\r')
        self.assertEqual(terminal.finish(), 0, terminal.clean())
        self.assertTrue(Path(output).exists(), 'the selected check was not built')
        self.assertTrue(Path(output).read_text().startswith('CHECK_BETA_'))

    def test_option_navigation_and_back(self):
        terminal = self.terminal('option', '--pick')
        terminal.expect('enter submit')
        terminal.send('\r')  # host
        terminal.expect('enter submit')
        terminal.send('\r')  # demo group
        terminal.expect('enter submit')
        terminal.send('\x1b[B\r')  # message, after Back
        terminal.expect('INTERACTIVE_OPTION_OK')
        terminal.send('q')  # close pager
        terminal.expect('enter submit')
        terminal.send('\r')  # Back to root
        terminal.expect('enter submit')
        terminal.send('\x03')
        self.assertEqual(terminal.finish(), 130, terminal.clean())

    def test_multi_input_update(self):
        before = json.loads((self.fixture / 'flake.lock').read_text())['nodes']
        for name in ['alpha', 'beta']:
            p = self.root / name / 'flake.nix'
            p.write_text(p.read_text().replace('old', 'updated'))
        terminal = self.terminal('update', '--pick')
        terminal.expect('enter submit')
        terminal.send(' \x1b[B \r')
        self.assertEqual(terminal.finish(), 0, terminal.clean())
        after = json.loads((self.fixture / 'flake.lock').read_text())['nodes']
        for name in ['alpha', 'beta']:
            self.assertNotEqual(before[name]['locked'], after[name]['locked'])
        self.assertEqual(before['nixpkgs']['locked'], after['nixpkgs']['locked'])

    def test_development_shell(self):
        terminal = self.terminal('dev', '--pick')
        terminal.expect('enter submit')
        terminal.send('\r')
        terminal.expect('SHELL_ACTIVE')
        terminal.send("printf 'SHELL_COMMAND_OK\\n'\nexit\n")
        self.assertEqual(terminal.finish(), 0, terminal.clean())
        self.assertIn('SHELL_COMMAND_OK', terminal.clean())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', required=True)
    parser.add_argument('--nixpkgs', required=True)
    ARGS, remainder = parser.parse_known_args()
    unittest.main(argv=[__file__, *remainder], verbosity=2)
