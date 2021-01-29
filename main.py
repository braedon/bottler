#!/usr/bin/python3
from gevent import monkey; monkey.patch_all()

import bottle
import click
import gevent
import logging
import os.path
import sys
import time
import yaml

from bottle import Bottle, HTTPError, abort, response, static_file
from gevent.pool import Pool

from utils import log_exceptions, nice_shutdown
from utils.logging import configure_logging, wsgi_log_middleware
from utils.security_headers import SecurityHeadersPlugin

CONTEXT_SETTINGS = {
    'help_option_names': ['-h', '--help']
}

DEFAULT_CONFIG_FILE = 'config/site.yaml'
DEFAULT_FILE_ROOT = 'static'
DEFAULT_INDEX_FILE = 'index.html'
DEFAULT_MAX_AGE_SECS = 10 * 60  # 10 minutes
DEFAULT_EXTRA_HEADERS = {'Cache-Control': f'max-age={DEFAULT_MAX_AGE_SECS}'}

SERVER_READY = True

log = logging.getLogger(__name__)

# Use an unbounded pool to track gevent greenlets so we can
# wait for them to finish on shutdown.
gevent_pool = Pool()


def build_eh_updates(config):
    eh_config = config.get('extraHeaders') or {}
    eh_headers = ['Cache-Control', 'Access-Control-Allow-Origin']
    eh_updates = {header: value
                  for header, value in eh_config.items()
                  if header in eh_headers}
    return eh_updates


def build_sh_updates(config):
    sh_config = config.get('securityHeaders') or {}
    sh_headers = ['Strict-Transport-Security',
                  'Expect-CT',
                  'Referrer-Policy',
                  'Cross-Origin-Opener-Policy',
                  'Cross-Origin-Embedder-Policy',
                  'Cross-Origin-Resource-Policy',
                  'X-XSS-Protection',
                  'X-Content-Type-Options',
                  'X-Frame-Options']
    sh_updates = {header: value
                  for header, value in sh_config.items()
                  if header in sh_headers}
    return sh_updates


def build_csp_updates(config):
    csp_updates = config.get('contentSecurityPolicy') or {}
    return csp_updates


def build_pp_updates(config):
    pp_updates = config.get('permissionsPolicy') or {}
    return pp_updates


def serve_static_file(filename, root, mimetype=True, headers=None):
    # Some versions of static_file modify the headers dict, so copy it before passing through in
    # case the caller is going to reuse it.
    if isinstance(headers, dict):
        headers = headers.copy()

    resp = static_file(filename, root, mimetype=mimetype, headers=headers)

    # static_file() can return a variety of 4xx errors, with messages that aren't ideal.
    # Just use a standard 404 instead.
    if isinstance(resp, HTTPError) and 400 <= resp.status_code < 500:
        abort(404, 'Not Found')

    return resp


