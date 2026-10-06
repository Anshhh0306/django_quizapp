"""
WSGI config for quiz_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from io import BytesIO

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quiz_project.settings')

# Zoho Catalyst's gateway passes EVERY request body on as "Transfer-Encoding: chunked" with no Content-Length, even when the browser sent one.
# gunicorn reads such a body without trouble, but Django builds request.POST from CONTENT_LENGTH alone: with none, every form arrives EMPTY (a
# sign-in answered "This field is required" for both fields). So a chunked body is read here, up to a limit, and handed on as an ordinary body
# with a Content-Length. The biggest real body is an exam upload (quiz/exams.py MAX_BYTES, 1 MB), so 5 MB is generous; more gets a 413.
MAX_CHUNKED_BODY = 5 * 1024 * 1024


class ReadChunkedBodies:
    def __init__(self, app, limit=MAX_CHUNKED_BODY):
        self.app, self.limit = app, limit

    def __call__(self, environ, start_response):
        if 'chunked' in environ.get('HTTP_TRANSFER_ENCODING', '').lower() and not environ.get('CONTENT_LENGTH'):
            body = environ['wsgi.input'].read(self.limit + 1)  # ponytail: whole body in memory (at most the limit); stream to a temp file if limits ever grow
            if len(body) > self.limit:
                start_response('413 Payload Too Large', [('Content-Type', 'text/plain'), ('Connection', 'close')])
                return [b'The request is too large.\n']
            environ['wsgi.input'] = BytesIO(body)
            environ['CONTENT_LENGTH'] = str(len(body))
            del environ['HTTP_TRANSFER_ENCODING']
        return self.app(environ, start_response)


application = ReadChunkedBodies(get_wsgi_application())
