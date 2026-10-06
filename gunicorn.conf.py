"""How gunicorn runs the site on a real server. gunicorn finds this file by itself when it is started in this folder:

    gunicorn quiz_project.wsgi:application              (Render)
    python3 -m gunicorn quiz_project.wsgi:application   (Zoho Catalyst AppSail)
"""
import os

# The host says which port to listen on (Zoho Catalyst: X_ZOHO_CATALYST_LISTEN_PORT; Render and others: PORT).
bind = f'0.0.0.0:{os.environ.get("X_ZOHO_CATALYST_LISTEN_PORT") or os.environ.get("PORT") or 8000}'

# ponytail: ONE process with threads, so the in-memory login locks and rate limits (quiz/ratelimit.py) are exact. With
# several processes or instances each keeps its own counters: then give Django a shared (database or Redis) cache.
workers = 1
threads = 8

accesslog = '-'  # one line per request (method, path, status) in the host's log; headers are never logged
