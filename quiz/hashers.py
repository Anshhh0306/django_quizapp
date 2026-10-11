from django.contrib.auth.hashers import Argon2PasswordHasher


class SmallArgon2PasswordHasher(Argon2PasswordHasher):
    """Argon2id with the smallest settings OWASP lists for it: 19 MiB of memory, 2 passes, 1 lane.

    One password check costs about 0.02 s of CPU on a laptop; the PBKDF2 setting Django ships (1,000,000 rounds) costs 0.3 s, and on a
    small host (Azure Basic B1: about 3 s per check) 50 students signing in together took minutes. Django's own Argon2 numbers (100 MiB,
    8 lanes) save almost nothing and would use 800 MB when eight sign-ins arrive at once (gunicorn.conf.py runs 8 threads), so they are
    not used. Raising these later is safe: every stored hash is upgraded at its owner's next sign-in (Django's must_update)."""
    time_cost = 2
    memory_cost = 19456  # KiB
    parallelism = 1
