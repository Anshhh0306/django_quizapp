"""The files Render reads (the Blueprint, the build script, the Python pin) must say what the code expects and hold no secret."""
import re
from pathlib import Path

from django.conf import settings
from django.core.management import get_commands
from django.test import SimpleTestCase
from django.urls import resolve

REPO = Path(settings.BASE_DIR)
BLUEPRINT = (REPO / 'render.yaml').read_text(encoding='utf-8')
BUILD = (REPO / 'build.sh').read_text(encoding='utf-8')


def service():
    """The service-level fields of the Blueprint (everything before envVars)."""
    return dict(re.findall(r'(?m)^\s+(?:- )?(type|name|runtime|region|plan|buildCommand|startCommand|healthCheckPath|autoDeployTrigger): (.+)$',
                           BLUEPRINT.split('envVars:')[0]))


def env_vars():
    found = {}
    for block in re.split(r'(?m)^\s*- key: ', BLUEPRINT)[1:]:
        name, _, rest = block.partition('\n')
        found[name.strip()] = {m.group(1): m.group(2).strip().strip('"') for m in re.finditer(r'(?m)^\s+(value|generateValue|sync): (.+)$', rest)}
    return found


class BlueprintTests(SimpleTestCase):
    def test_it_is_the_free_service_in_singapore_next_to_the_database(self):
        self.assertEqual([service()[k] for k in ('type', 'runtime', 'region', 'plan')], ['web', 'python', 'singapore', 'free'])

    def test_it_runs_the_commands_that_exist(self):
        self.assertEqual(service()['buildCommand'], 'bash build.sh')
        self.assertEqual(service()['startCommand'], 'gunicorn quiz_project.wsgi:application')
        self.assertTrue((REPO / 'build.sh').exists() and (REPO / 'gunicorn.conf.py').exists())
        self.assertEqual(resolve(service()['healthCheckPath']).url_name, 'login')  # a page that answers 200 without the database

    def test_the_secret_key_is_made_by_render_and_the_other_secrets_are_asked_for(self):
        found = env_vars()
        self.assertEqual(found['DJANGO_SECRET_KEY'], {'generateValue': 'true'})
        for name in ('DATABASE_URL', 'DJANGO_SUPERUSER_USERNAME', 'DJANGO_SUPERUSER_EMAIL', 'DJANGO_SUPERUSER_PASSWORD'):
            self.assertEqual(found[name], {'sync': 'false'}, name)

    def test_it_holds_no_secret(self):
        """Only these three have a fixed value, and none is secret; the file is in a public repository."""
        fixed = {name for name, fields in env_vars().items() if 'value' in fields}
        self.assertEqual(fixed, {'DJANGO_DEBUG', 'DJANGO_ASSUME_HTTPS', 'DJANGO_TRUSTED_PROXY_COUNT'})
        self.assertFalse('postgres' in BLUEPRINT.lower() and '://' in BLUEPRINT)

    def test_the_settings_are_the_ones_a_host_that_ends_https_needs(self):
        found = env_vars()
        self.assertEqual((found['DJANGO_DEBUG']['value'], found['DJANGO_ASSUME_HTTPS']['value']), ('False', 'True'))
        self.assertEqual(found['DJANGO_TRUSTED_PROXY_COUNT']['value'], '0')  # nothing trusted until the address panel has been checked


class BuildScriptTests(SimpleTestCase):
    def test_it_stops_at_the_first_error_and_runs_the_steps_in_order(self):
        self.assertIn('set -o errexit', BUILD)
        steps = [BUILD.index(step) for step in ('pip install -r requirements.txt', 'collectstatic --noinput', 'migrate --noinput', 'ensure_superuser')]
        self.assertEqual(steps, sorted(steps))

    def test_the_build_runs_with_debug_off_and_a_host_before_it_collects_static_files(self):
        collect = BUILD.index('collectstatic')
        self.assertTrue(BUILD.index('export DJANGO_DEBUG=False') < collect and BUILD.index('export DJANGO_ALLOWED_HOSTS=localhost') < collect)

    def test_the_commands_it_runs_exist(self):
        self.assertIn('ensure_superuser', get_commands())

    def test_it_keeps_unix_line_endings(self):
        self.assertNotIn(b'\r', (REPO / 'build.sh').read_bytes())
        attributes = (REPO / '.gitattributes').read_text(encoding='utf-8')
        self.assertTrue(all(f'{name} text eol=lf' in attributes for name in ('build.sh', 'render.yaml', '.python-version')))


class PythonPinTests(SimpleTestCase):
    def test_python_is_the_version_the_code_is_tested_on(self):
        """A new Render service defaults to a newer Python than the one every test here runs on."""
        self.assertEqual((REPO / '.python-version').read_text(encoding='utf-8').strip(), '3.13')
