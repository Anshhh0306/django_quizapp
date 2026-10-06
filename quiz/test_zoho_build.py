"""deploy/build_zoho.py: what it puts in the folder Zoho uploads, what it keeps out, and that it cannot clobber or delete anything else.
The pip step itself is not run here (it downloads packages): only the command it would run is checked."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

REPO = Path(settings.BASE_DIR)
SCRIPT = REPO / 'deploy' / 'build_zoho.py'
START = 'python3 -u -m gunicorn quiz_project.wsgi:application'


def load_script():
    spec = importlib.util.spec_from_file_location('build_zoho_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def quietly(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


def value_after(command, flag):
    return command[command.index(flag) + 1]


class PipCommandTests(SimpleTestCase):
    def test_it_asks_for_the_linux_packages_and_installs_nothing_here(self):
        command = load_script().pip_command(Path('target'))
        self.assertEqual(value_after(command, '--platform'), 'manylinux2014_x86_64')
        self.assertIn('--only-binary=:all:', command)
        self.assertEqual([value_after(command, flag) for flag in ('--python-version', '--implementation', '--abi')], ['3.13', 'cp', 'cp313'])
        self.assertEqual(value_after(command, '--target'), 'target')  # into the new folder, not into this computer's Python
        self.assertEqual(Path(value_after(command, '-r')), REPO / 'requirements.txt')

    def test_no_requirement_has_an_environment_marker(self):
        """pip would judge a marker by THIS computer (Windows), not by the Linux host the packages are for."""
        lines = [line for line in (REPO / 'requirements.txt').read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')]
        self.assertEqual([line for line in lines if ';' in line], [])


class ChecksTests(SimpleTestCase):
    def setUp(self):
        self.build = load_script()

    def test_the_wrong_python_is_refused(self):
        with mock.patch.object(self.build.sys, 'version_info', (3, 12, 4, 'final', 0)), self.assertRaisesRegex(SystemExit, 'Python 3.13'):
            self.build.check_this_computer()

    def test_a_different_django_than_the_pinned_one_is_refused(self):
        with mock.patch.object(self.build.metadata, 'version', return_value='5.2.6'), self.assertRaisesRegex(SystemExit, 'pins'):
            self.build.check_this_computer()
        with mock.patch.object(self.build.metadata, 'version', side_effect=self.build.metadata.PackageNotFoundError), \
                self.assertRaisesRegex(SystemExit, 'not installed'):
            self.build.check_this_computer()

    def test_this_computer_passes_its_own_checks(self):
        self.build.check_this_computer()

    def test_the_copy_leaves_out_secrets_tests_and_the_demo_command_wherever_they_are(self):
        """Even a .env that someone drops into a copied folder must not travel to the host."""
        skipped = self.build.LEAVE_OUT('somewhere', ['models.py', 'views.py', '.env', '.env.local', 'test_models.py', 'tests.py', 'seed_demo.py',
                                                     '__pycache__', 'models.cpython-313.pyc'])
        self.assertEqual(set(skipped), {'.env', '.env.local', 'test_models.py', 'tests.py', 'seed_demo.py', '__pycache__', 'models.cpython-313.pyc'})


class BuiltFolderTests(SimpleTestCase):
    """One real build (without the pip step), looked at from several sides."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.build = load_script()
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.out = Path(tmp.name) / 'zoho'
        quietly(cls.build.build, cls.out, skip_packages=True)

    def test_it_holds_the_site_and_its_collected_static_files(self):
        for path in ('manage.py', 'gunicorn.conf.py', 'quiz/models.py', 'quiz/migrations/0001_initial.py', 'quiz_project/wsgi.py',
                     'templates/base.html', 'static/quiz/style.css', 'staticfiles/staticfiles.json'):
            self.assertTrue((self.out / path).exists(), path)
        self.assertTrue(list((self.out / 'staticfiles' / 'quiz').glob('style.*.css')), 'no fingerprinted stylesheet')

    def test_it_leaves_out_tests_the_demo_data_command_and_secrets(self):
        unwanted = [str(p.relative_to(self.out)) for p in self.out.rglob('*')
                    if p.is_file() and (p.name.startswith(('test_', '.env')) or p.name in ('tests.py', 'seed_demo.py', 'README.md', 'requirements.txt'))]
        self.assertEqual(unwanted, [])
        self.assertFalse((self.out / '.git').exists() or (self.out / 'deploy').exists())

    def test_everything_it_made_is_recorded_so_the_next_run_can_clean_up(self):
        recorded = json.loads((self.out / '.build-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(set(os.listdir(self.out)) - {'.build-manifest.json', 'app-config.json'}, set(recorded['app']) | set(recorded['packages']))

    def test_nothing_used_only_for_the_build_is_left_in_it(self):
        """collectstatic ran with a made-up database address and a random key: neither may end up in a file."""
        leaked = [p.name for p in self.out.rglob('*') if p.is_file() and b'build:build@localhost' in p.read_bytes()]
        self.assertEqual(leaked, [])

    def test_the_compiled_files_stay_valid_when_the_upload_changes_file_dates(self):
        pyc = next((self.out / 'quiz' / '__pycache__').glob('models.*.pyc'))
        self.assertEqual(int.from_bytes(pyc.read_bytes()[4:8], 'little'), 0b11)  # PEP 552: hash based, checked against the source

    def test_the_config_has_the_start_command_and_no_secrets(self):
        text = (self.out / 'app-config.json').read_text(encoding='utf-8')
        config = json.loads(text)
        self.assertEqual(config['command'], START)
        self.assertEqual((config['stack'], config['build_path']), ('python_3_13', '.'))
        self.assertEqual(config['env_variables'], {'DJANGO_DEBUG': 'False', 'DJANGO_TRUSTED_PROXY_COUNT': '1', 'DJANGO_ASSUME_HTTPS': 'True'})
        self.assertFalse([word for word in ('SECRET_KEY', 'PASSWORD', 'DATABASE_URL') if word in text.upper()])


class RebuildTests(SimpleTestCase):
    """What a second build may and may not touch. The slow steps are replaced: it is the bookkeeping that is tested here."""

    def setUp(self):
        self.build = load_script()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.out = self.base / 'zoho'
        for step in ('check_this_computer', 'collect_static', 'precompile'):
            patcher = mock.patch.object(self.build, step)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_build(self, **kwargs):
        return quietly(self.build.build, self.out, **kwargs)

    def manifest(self):
        return json.loads((self.out / '.build-manifest.json').read_text(encoding='utf-8'))

    def test_a_rebuild_replaces_what_it_made_and_leaves_catalysts_files_alone(self):
        self.run_build(skip_packages=True)
        (self.out / 'catalyst.json').write_text('{"appsail": []}')
        (self.out / '.catalystrc').write_text('{"projects": []}')
        (self.out / 'quiz' / 'stale.py').write_text('x = 1')
        (self.out / 'static' / 'old.txt').write_text('old')
        config = json.loads((self.out / 'app-config.json').read_text())
        config.update(platform='x', command='echo changed', memory=256)
        config['env_variables']['MY_OWN'] = '1'
        (self.out / 'app-config.json').write_text(json.dumps(config))
        self.run_build(skip_packages=True)
        self.assertFalse((self.out / 'quiz' / 'stale.py').exists() or (self.out / 'static' / 'old.txt').exists())
        self.assertEqual((self.out / 'catalyst.json').read_text(), '{"appsail": []}')
        self.assertEqual((self.out / '.catalystrc').read_text(), '{"projects": []}')
        config = json.loads((self.out / 'app-config.json').read_text())
        self.assertEqual((config['platform'], config['command'], config['memory'], config['env_variables']['MY_OWN']), ('x', START, 512, '1'))

    def test_a_quick_rebuild_keeps_the_packages_and_a_full_one_replaces_them(self):
        self.run_build(skip_packages=True)
        (self.out / 'oldpkg').mkdir()
        (self.out / 'oldpkg' / '__init__.py').write_text('')
        recorded = {**self.manifest(), 'packages': ['oldpkg']}
        (self.out / '.build-manifest.json').write_text(json.dumps(recorded))
        self.run_build(skip_packages=True)
        self.assertTrue((self.out / 'oldpkg').is_dir())
        self.assertEqual(self.manifest()['packages'], ['oldpkg'])

        def fake_pip(out):
            (out / 'newpkg').mkdir()
            (out / 'newpkg' / '__init__.py').write_text('')
        with mock.patch.object(self.build, 'add_packages', fake_pip):
            self.run_build()
        self.assertFalse((self.out / 'oldpkg').exists())
        self.assertTrue((self.out / 'newpkg').is_dir())
        self.assertEqual(self.manifest()['packages'], ['newpkg'])

    def test_a_quick_build_into_a_folder_without_packages_warns(self):
        def printed(**kwargs):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.build.build(self.out, **kwargs)
            return buffer.getvalue()

        self.assertIn('no Python packages', printed(skip_packages=True))

        def fake_pip(out):
            (out / 'newpkg').mkdir()
        with mock.patch.object(self.build, 'add_packages', fake_pip):
            self.assertNotIn('no Python packages', printed())
        self.assertNotIn('no Python packages', printed(skip_packages=True))  # the packages of the full build are still there

    def test_a_failed_step_is_recorded_so_the_next_run_can_clean_up(self):
        with mock.patch.object(self.build, 'add_packages', side_effect=SystemExit('pip failed')), self.assertRaises(SystemExit):
            self.run_build()
        self.assertIn('quiz', self.manifest()['app'])
        self.run_build(skip_packages=True)  # no "not made by this script" refusal, no half-made leftovers in the way
        self.assertTrue((self.out / 'quiz' / 'models.py').exists())

    def test_it_will_not_build_into_a_folder_it_did_not_make(self):
        self.out.mkdir()
        (self.out / 'precious.txt').write_text('mine')
        with self.assertRaisesRegex(SystemExit, 'not made by this script'):
            self.run_build(skip_packages=True)
        self.assertEqual(os.listdir(self.out), ['precious.txt'])

    def test_it_will_not_build_in_or_around_the_project(self):
        stray = REPO / 'zoho_build_test'  # if the guard ever broke, this test would build here: remove its own mess (only what the script made)
        self.addCleanup(lambda: shutil.rmtree(stray) if (stray / '.build-manifest.json').exists() else None)
        for folder in (REPO / 'zoho_build_test', REPO, REPO.parent):
            self.out = folder
            with self.assertRaisesRegex(SystemExit, 'project folder'):
                self.run_build(skip_packages=True)
        self.assertFalse((REPO / 'zoho_build_test').exists())

    def test_a_doctored_manifest_cannot_make_it_delete_anything_outside(self):
        self.out.mkdir()
        outside = self.base / 'outside.txt'
        outside.write_text('keep')
        (self.out / 'sub').mkdir()
        (self.out / 'sub' / 'inner.txt').write_text('keep')
        for bad in ('../outside.txt', '..', '.', '', 'sub/inner.txt', 'catalyst.json', 'app-config.json'):
            (self.out / '.build-manifest.json').write_text(json.dumps({'app': [bad], 'packages': []}))
            with self.assertRaisesRegex(SystemExit, 'plain name'):
                self.run_build(skip_packages=True)
        self.assertEqual(outside.read_text(), 'keep')
        self.assertTrue((self.out / 'sub' / 'inner.txt').exists())

    def test_config_only_rewrites_just_the_config(self):
        self.out.mkdir()
        (self.out / 'app-config.json').write_text(json.dumps({'command': 'echo hi', 'build_path': '.', 'stack': 'python_3_13',
                                                              'env_variables': {}, 'memory': 256, 'scripts': {}}))
        quietly(self.build.main, [str(self.out), '--config-only'])
        config = json.loads((self.out / 'app-config.json').read_text())
        self.assertEqual((config['command'], config['memory']), (START, 512))
        self.assertEqual(os.listdir(self.out), ['app-config.json'])
        with self.assertRaisesRegex(SystemExit, 'build first'):
            quietly(self.build.main, [str(self.base / 'nothing-here'), '--config-only'])
