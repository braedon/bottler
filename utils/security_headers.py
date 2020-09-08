import functools

from bottle import HTTPResponse, response


def ensure_headers(r, headers):
    """Set headers on a response if not already set"""
    r = r if isinstance(r, HTTPResponse) else response

    for k, v in headers.items():
        if k not in r.headers:
            r.set_header(k, v)


class SecurityHeadersPlugin(object):
    name = 'security_headers'
    api = 2
    sh_defaults = {
        'Strict-Transport-Security': 'max-age=63072000; includeSubDomains; preload',
        'Expect-CT': 'max-age=86400, enforce',
        'Referrer-Policy': 'no-referrer, strict-origin-when-cross-origin',
        'X-XSS-Protection': '1; mode=block',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
    }
    csp_defaults = {
        # Fetch directives
        'default-src': "'none'",
        # Document directives
        'base-uri': "'none'",
        # Navigation directives
        'form-action': "'none'",
        'frame-ancestors': "'none'",
        # Other directives
        'block-all-mixed-content': True,
    }
    fp_defaults = {
        'accelerometer': "'none'",
        'ambient-light-sensor': "'none'",
        'autoplay': "'none'",
        'battery': "'none'",
        'camera': "'none'",
        'display-capture': "'none'",
        'document-domain': "'none'",
        'encrypted-media': "'none'",
        'execution-while-not-rendered': "'none'",
        'execution-while-out-of-viewport': "'none'",
        'fullscreen': "'none'",
        'geolocation': "'none'",
        'gyroscope': "'none'",
        'layout-animations': "'none'",
        'legacy-image-formats': "'none'",
        'magnetometer': "'none'",
        'microphone': "'none'",
        'midi': "'none'",
        'navigation-override': "'none'",
        'oversized-images': "'none'",
        'payment': "'none'",
        'picture-in-picture': "'none'",
        'publickey-credentials-get': "'none'",
        'screen-wake-lock': "'none'",
        'sync-xhr': "'none'",
        'usb': "'none'",
        'wake-lock': "'none'",
        'web-share': "'none'",
        'xr-spatial-tracking': "'none'",
    }

    def __init__(self, sh_updates=None, csp_updates=None, fp_updates=None):
        if sh_updates:
            self.sh_defaults = {**self.sh_defaults,
                                **sh_updates}
        if csp_updates:
            self.csp_defaults = {**self.csp_defaults,
                                 **csp_updates}
        if fp_updates:
            self.fp_defaults = {**self.fp_defaults,
                                **fp_updates}

    def get_sh(self, sh_updates=None):
        sh_dict = self.sh_defaults
        if sh_updates:
            sh_dict = {**sh_dict, **sh_updates}

        return {k: v for k, v in sh_dict.items() if v is not False}

    def get_csp(self, csp_updates=None):
        csp_dict = self.csp_defaults
        if csp_updates:
            csp_dict = {**csp_dict, **csp_updates}

        csp_entries = []
        for k, v in csp_dict.items():
            if isinstance(v, bool):
                if v:
                    csp_entries.append(k)
            else:
                csp_entries.append(f'{k} {v}')

        return '; '.join(csp_entries)

    def get_fp(self, fp_updates=None):
        fp_dict = self.fp_defaults
        if fp_updates:
            fp_dict = {**fp_dict, **fp_updates}

        fp_entries = []
        for k, v in fp_dict.items():
            if v is not False:
                fp_entries.append(f'{k} {v}')

        return '; '.join(fp_entries)

    def apply(self, callback, route=None):
        sh_updates = route.config.get('sh_updates') if route else None
        csp_updates = route.config.get('sh_csp_updates') if route else None
        fp_updates = route.config.get('sh_fp_updates') if route else None
        # Bottle flattens dictionaries passed into route config for some reason,
        # so need to un-flatten the dicts.
        if route:
            if not sh_updates:
                prefix = 'sh_updates.'
                prefix_len = len(prefix)
                sh_updates = {k[prefix_len:]: v for k, v in route.config.items()
                              if k[:prefix_len] == prefix}
            if not csp_updates:
                prefix = 'sh_csp_updates.'
                prefix_len = len(prefix)
                csp_updates = {k[prefix_len:]: v for k, v in route.config.items()
                               if k[:prefix_len] == prefix}
            if not fp_updates:
                prefix = 'sh_fp_updates.'
                prefix_len = len(prefix)
                fp_updates = {k[prefix_len:]: v for k, v in route.config.items()
                              if k[:prefix_len] == prefix}

        headers = {**self.get_sh(sh_updates=sh_updates),
                   'Content-Security-Policy': self.get_csp(csp_updates=csp_updates),
                   'Feature-Policy': self.get_fp(fp_updates=fp_updates)}

        @functools.wraps(callback)
        def wrapper(*args, **kwargs):
            r = callback(*args, **kwargs)
            ensure_headers(r, headers)
            return r

        return wrapper

    def __call__(self, callback):
        return self.apply(callback)