def construct_app(config_file, file_root, **kwargs):

    global_file_root = os.path.abspath(file_root)

    # If a config file wasn't specified but the default one exists, use that.
    if not config_file and os.path.exists(DEFAULT_CONFIG_FILE):
        config_file = DEFAULT_CONFIG_FILE

    if config_file:
        log.info('Loading config file %(config_file)s.', {'config_file': config_file})
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
    else:
        log.warning('No config file found. Using defaults.')
        config = {}

    # Load global config
    not_found_file = config.get('notFoundFile')
    global_eh_updates = build_eh_updates(config)
    global_sh_updates = build_sh_updates(config)
    global_csp_updates = build_csp_updates(config)
    global_pp_updates = build_pp_updates(config)

    route_configs = config.get('routes') or []

    # The root route is just a directory route at `/`.
    root_route_config = {
        'type': 'directory',
        'pathPrefix': '/',
        'indexFile': config.get('indexFile'),
    }

    # Set up the Bottle app.
    app = Bottle()
    security_headers = SecurityHeadersPlugin(sh_updates=global_sh_updates,
                                             csp_updates=global_csp_updates,
                                             pp_updates=global_pp_updates)
    app.install(security_headers)

    # Setup security headers on the default error handler.
    # Need to enable inline styles - used in the default error template - and let the browser try
    # and load a favicon.
    default_error_csp_updates = {'style-src': "'unsafe-inline'",
                                 'img-src': "'self'"}
    default_error_security_headers = SecurityHeadersPlugin(csp_updates=default_error_csp_updates)
    app.default_error_handler = default_error_security_headers(app.default_error_handler)

    # Liveness probe endpoint.
    @app.get('/-/live')
    def live():
        return 'Live'

    # Readiness probe endpoint.
    @app.get('/-/ready')
    def ready():
        if SERVER_READY:
            return 'Ready'
        else:
            response.status = 503
            return 'Unavailable'

    def build_route(route_config):
        method = route_config.get('method') or 'GET'

        eh_updates = build_eh_updates(route_config)
        sh_updates = build_sh_updates(route_config)
        csp_updates = build_csp_updates(route_config)
        pp_updates = build_pp_updates(route_config)

        # Construct the extra headers for the route
        extra_headers = {**DEFAULT_EXTRA_HEADERS, **global_eh_updates, **eh_updates}
        extra_headers = {header: value
                         for header, value in extra_headers.items()
                         if value is not False}

        extra_route_params = {
            'sh_updates': sh_updates,
            'sh_csp_updates': csp_updates,
            'sh_pp_updates': pp_updates,
        }

        if route_config['type'] == 'directory':
            path_prefix = route_config['pathPrefix']
            assert path_prefix[0] == '/', 'pathPrefix must start with /'
            assert path_prefix[-1] == '/', 'pathPrefix must end with /'

            file_root = route_config.get('fileRoot')
            # If present, the route's file root could be relative to the global file root.
            if file_root:
                file_root = os.path.join(global_file_root, file_root)
            # Otherwise, it should default to the global file root plus the path prefix.
            # Need to convert the path_prefix to a relative file path by stripping off the
            # leading `/` and converting to OS specific separators.
            else:
                file_path_prefix = os.path.normcase(path_prefix[1:])
                file_root = os.path.join(global_file_root, file_path_prefix)

            index_file = route_config.get('indexFile') or DEFAULT_INDEX_FILE

            # Serve root files.
            @app.route(path_prefix, method=method, **extra_route_params)
            @app.route(path_prefix + r'<file_path:re:.+>/', method=method, **extra_route_params)
            def serve_dir_roots(file_path=None):
                if file_path is None:
                    filename = index_file
                else:
                    filename = os.path.join(os.path.normcase(file_path), index_file)

                return serve_static_file(filename, file_root, headers=extra_headers)

            # Serve other files.
            @app.route(path_prefix + r'<file_path:re:.+>', method=method, **extra_route_params)
            def serve_dir_files(file_path):
                filename = os.path.normcase(file_path)
                return serve_static_file(filename, file_root, headers=extra_headers)

        elif route_config['type'] == 'file':
            path = route_config['path']
            assert path[0] == '/', 'path must start with /'
            # If the content type isn't provided, set mimetype to True so bottle will try and guess.
            mimetype = route_config.get('contentType') or True

            filename = route_config.get('file')
            # If present, the route's file could be relative to the global file root.
            if filename:
                filename = os.path.join(global_file_root, filename)
            # Otherwise, it should default to the global file root plus the path.
            # Need to convert the path to a relative file path by stripping off the
            # leading `/` and converting to OS specific separators.
            else:
                file_path = os.path.normcase(path[1:])
                filename = os.path.join(global_file_root, file_path)

            @app.route(path, method=method, **extra_route_params)
            def serve_file():
                return serve_static_file(filename, '/', mimetype=mimetype, headers=extra_headers)

        elif route_config['type'] == 'json':
            path = route_config['path']
            assert path[0] == '/', 'path must start with /'
            json_data = route_config['json']

            @app.route(path, method=method, **extra_route_params)
            def serve_json():
                for header, value in extra_headers.items():
                    response.set_header(header, value)
                return json_data

        elif route_config['type'] == 'text':
            path = route_config['path']
            assert path[0] == '/', 'path must start with /'

            content_type = route_config.get('contentType') or 'text/plain'
            if content_type[:5] == 'text/' and 'charset=' not in content_type:
                content_type = content_type.strip() + '; charset=UTF-8'

            text_data = route_config['text']

            @app.route(path, method=method, **extra_route_params)
            def serve_text():
                for header, value in extra_headers.items():
                    response.set_header(header, value)
                response.content_type = content_type
                return text_data

    # Build the custom routes first, in order.
    for route_config in route_configs:
        build_route(route_config)

    # Then add the root route last as the fallback.
    build_route(root_route_config)

    # Set up a custom 404 handler if a 404 file is supplied.
    if not_found_file:
        not_found_file_path = os.path.join(file_root, not_found_file)

        with open(not_found_file_path) as f:
            not_found_html = f.read()

        @app.error(404)
        @security_headers
        def not_found(error):
            return not_found_html

    return app


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('--config-file', '-c', type=click.Path(dir_okay=False),
              help='Path to the site config file. '
                   'Can be absolute, or relative to the current working directory. '
                   '(default: config/site.yaml)')
@click.option('--file-root', '-f', default=DEFAULT_FILE_ROOT, type=click.Path(file_okay=False),
              help='Path to the directory to serve files from. '
                   'Can be absolute, or relative to the current working directory. '
                   '(default: static)')
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
