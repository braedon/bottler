Bottler
====
Wrap static sites in a simple Docker container for deployment on Kubernetes (or similar).

[Source Code](https://github.com/braedon/bottler) | [Docker Image](https://hub.docker.com/r/braedon/bottler)

# How?

Bottler serves your site with the [Bottle micro web-framework](https://bottlepy.org/) on a [gevent WSGI server](https://www.gevent.org/).

# Why?

Why not just use a standard webserver like Nginx?

Bottler provides strict [security headers](https://securityheaders.com/) out of the box, which you can relax as needed based on the needs of your site.

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
    -v <path to config file>:/site/site.cfg \
    -p <host port>:8080 \
    braedon/bottler
```

If you don't want to mount the config and site files at run time, you can extend the image with your own Dockerfile that copies them in at build time:
```docker
FROM braedon/bottler

COPY <path to static files> /site/static
COPY <path to config file> /site/site.cfg
```

# CLI Options

Bottler accepts a few CLI flags:
```
Usage: main.py [OPTIONS]

Options:
  -c, --config-file FILE    Path to the site config file. Can be absolute, or
                            relative to the current working directory.
                            (default: site.cfg)

  -p, --port INTEGER        Port to serve on. (default=8080)
  --shutdown-sleep INTEGER  How many seconds to sleep during graceful
                            shutdown. (default=10)

  --shutdown-wait INTEGER   How many seconds to wait for active connections to
                            close during graceful shutdown (after sleeping).
                            (default=10)

  -j, --json                Log in json.
  -v, --verbose             Log debug messages.
  -h, --help                Show this message and exit.
```

Any options placed after the image name (`bottler`) will be passed to the process inside the container. For example, enable structured logging with `--json`:
```bash
> sudo docker run --rm \
    -v <path to static files>:/site/static \
    -p <host port>:8080 \
    braedon/bottler --json
```

These options can also be set via environment variables. The environment variable names are prefixed with `BOTTLER_OPT`, e.g. `BOTTLER_OPT_CONFIG_FILE=mysite.cfg` is equivalent to `--config-file mysite.cfg`. CLI options take precedence over environment variables.

# Site Config File

The config file uses the [Python Config Parser](https://docs.python.org/3/library/configparser.html) format, which is similar to Windows INI files.

```ini
[Site]
# The root directory of the site's static files.
# Can be absolute, or relative to the working directory (`/site` in the docker image).
# Defaults to `static`.
Root = static

# A HTML file to use for 404 responses.
# Must be relative to the root directory.
# Defaults to the standard bottle error page - it's highly recommended you override it.
NotFound = 404.html

# Configure some headers that are returned when serving the static files.
# The supported headers and their default values are shown here.
# Their values can be overridden.
# Set a default header to `false` to remove it entirely.
[StaticFileHeaders]
Cache-Control = max-age=600

# Configure security headers that are returned when serving the static files.
# Also used for the `NotFound` page, if configured.
# The supported headers and their default values are shown here.
# Their values can be overridden.
# Set a default header to `false` to remove it entirely.
[SecurityHeaders]
Strict-Transport-Security = max-age=63072000; includeSubDomains; preload
Expect-CT = max-age=86400, enforce
Referrer-Policy = no-referrer, strict-origin-when-cross-origin
X-XSS-Protection = 1; mode=block
X-Content-Type-Options = nosniff
X-Frame-Options = DENY

# Configure policy directives for the `Content-Security-Policy` header.
# The default directives are shown here.
# Their values can be overridden, and new directives can be set.
# Set a default directive to `false` to remove it entirely.
[Content-Security-Policy]
default-src = 'none'
base-uri = 'none'
form-action = 'none'
frame-ancestors = 'none'
# Some directives don't have values
block-all-mixed-content

# Configure policy directives for the `Feature-Policy` header.
# The default directives are shown here.
# Their values can be overridden, and new directives can be set.
# Set a default directive to `false` to remove it entirely.
[Feature-Policy]
accelerometer = 'none'
ambient-light-sensor = 'none'
autoplay = 'none'
battery = 'none'
camera = 'none'
display-capture = 'none'
document-domain = 'none'
encrypted-media = 'none'
execution-while-not-rendered = 'none'
execution-while-out-of-viewport = 'none'
fullscreen = 'none'
geolocation = 'none'
gyroscope = 'none'
layout-animations = 'none'
legacy-image-formats = 'none'
magnetometer = 'none'
microphone = 'none'
midi = 'none'
navigation-override = 'none'
oversized-images = 'none'
payment = 'none'
picture-in-picture = 'none'
publickey-credentials = 'none'
sync-xhr = 'none'
usb = 'none'
wake-lock = 'none'
xr-spatial-tracking = 'none'
```
