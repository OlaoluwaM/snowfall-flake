"""Exercise the packaged completion through a real Zsh line editor and Tab key."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import tempfile
import unittest

from test_interactive import Terminal


class Completion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='flake completion ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'flake.nix').write_text('{}')
        self.lock = self.root / 'flake.lock'
        self.lock.write_text(json.dumps({
            'root': 'project',
            'nodes': {
                'project': {'inputs': {
                    'alpha': 'alpha-node', 'beta': 'beta-node',
                    'alias': ['alpha'],
                }},
                'alpha-node': {'inputs': {'transitive': 'hidden'}},
            },
        }))
        self.original_lock = self.lock.read_bytes()
        self.terminal = Terminal(['zsh', '-f'], self.root)
        self.addCleanup(self.close_terminal)
        # Pass the package location as data, and load the installed #compdef
        # through compinit exactly as a user's shell would.
        os.write(self.terminal.fd, (
            'fpath=("$SNOWFALL_COMPLETION_DIR" $fpath); '
            'autoload -Uz compinit; compinit -D; '
            "PROMPT='READ''Y> '; RPROMPT=; bindkey -e; "
            "capture() { print -r -- \"CAPTURE<$BUFFER>\"; BUFFER=; zle reset-prompt; }; "
            "zle -N capture; bindkey '^X^B' capture; "
            "nix() { print NIX_MUST_NOT_RUN; return 1; }; "
            # Split the readiness marker so the PTY's echo of this command
            # cannot satisfy expect() before Zsh has executed the setup.
            "print INIT''IALIZED\n"
        ).encode())
        self.terminal.expect('INITIALIZED\r\n')
        self.terminal.expect('READY> ')

    def close_terminal(self):
        # Interactive Zsh ignores SIGTERM; ask it to exit before the shared
        # terminal helper reaps it, with a bounded fallback on test failure.
        try:
            self.terminal.send('\x03\x15exit\n')
            self.terminal.finish(timeout=5)
        finally:
            if self.terminal.status is None:
                os.killpg(self.terminal.pid, signal.SIGKILL)
            self.terminal.close()

    def complete(self, command, tabs=1):
        terminal = self.terminal
        start = len(terminal.output)
        terminal.send(command + '\t' * tabs)
        terminal.read(0.2)
        terminal.send('\x18\x02')
        terminal.expect('CAPTURE<')
        terminal.expect('>')
        output = terminal.output[start:]
        buffer = re.search(r'CAPTURE<([^\r\n]*)>', output).group(1)
        self.assertNotIn('NIX_MUST_NOT_RUN', output)
        self.assertNotIn('command not found', output)
        self.assertNotIn('bad option', output)
        return buffer, output

    def test_commands_and_build_targets(self):
        self.assertEqual(self.complete('flake up')[0], 'flake update ')
        self.assertEqual(self.complete('flake build-azu')[0], 'flake build-azure ')
        _, output = self.complete('flake ', tabs=2)
        for name in ['update', 'option', 'build-system', 'switch']:
            self.assertIn(name, output)

    def test_contextual_flags(self):
        self.assertEqual(self.complete('flake update --pi')[0], 'flake update --pick ')
        self.assertEqual(self.complete('flake check --all')[0], 'flake check --all-systems ')
        self.assertEqual(self.complete('flake new --tem')[0], 'flake new --template ')
        self.assertEqual(self.complete('flake show --pi')[0], 'flake show --pi')
        self.assertEqual(self.complete('flake update --tem')[0], 'flake update --tem')
        self.assertEqual(self.complete('flake check --all-systems --pi')[0], 'flake check --all-systems --pi')
        self.assertEqual(self.complete('flake check --pick --all')[0], 'flake check --pick --all')
        self.assertEqual(self.complete('flake --all-systems check --pi')[0], 'flake --all-systems check --pi')

    def test_global_flags_before_command(self):
        self.assertEqual(self.complete('flake --debug up')[0], 'flake --debug update ')
        self.assertEqual(self.complete('flake --debug update be')[0], 'flake --debug update beta ')

    def test_direct_and_follows_inputs(self):
        self.assertEqual(self.complete('flake update bet')[0], 'flake update beta ')
        self.assertEqual(self.complete('flake update ali')[0], 'flake update alias ')
        self.assertEqual(self.complete('flake update trans')[0], 'flake update trans')
        self.assertEqual(self.lock.read_bytes(), self.original_lock)

    def test_multiple_inputs_and_duplicates(self):
        self.assertEqual(self.complete('flake update alpha be')[0], 'flake update alpha beta ')
        self.assertEqual(self.complete('flake update alpha alph')[0], 'flake update alpha alph')
        self.assertEqual(self.complete('flake update alpha --pi')[0], 'flake update alpha --pi')

    def test_pick_and_passthrough_do_not_complete_inputs(self):
        self.assertEqual(self.complete('flake update --pick bet')[0], 'flake update --pick bet')
        self.assertEqual(self.complete('flake --pick update bet')[0], 'flake --pick update bet')
        self.assertEqual(self.complete('flake run -- --deb')[0], 'flake run -- --deb')

    def test_missing_and_invalid_lock(self):
        self.lock.unlink()
        self.assertEqual(self.complete('flake update bet')[0], 'flake update bet')
        self.lock.write_text('{invalid')
        buffer, output = self.complete('flake update bet')
        self.assertEqual(buffer, 'flake update bet')
        self.assertNotIn('parse error', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', required=True)
    args, remainder = parser.parse_known_args()
    package = Path(args.cli).resolve().parent.parent
    completion_dir = package / 'share/zsh/site-functions'
    if not (completion_dir / '_flake').is_file():
        parser.error(f'Packaged completion not found in {completion_dir}')
    os.environ['SNOWFALL_COMPLETION_DIR'] = str(completion_dir)
    unittest.main(argv=[__file__, *remainder], verbosity=2)
