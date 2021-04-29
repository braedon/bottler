Bottler
====
Wrap static sites in a simple Docker container for deployment on Kubernetes (or similar).

[Source Code](https://github.com/braedon/bottler) | [Docker Image](https://hub.docker.com/r/braedon/bottler)

# How?

Bottler serves your site with the [Bottle micro web-framework](https://bottlepy.org/) on a [gevent WSGI server](https://www.gevent.org/).

# Why?

Why not just use a standard webserver like Nginx?

Bottler provides strict [security headers](https://securityheaders.com/) out of the box, which you can relax based on the needs of your site.

It's also designed to be simple to deploy on container services.

* JSON structured request logging (enable with the `--json` option),
* Graceful shutdown on `SIGINT` and `SIGTERM`,
* `/-/live` and `/-/ready` endpoints for liveness and readiness probes.

**:warning: Here Be Dragons**

Take note of the default values for the [Strict-Transport-Security](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Strict-Transport-Security) and [Expect-CT](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Expect-CT) headers in the [site config file](#site-config-file) before deploying. These headers can cause long term issues if not set correctly for your site.

# Quickstart

Docker images for released versions can be found on Docker Hub (`latest` is available):
```bash
> sudo docker pull braedon/bottler
```

Mount your site's static files at `/site/static` and map container port `8080` to a port on the host:
```bash
> sudo docker run --rm \
    -v <path to static files>:/site/static \
    -p <host port>:8080 \
    braedon/bottler
```

A config file can also be mounted in:
```bash
> sudo docker run --rm \
    -v <path to static files>:/site/static \
    -v <path to config file>:/site/config/site.yaml \
    -p <host port>:8080 \
    braedon/bottler
```

If you don't want to mount the config and site files at run time, you can extend the image with your own Dockerfile that copies them in at build time:
```docker
FROM braedon/bottler

COPY <path to static files> /site/static
COPY <path to config file> /site/config/site.yaml
```

# CLI Options

Bottler accepts a few CLI flags:
```
Usage: main.py [OPTIONS]

Options:
  -c, --config-file FILE     Path to the site config file. Can be absolute, or
                             relative to the current working directory.
                             (default: config/site.yaml)

  -f, --file-root DIRECTORY  Path to the directory to serve files from. Can be
                             absolute, or relative to the current working
                             directory. (default: static)

  -p, --port INTEGER         Port to serve on. (default=8080)
  --shutdown-sleep INTEGER   How many seconds to sleep during graceful
                             shutdown. (default=10)

  --shutdown-wait INTEGER    How many seconds to wait for active connections
                             to close during graceful shutdown (after
                             sleeping). (default=10)

  -j, --json                 Log in json.
  -v, --verbose              Log debug messages.
  -h, --help                 Show this message and exit.

```

Any options placed after the image name (`bottler`) will be passed to the process inside the container. For example, enable structured logging with `--json`:
```bash
> sudo docker run --rm \
    -v <path to static files>:/site/static \
    -p <host port>:8080 \
    braedon/bottler --json
```

These options can also be set via environment variables. The environment variable names are prefixed with `BOTTLER_OPT`, e.g. `BOTTLER_OPT_CONFIG_FILE=mysite.yaml` is equivalent to `--config-file mysite.yaml`. CLI options take precedence over environment variables.

# Site Config File

The config file uses the YAML format.

```yaml
# The file to serve at directory roots (e.g. `/`, `/docs/`).
# Can be absolute, or relative to the global file root.
# Defaults to `index.html`.
indexFile: index.html
# The file to use for 404 responses.
# Can be absolute, or relative to the global file root.
# Defaults to the standard bottle error page - it's recommended you override it.
notFoundFile: 404.html

# Extra headers to return when serving files.
# The supported headers and their default values are shown here.
# Setting a header to `false` removes it.
extraHeaders:
  Cache-Control: max-age=600
  Access-Control-Allow-Origin: false

# Configure security headers to return when serving files.
# The supported headers and their default values are shown here.
# Setting a header to `false` removes it.
securityHeaders:
  Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
  Expect-CT: max-age=86400, enforce
  Referrer-Policy: no-referrer, strict-origin-when-cross-origin
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Embedder-Policy: require-corp
  Cross-Origin-Resource-Policy: same-origin
  X-XSS-Protection: 1; mode=block
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY

# Configure policy directives for the `Content-Security-Policy` header.
# The default directives are shown here.
# Setting a directive to `false` removes it.
contentSecurityPolicy:
  # Values that include quotes need to be explicitly quoted.
  default-src: "'none'"
  base-uri: "'none'"
  form-action: "'none'"
  frame-ancestors: "'none'"
  # Some directives don't have values. Set them to `true` to include them.
  block-all-mixed-content: true

# Configure policy directives for the `Permissions-Policy` header.
# The `Feature-Policy` header is also set for compatibility.
# The default directives are shown here.
# Setting a directive to `false` removes it.
permissionsPolicy:
  accelerometer: ()
  ambient-light-sensor: ()
  autoplay: ()
  battery: ()
  camera: ()
  display-capture: ()
  document-domain: ()
  encrypted-media: ()
  execution-while-not-rendered: ()
  execution-while-out-of-viewport: ()
  fullscreen: ()
  geolocation: ()
  gyroscope: ()
  interest-cohort: ()
  layout-animations: ()
  legacy-image-formats: ()
  magnetometer: ()
  microphone: ()
  midi: ()
  navigation-override: ()
  oversized-images: ()
  payment: ()
  picture-in-picture: ()
  publickey-credentials-get: ()
  screen-wake-lock: ()
  sync-xhr: ()
  usb: ()
  wake-lock: ()
  web-share: ()
  xr-spatial-tracking: ()

# Extra routes to serve.
# Incoming requests are checked against the routes in order, and handled by the
# first to match.
# If a request doesn't match any routes it's handled as a normal file request.
#
# Routes are matched based on their HTTP method and path.
# `directory` type routes match on a path prefix, while other types match an
# exact path.
routes:
    # The following route options are available to all route types:

    # The method the request must be using to match the route.
    # A list can be provided to match multiple methods.
    # Defaults to `GET`.
  - method: GET
    # Response header configs can be overridden for the route.
    # Only changes need to be specified here - they will be merged with the
    # global configs.
    extraHeaders: {}
    securityHeaders: {}
    contentSecurityPolicy: {}
    permissionsPolicy: {}

    # The following route options are specific to the route type:

    # Serve files from a path prefix.
    type: directory
    # Requests with a path starting with this prefix are match this route.
    # Must start and end with a `/`.
    pathPrefix: /images/
    # The directory containing the files to serve from this path prefix.
    # Can be absolute, or relative to the global file root.
    # Defaults to the global file root plus the path prefix.
    fileRoot: static
    # The file to serve at directory roots (e.g. `/images/`, `/images/small/`).
    # Defaults to `index.html`
    indexFile: index.html

    # Serve a single file from a path.
  - type: file
    # Requests with this exact path match this route.
    # Must start with '/'.
    path: /favicon.ico
    # The Content-Type header to use.
    # Defaults to guessing from the file extension.
    contentType: text/html
    # The file to serve at this path.
    # Can be absolute, or relative to the global file root.
    # Defaults to the global file root plus the path.
    file: images/favicon.ico

    # Serve configured JSON at a path.
  - type: json
    # Requests with this exact path match this route.
    # Must start with '/'.
    path: /data.json
    # The data to return as JSON.
    json: {'foo': 'bar'}

    # Serve configured text at a path.
  - type: text
    # Requests with this exact path match this route.
    # Must start with '/'.
    path: /hello.html
    # The Content-Type header to use.
    contentType: text/html
    # The text to return.
    text: |-
      <!DOCTYPE html>
      <html>
        <head>
          <title>This is Hello World page</title>
        </head>
        <body>
          <h1>Hello World</h1>
        </body>
      </html>
```
