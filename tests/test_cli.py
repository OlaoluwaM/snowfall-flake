"""Exercise the CLI with fake external commands; never rebuild a real system."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash')
MOCK = '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as f:
    f.write(json.dumps([name, *args]) + '\\n')
if name in ('sudo', 'doas'):
    os.execvp(args[0], args)
if name == 'nix' and args[:1] == ['eval']:
    print(os.environ.get('MOCK_OUTPUTS', ''), end='')
elif name == 'nix' and args[:2] == ['registry', 'list']:
    print(os.environ.get('MOCK_REGISTRY', ''), end='')
elif name == 'gum' and args[:1] == ['choose']:
    choices = json.loads(os.environ.get('MOCK_CHOICES', '[]'))
    count = sum(json.loads(line)[:2] == ['gum', 'choose'] for line in pathlib.Path(os.environ['CALL_LOG']).read_text().splitlines())
    choice = choices[count - 1] if count <= len(choices) else os.environ.get('MOCK_CHOICE', '')
    print(choice, end='')
elif name == 'gum' and args[:1] == ['spin']:
    i = args.index('--')
    os.execvp(args[i + 1], args[i + 1:])
elif name == 'nixos-option':
    print(os.environ.get('MOCK_OPTIONS', 'value'))
sys.exit(int(os.environ.get('MOCK_' + name.upper().replace('-', '_') + '_STATUS', '0')))
'''


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'
        self.cwd = self.root / 'project with spaces'
        self.cwd.mkdir()
        (self.cwd / 'flake.nix').write_text('{}')
        for name in ['nix', 'nixos-rebuild', 'darwin-rebuild', 'sudo', 'doas', 'gum', 'nixos-option']:
            p = self.bin / name
            p.write_text(f'#!{sys.executable}\n' + MOCK)
            p.chmod(0o755)
        for name in ['filter-flake', 'filter-flakes', 'get-registry-flakes']:
            p = self.bin / name
            p.write_text(f'#!{BASH}\nset -euo pipefail\n' + (ROOT / f'packages/flake/{name}.sh').read_text())
            p.chmod(0o755)
        script = (ROOT / 'packages/flake/flake.sh').read_text()
        script = script.replace('@help@', str(ROOT / 'packages/flake/help'))
        script = script.replace('@isDarwin@', 'false').replace('@flakeCompat@', '/mock/flake-compat')
        self.cli = self.root / 'flake'
        self.cli.write_text(script)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'], CALL_LOG=str(self.log))

    def run_cli(self, *args, **env):
        return subprocess.run([BASH, '-euo', 'pipefail', str(self.cli), *args], cwd=self.cwd,
                              env=self.env | env, capture_output=True, text=True, timeout=5)

    def calls(self, name):
        if not self.log.exists():
            return []
        return [c[1:] for c in map(json.loads, self.log.read_text().splitlines()) if c[0] == name]

    def test_reject_excess_arguments(self):
        limits = {'new': 2, 'init': 1, 'show': 2, 'build': 2, 'build-system': 2,
                  'build-nixos-vm': 2, 'dev': 2, 'run': 2, 'switch': 2, 'test': 2,
                  'boot': 2, 'option': 3, 'check': 2}
        for command, limit in limits.items():
            for total in (limit + 1, 10, 20):
                with self.subTest(command=command, total=total):
                    result = self.run_cli(command, *['extra'] * (total - 1))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('too many positional arguments', result.stdout)
        self.assertFalse(self.log.exists(), 'invalid arguments must not invoke external commands')

    def test_update_pick_rejects_names(self):
        result = self.run_cli('update', '--pick', *['extra'] * 9)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cannot be called with input names', result.stdout)
        self.assertFalse(self.log.exists())

    def test_passthrough_keeps_spaces_empty_values_and_globs(self):
        values = ['two words', '', '*', '--flag', 'semi;colon']
        result = self.run_cli('run', 'app', '--', *values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nix'), [['run', '.#app', '--', *values]])

    def test_show_keeps_uri_as_one_argument(self):
        uri = 'path:/tmp/project with spaces'
        result = self.run_cli('show', uri)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nix'), [['flake', 'show', uri]])

    def test_rebuild_preserves_arguments(self):
        uri = 'path:/tmp/project with spaces#host'
        result = self.run_cli('switch', uri)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('sudo'), [['nixos-rebuild', 'switch', '--flake', uri]])
        self.assertEqual(self.calls('nixos-rebuild'), [['switch', '--flake', uri]])

    def test_missing_template_value(self):
        result = self.run_cli('new', 'project', '--template')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires a value', result.stdout)
        self.assertFalse(self.log.exists())

    def test_help(self):
        for command in ['', 'new', 'init', 'dev', 'run', 'build', 'build-system', 'switch',
                        'test', 'boot', 'show', 'update', 'option', 'check']:
            with self.subTest(command=command):
                result = self.run_cli(*([command] if command else []), '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('USAGE', result.stdout)
        self.assertFalse(self.log.exists())

    def test_empty_picker_outputs(self):
        for command in ['build', 'dev', 'run', 'switch', 'test', 'boot', 'build-system', 'check', 'option', 'update']:
            with self.subTest(command=command):
                result = self.run_cli(command, '--pick')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Could not find any', result.stdout)
        self.assertEqual(self.calls('gum'), [])

    def test_run_picker_preserves_selection(self):
        choice = f'path:{self.cwd}#app'
        result = self.run_cli('run', '--pick', '--', 'two words',
                              MOCK_OUTPUTS=choice + '\n', MOCK_CHOICE='.#app')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nix')[-1], ['run', '.#app', '--', 'two words'])
        self.assertIn('.#app', self.calls('gum')[0])

    def test_multi_input_update(self):
        result = self.run_cli('update', '--pick', MOCK_OUTPUTS='first\nsecond\n', MOCK_CHOICE='first\nsecond\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nix')[-1], ['flake', 'update', 'first', 'second'])

    def test_cancelled_picker_does_not_execute(self):
        result = self.run_cli('build', '--pick', MOCK_OUTPUTS='path:test#app\n', MOCK_CHOICE='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No package selected', result.stdout)
        self.assertEqual(len(self.calls('nix')), 1)

    def test_registry_filtering(self):
        result = subprocess.run([str(self.bin / 'get-registry-flakes')], env=self.env | {
            'MOCK_REGISTRY': 'global flake:nixpkgs github:NixOS/nixpkgs\nuser flake:mine github:me/repo\nsystem flake:local path:/nix/store/local\n'
        }, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['github:NixOS/nixpkgs', 'github:me/repo'])

    def test_empty_registry(self):
        result = subprocess.run([str(self.bin / 'get-registry-flakes')], env=self.env,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')


    def test_nonzero_picker_status_stops_execution(self):
        result = self.run_cli('build', '--pick', MOCK_OUTPUTS='path:test#app\n',
                              MOCK_CHOICE='path:test#app', MOCK_GUM_STATUS='130')
        self.assertEqual(result.returncode, 130)
        self.assertEqual(len(self.calls('nix')), 1)

    def test_nix_failure_propagates(self):
        result = self.run_cli('build', 'app', MOCK_NIX_STATUS='42')
        self.assertEqual(result.returncode, 42)

    def test_optional_flags_do_not_add_empty_arguments(self):
        result = self.run_cli('check', '--show-trace', '--all-systems')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nix'), [['flake', 'check', '.#', '--show-trace', '--all-systems']])

    def test_update_preserves_explicit_input_names(self):
        result = self.run_cli('update', 'first', 'input with spaces')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nix'), [['flake', 'update', 'first', 'input with spaces']])

    def test_system_picker_builds_selected_host(self):
        result = self.run_cli('build-nixos-vm', '--pick', '--show-trace',
                              MOCK_OUTPUTS=f'path:{self.cwd}#host\n',
                              MOCK_CHOICE='.#nixosConfigurations.host')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nixos-rebuild'), [['build-vm', '--flake', '.#host', '--show-trace']])

    def test_darwin_rebuild_preserves_arguments(self):
        self.cli.write_text(self.cli.read_text().replace('is_darwin="false"', 'is_darwin="true"'))
        uri = 'path:/tmp/project with spaces#host'
        result = self.run_cli('switch', uri)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('darwin-rebuild'), [['switch', '--flake', uri]])
        self.assertEqual(self.calls('sudo'), [])

    def test_option_picker_preserves_names(self):
        result = self.run_cli('option', '--pick', MOCK_OUTPUTS=f'path:{self.cwd}#host\n',
                              MOCK_CHOICES=json.dumps(['.#host', '']),
                              MOCK_OPTIONS='This attribute set contains:\nfirst\nsecond name')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No option selected', result.stdout)
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.calls('gum')[-1][-2:], ['first', 'second name'])

    def test_template_picker_handles_empty_registry(self):
        result = self.run_cli('new', 'project', '--pick', MOCK_OUTPUTS='github:NixOS/templates#default\n',
                              MOCK_CHOICE='github:NixOS/templates#default')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nix')[-1], ['flake', 'new', 'project', '--template', 'github:NixOS/templates#default'])

    def test_filter_preserves_uri_without_executing_shell_syntax(self):
        uri = 'path:/tmp/project with spaces; touch SHOULD_NOT_EXIST'
        result = subprocess.run([str(self.bin / 'filter-flakes'), 'templates', uri],
                                cwd=self.cwd, env=self.env | {'MOCK_OUTPUTS': 'true'},
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, uri + '\n')
        self.assertFalse((self.cwd / 'SHOULD_NOT_EXIST').exists())
        self.assertEqual(len(self.calls('nix')), 1)

    def test_filter_with_no_uris(self):
        result = subprocess.run([str(self.bin / 'filter-flakes'), 'templates'],
                                env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertFalse(self.log.exists())


    def test_doas_fallback_preserves_arguments(self):
        (self.bin / 'sudo').unlink()
        uri = 'path:/tmp/project with spaces#host'
        result = self.run_cli('switch', uri, PATH=str(self.bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('doas'), [['nixos-rebuild', 'switch', '--flake', uri]])
        self.assertEqual(self.calls('nixos-rebuild'), [['switch', '--flake', uri]])

    def test_unprivileged_fallback_does_not_evaluate_shell_syntax(self):
        (self.bin / 'sudo').unlink()
        (self.bin / 'doas').unlink()
        uri = 'path:/tmp/project; echo bad > SHOULD_NOT_EXIST'
        result = self.run_cli('switch', uri, PATH=str(self.bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('nixos-rebuild'), [['switch', '--flake', uri]])
        self.assertFalse((self.cwd / 'SHOULD_NOT_EXIST').exists())


if __name__ == '__main__':
    unittest.main()
