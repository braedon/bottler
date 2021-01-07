#!/usr/bin/python3
from gevent import monkey; monkey.patch_all()

import bottle
import click
import configparser
import gevent
import logging
import os.path
import sys
import time

from bottle import Bottle, HTTPError, abort, response, static_file
from gevent.pool import Pool

from utils import log_exceptions, nice_shutdown
from utils.logging import configure_logging, wsgi_log_middleware
from utils.security_headers import SecurityHeadersPlugin

CONTEXT_SETTINGS = {
    'help_option_names': ['-h', '--help']
}

DEFAULT_SITE_ROOT = 'static'
DEFAULT_STATIC_FILE_MAX_AGE_SECS = 10 * 60  # 10 minutes
DEFAULT_STATIC_FILE_HEADERS = {'Cache-Control': f'max-age={DEFAULT_STATIC_FILE_MAX_AGE_SECS}'}

SERVER_READY = True

log = logging.getLogger(__name__)

# Use an unbounded pool to track gevent greenlets so we can
# wait for them to finish on shutdown.
gevent_pool = Pool()


def construct_app(config_file, **kwargs):

    config = configparser.ConfigParser(allow_no_value=True)
    config.read(config_file)

    site_root = DEFAULT_SITE_ROOT
    not_found_file = None
    if 'Site' in config:
        site_config = config['Site']

        site_root = site_config.get('Root', DEFAULT_SITE_ROOT)
        not_found_file = site_config.get('NotFound')

    sfh_updates = None
    if 'StaticFileHeaders' in config:
        sfh_config = config['StaticFileHeaders']

        sfh_updates = {}

        headers = ['Cache-Control', 'Access-Control-Allow-Origin']
        for header in headers:
            value = sfh_config.get(header)
            if value is not None:
                sfh_updates[header] = False if value.lower() == 'false' else value

    sh_updates = None
    if 'SecurityHeaders' in config:
        sh_config = config['SecurityHeaders']

        sh_updates = {}

        headers = ['Strict-Transport-Security',
                   'Expect-CT',
                   'Referrer-Policy',
                   'Cross-Origin-Opener-Policy',
                   'Cross-Origin-Embedder-Policy',
                   'Cross-Origin-Resource-Policy',
                   'X-XSS-Protection',
                   'X-Content-Type-Options',
                   'X-Frame-Options']
        for header in headers:
            value = sh_config.get(header)
            if value is not None:
                sh_updates[header] = False if value.lower() == 'false' else value

    csp_updates = None
    if 'Content-Security-Policy' in config:

        def parse_v(v):
            # If the value is empty or missing entirely, include the directive without a value.
            if v == '' or v is None:
                return True
            # If the value is `false`, don't include the directive.
            if v.lower() == 'false':
                return False
            return v

        csp_updates = {k: parse_v(v)
                       for k, v in config['Content-Security-Policy'].items()}

    pp_updates = None
    if 'Permissions-Policy' in config:

        def parse_v(v):
            # If the value is `false`, don't include the directive.
            if v.lower() == 'false':
                return False
            return v

        pp_updates = {k: parse_v(v)
                      for k, v in config['Permissions-Policy'].items()}

    static_file_headers = DEFAULT_STATIC_FILE_HEADERS
    if sfh_updates:
        static_file_headers = {**static_file_headers, **sfh_updates}
        static_file_headers = {k: v
                               for k, v in static_file_headers.items()
                               if v is not False}

    app = Bottle()

    security_headers = SecurityHeadersPlugin(sh_updates=sh_updates,
                                             csp_updates=csp_updates,
                                             pp_updates=pp_updates)
    app.install(security_headers)

    default_error_csp_updates = {'img-src': "'self'",
                                 'style-src': "'unsafe-inline'"}
    default_error_security_headers = SecurityHeadersPlugin(csp_updates=default_error_csp_updates)
    app.default_error_handler = default_error_security_headers(app.default_error_handler)

    @app.get('/-/live')
    def live():
        return 'Live'

    @app.get('/-/ready')
    def ready():
        if SERVER_READY:
            return 'Ready'
        else:
            response.status = 503
            return 'Unavailable'

    @app.get(r'/')
    @app.get(r'/<filename:re:.+>/')
    def index(filename=None):
        if filename is None:
            filename = 'index.html'
        else:
            filename = os.path.join(filename, 'index.html')

        resp = static_file(filename, root=site_root, headers=static_file_headers.copy())

        # static_file() can return a variety of 4xx errors, with messages that aren't ideal.
        # Just use a standard 404 instead.
        if isinstance(resp, HTTPError) and 400 <= resp.status_code < 500:
            abort(404, 'Not Found')

        return resp

    @app.get(r'/<filename:re:.+>')
    def file(filename):
        resp = static_file(filename, root=site_root, headers=static_file_headers.copy())

        # static_file() can return a variety of 4xx errors, with messages that aren't ideal.
        # Just use a standard 404 instead.
        if isinstance(resp, HTTPError) and 400 <= resp.status_code < 500:
            abort(404, 'Not Found')

        return resp

    if not_found_file is not None:
        not_found_file_path = os.path.join(site_root, not_found_file)

        with open(not_found_file_path) as f:
            not_found_html = f.read()

        @app.error(404)
        @security_headers
        def not_found(error):
            return not_found_html

    return app


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('--config-file', '-c', default='site.cfg', type=click.Path(dir_okay=False),
              help='Path to the site config file. '
                   'Can be absolute, or relative to the current working directory. '
                   '(default: site.cfg)')
@click.option('--port', '-p', default=8080,
              help='Port to serve on. (default=8080)')
@click.option('--shutdown-sleep', default=10,
              help='How many seconds to sleep during graceful shutdown. (default=10)')
@click.option('--shutdown-wait', default=10,
              help='How many seconds to wait for active connections to close during graceful '
                   'shutdown (after sleeping). (default=10)')
@click.option('--json', '-j', default=False, is_flag=True,
              help='Log in json.')
@click.option('--verbose', '-v', default=False, is_flag=True,
              help='Log debug messages.')
@log_exceptions(exit_on_exception=True)
def server(**options):

    def shutdown():
        global SERVER_READY
        SERVER_READY = False

        def wait():
            # Sleep for a few seconds to allow for race conditions between sending
            # the SIGTERM and load balancers stopping sending traffic here.
            log.info('Shutdown: Sleeping %(sleep_s)s seconds.',
                     {'sleep_s': options['shutdown_sleep']})
            time.sleep(options['shutdown_sleep'])

            log.info('Shutdown: Waiting up to %(wait_s)s seconds for connections to close.',
                     {'wait_s': options['shutdown_sleep']})
            gevent_pool.join(timeout=options['shutdown_wait'])

            log.info('Shutdown: Exiting.')
            sys.exit()

        # Run in greenlet, as we can't block in a signal hander.
        gevent.spawn(wait)

    configure_logging(json=options['json'], verbose=options['verbose'])

    app = construct_app(**options)
    app = wsgi_log_middleware(app)

    with nice_shutdown(shutdown=shutdown):
        bottle.run(app,
                   host='0.0.0.0', port=options['port'],
                   server='gevent', spawn=gevent_pool,
                   # Disable default request logging - we're using middleware
                   quiet=True, error_log=None)


if __name__ == '__main__':
    server(auto_envvar_prefix='BOTTLER_OPT')
