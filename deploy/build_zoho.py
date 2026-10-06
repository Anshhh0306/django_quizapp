"""Builds the folder that Zoho Catalyst AppSail uploads: the site's code, its Python packages (the LINUX versions: Zoho runs Linux,
this computer does not), the collected static files, and an app-config.json (with no secrets unless you give --secrets-file).

    python deploy/build_zoho.py                   build into ..\\quizhub_zoho, next to the project folder
    python deploy/build_zoho.py C:\\some\\folder     build somewhere else
    python deploy/build_zoho.py --skip-packages   only the code and static files (a quick rebuild: the packages stay as they are)
    python deploy/build_zoho.py --config-only     only rewrite app-config.json (after `catalyst init` has made its own)
    python deploy/build_zoho.py --secrets-file F  also put the host's secrets from the private file F (NAME=value lines, kept OUTSIDE the
                                                  project) into app-config.json. Values are never printed. That folder is then private too.

Needs Python 3.13 (the version Zoho runs) and the project's requirements installed here (`pip install -r requirements.txt`),
because collectstatic runs here. The only network use is ONE pip command that downloads the Linux packages into the new folder
(it is printed before it runs; nothing is installed on this computer). Run it again after every code change: it replaces what it
made earlier and leaves the files `catalyst init` made (catalyst.json, .catalystrc) alone."""
import argparse
import compileall
import json
import os
import py_compile
import re
import secrets
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
APP_ITEMS = ['manage.py', 'gunicorn.conf.py', 'quiz', 'quiz_project', 'templates', 'static']  # an allow-list: nothing else is copied
LEAVE_OUT = shutil.ignore_patterns('__pycache__', '*.pyc', 'test_*.py', 'tests.py', 'seed_demo.py', '.env*')  # tests, the demo-data command, secrets
START_COMMAND = 'python3 -u -m gunicorn quiz_project.wsgi:application'  # -u: log lines appear at once; python3 -m finds gunicorn in this folder
STACK, MEMORY_MB = 'python_3_13', 512
PUBLIC_SETTINGS = {'DJANGO_DEBUG': 'False', 'DJANGO_TRUSTED_PROXY_COUNT': '1', 'DJANGO_ASSUME_HTTPS': 'True'}  # none of these is a secret
HOST_NAMES = ('DATABASE_URL', 'DJANGO_SECRET_KEY', 'DJANGO_ALLOWED_HOSTS', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD', 'DEFAULT_FROM_EMAIL')  # all a secrets file may give the host
FIRST_HOSTS = '.catalystappsail.in'  # any Zoho address: enough for the very first start, before the exact host name is known
MANIFEST = '.build-manifest.json'  # what this script made, so a rebuild removes exactly that and nothing else
CATALYST_FILES = {'catalyst.json', '.catalystrc', 'app-config.json'}  # what `catalyst init` makes next to our files


def fail(message):
    sys.exit(f'\nStopped: {message}')


def pip_command(target):
    """The one pip command: the Linux (manylinux, Python 3.13) version of every package, into `target`; nothing is installed here."""
    return [sys.executable, '-m', 'pip', 'install', '-r', str(REPO / 'requirements.txt'), '--target', str(target),
            '--platform', 'manylinux2014_x86_64', '--only-binary=:all:', '--python-version', '3.13', '--implementation', 'cp', '--abi', 'cp313']


def check_this_computer():
    if sys.version_info[:2] != (3, 13):
        fail(f'this needs Python 3.13, the version Zoho runs (this is {sys.version.split()[0]}).')
    pinned = re.search(r'^Django==(\S+)', (REPO / 'requirements.txt').read_text(encoding='utf-8'), re.M).group(1)
    try:
        installed = metadata.version('Django')
    except metadata.PackageNotFoundError:
        installed = None
    if installed != pinned:  # collectstatic copies Django's admin files from here
        fail(f'Django {installed or "is not installed"} here but requirements.txt pins {pinned}: run pip install -r requirements.txt first.')


def names(folder):
    return set(os.listdir(folder))


def prepare_folder(out, skip_packages):
    """Checks that `out` is safe to build into, deletes what an earlier run made (the packages too, unless they are kept) and
    returns the package names that stay."""
    if out == REPO or REPO in out.parents or out in REPO.parents:
        fail(f'{out} is the project folder, inside it, or contains it. Build next to it, so packages and secrets can never be committed.')
    if out.exists() and not out.is_dir():
        fail(f'{out} is a file.')
    manifest = {'app': [], 'packages': []}
    if (out / MANIFEST).exists():
        manifest = json.loads((out / MANIFEST).read_text(encoding='utf-8'))
    elif out.is_dir() and names(out) - CATALYST_FILES:
        fail(f'{out} is not empty and was not made by this script; I will not build into it.')
    old = manifest['app'] + ([] if skip_packages else manifest['packages'])
    for name in old:  # the manifest is only trusted for plain names directly inside the folder
        if not name or Path(name).name != name or name in ('.', '..') or name in CATALYST_FILES or name == MANIFEST:
            fail(f'the manifest in {out} lists {name!r}, which is not a plain name inside it. I will not delete anything.')
    for name in old:
        victim = out / name
        if victim.is_dir() and not victim.is_symlink():
            shutil.rmtree(victim)
        elif victim.exists() or victim.is_symlink():
            victim.unlink()
    return manifest['packages'] if skip_packages else []


def copy_app(out):
    for item in APP_ITEMS:
        if (REPO / item).is_dir():
            shutil.copytree(REPO / item, out / item, ignore=LEAVE_OUT)
        else:
            shutil.copy2(REPO / item, out / item)


def collect_static(out):
    """collectstatic with production settings, run here on the copy: it only copies and fingerprints files, so a Linux build is not needed."""
    env = {**os.environ, 'DJANGO_DEBUG': 'False', 'DJANGO_SECRET_KEY': secrets.token_urlsafe(50), 'DJANGO_ALLOWED_HOSTS': 'localhost',
           'DATABASE_URL': 'postgres://build:build@localhost/build'}  # never used: collectstatic does not touch the database
    for name in ('TEST_DATABASE_URL', 'DJANGO_ASSUME_HTTPS', 'DJANGO_TRUSTED_PROXY_COUNT'):
        env.pop(name, None)
    if subprocess.run([sys.executable, 'manage.py', 'collectstatic', '--noinput', '-v', '0'], cwd=out, env=env).returncode:
        fail('collectstatic failed (see above): a template or stylesheet names a static file that does not exist.')


def add_packages(out):
    command = pip_command(out)
    print('\nDownloading the Linux packages into the new folder (nothing is installed on this computer):\n  ' + ' '.join(command) + '\n', flush=True)
    if subprocess.run(command).returncode:
        fail('pip failed (see above).')
    for junk in ('bin', 'Scripts'):  # launcher scripts for THIS computer; the start command uses python3 -m gunicorn instead
        shutil.rmtree(out / junk, ignore_errors=True)


def precompile(out, top_level_names):
    """Ship compiled Python too: Zoho stops an app that is not listening 10 seconds after it starts, and compiling Django on a small
    machine at the first start could use that time. 'Checked hash' stays valid when the upload changes the files' dates."""
    for name in top_level_names:
        path = out / name
        if path.is_dir():
            compileall.compile_dir(str(path), quiet=2, force=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
        elif name.endswith('.py'):
            compileall.compile_file(str(path), quiet=2, force=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)


def read_secrets_file(path):
    """The NAME=value lines of a private file, as a dict. It must live OUTSIDE the project (which is public on GitHub). A value is never
    printed, and a line that is not NAME=value is named only by its number, because it could be a password."""
    if path == REPO or REPO in path.parents:
        fail(f'{path} is inside the project folder, which is public on GitHub. Keep the secrets file outside it.')
    if not path.is_file():
        fail(f'there is no secrets file at {path}.')
    try:
        lines = path.read_text(encoding='utf-8-sig').splitlines()
    except UnicodeDecodeError:
        fail(f'{path.name} is not saved as UTF-8 (in Notepad: Save As, Encoding: UTF-8).')
    found = {}
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*', line)
        if not match:
            fail(f'line {number} of {path.name} is not NAME=value.')
        name, value = match.groups()
        if len(value) > 1 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        found[name] = value
    return found


def host_settings(path):
    """What the host gets from the secrets file: only the names it reads (HOST_NAMES), so a superadmin password kept in the same file for
    this computer stays behind. A missing DJANGO_SECRET_KEY is made and saved into the file, so every build keeps the same one (a new
    key would sign everybody out). Returns the settings and the names that stay behind."""
    found = read_secrets_file(path)
    try:
        url = urlsplit(found.get('DATABASE_URL', ''))
    except ValueError:
        url = urlsplit('')
    if url.scheme not in ('postgres', 'postgresql') or not url.hostname or not url.password:
        fail(f'DATABASE_URL in {path.name} is missing, or is not a postgres address with a user, a password and a host.')
    if '-pooler' in url.hostname:
        fail("DATABASE_URL is Neon's pooled address (-pooler in the host name). Use the direct one: the same host without -pooler.")
    if not found.get('DJANGO_SECRET_KEY'):
        found['DJANGO_SECRET_KEY'] = secrets.token_urlsafe(50)
        text = path.read_text(encoding='utf-8-sig')
        with path.open('a', encoding='utf-8') as file:
            file.write(('' if not text or text.endswith('\n') else '\n') + f'DJANGO_SECRET_KEY={found["DJANGO_SECRET_KEY"]}\n')
        print(f'Made a DJANGO_SECRET_KEY and saved it in {path.name}: every build reuses it.')
    if not found.get('DJANGO_ALLOWED_HOSTS'):
        found['DJANGO_ALLOWED_HOSTS'] = FIRST_HOSTS
    chosen = {name: found[name] for name in HOST_NAMES if found.get(name)}
    return chosen, sorted(set(found) - set(chosen))


def write_config(out, host=None):
    """app-config.json: our start command, the settings that are not secrets and, with --secrets-file, the host's secrets (`host`).
    Whatever else `catalyst init` put there stays."""
    path = out / 'app-config.json'
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'build_path': '.', 'stack': STACK, 'scripts': {}}
    config.update(command=START_COMMAND, memory=MEMORY_MB)
    config['env_variables'] = {**config.get('env_variables', {}), **(host or {}), **PUBLIC_SETTINGS}  # the public settings always win
    path.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')


def build(out, skip_packages=False, host=None):
    check_this_computer()
    kept = prepare_folder(out, skip_packages)
    out.mkdir(parents=True, exist_ok=True)
    before = names(out)  # catalyst's own files, and the packages kept from the last build
    app, new_packages = set(), set()
    try:
        copy_app(out)
        collect_static(out)  # before the Linux packages are added: it runs here, with this computer's own Django
        app = names(out) - before
        if not skip_packages:
            add_packages(out)
            new_packages = names(out) - before - app
        precompile(out, sorted(app | new_packages))
    finally:  # recorded even when a step failed, so the next run can clean up the half-made folder
        app |= names(out) - before - app - new_packages  # the __pycache__ that compiling manage.py made, or what a failed step left
        (out / MANIFEST).write_text(json.dumps({'app': sorted(app), 'packages': sorted(new_packages | set(kept))}, indent=2) + '\n', encoding='utf-8')
    write_config(out, host)
    files = [path for path in out.rglob('*') if path.is_file()]
    print(f'\nBuilt {out}\n  {len(files):,} files, {sum(path.stat().st_size for path in files) / 1e6:,.0f} MB')
    if skip_packages and not kept:
        print('WARNING: this folder has no Python packages (--skip-packages, and no earlier full build here): it will NOT start on Zoho. '
              'Run again without --skip-packages.')
    print('Next: in that folder run `catalyst init` the first time (AppSail, Catalyst-managed, Python 3.13, source directory "."), then run this\n'
          'script again with --config-only' + (' and the same --secrets-file' if host else '') + '; '
          + ('the secrets are in app-config.json already: keep that folder private' if host else 'put the secrets into the Zoho console')
          + '; then `catalyst deploy`. See the README.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the folder Zoho Catalyst AppSail uploads (see the top of this file).')
    parser.add_argument('folder', nargs='?', type=Path, default=REPO.parent / 'quizhub_zoho', help='where to build (default: quizhub_zoho next to the project)')
    parser.add_argument('--skip-packages', action='store_true', help='only the code and static files; keep the packages of the last build')
    parser.add_argument('--config-only', action='store_true', help='only rewrite app-config.json')
    parser.add_argument('--secrets-file', type=Path, help='a private NAME=value file OUTSIDE the project: its secrets go into app-config.json (never printed)')
    args = parser.parse_args(argv)
    out = args.folder.resolve()
    host, left_behind = host_settings(args.secrets_file.resolve()) if args.secrets_file else ({}, [])  # read first: a bad file stops before any slow step
    if args.secrets_file:
        print('Secrets for the host, from the file (values are never shown): ' + ', '.join(host) + '.')
        if left_behind:
            print('Left in the file, not sent to the host: ' + ', '.join(left_behind) + '.')
    if args.config_only:
        if not (out / 'app-config.json').exists():
            fail(f'there is no app-config.json in {out}: build first, then run `catalyst init` there.')
        write_config(out, host)
        print(f'Rewrote {out / "app-config.json"}')
    else:
        build(out, args.skip_packages, host)


if __name__ == '__main__':
    main()
