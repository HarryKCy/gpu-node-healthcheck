#!/usr/bin/env python3
"""Local Prometheus HTTP exporter for GPU Node Healthcheck."""

import argparse
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore

from healthcheck import collect_metrics
from prometheus import format_metrics

LOGGER = logging.getLogger(__name__)
# Bound simultaneous subprocesses; overlapping scrapes receive 503 and can retry.
COLLECTION_SLOT = BoundedSemaphore(1)


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404, 'Not Found')
            return
        if not COLLECTION_SLOT.acquire(blocking=False):
            self.send_error(503, 'Collection in progress')
            return
        try:
            body = format_metrics(collect_metrics()).encode('utf-8')
        except Exception:
            # An HTTP request is the isolation boundary: log unexpected failures
            # as well as collection errors, and never serve a partial snapshot.
            LOGGER.exception('Healthcheck collection or metric formatting failed')
            self.send_error(503, 'Metrics unavailable')
            return
        finally:
            COLLECTION_SLOT.release()

        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.debug('Scrape client disconnected')

    def log_message(self, fmt, *args):
        LOGGER.info('%s: %s', self.address_string(), fmt % args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9105)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    try:
        server = ThreadingHTTPServer((args.host, args.port), MetricsHandler)
    except OSError as exc:
        LOGGER.error('Cannot bind exporter to %s:%s: %s', args.host, args.port, exc)
        return 1
    LOGGER.info('GPU Node Exporter listening on http://%s:%s/metrics', args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info('Stopping exporter')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
