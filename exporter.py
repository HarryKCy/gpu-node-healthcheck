#!/usr/bin/env python3
"""Local Prometheus HTTP exporter for GPU Node Healthcheck."""

import argparse
import contextlib
import io
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from healthcheck import main as healthcheck_main
from prometheus import format_metrics


class MetricsHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404, "Not Found")
            return

        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            exit_code = healthcheck_main([])

        if exit_code not in (0, 2):
            self.send_error(503, "Metrics unavailable")
            return

        try:
            data = json.loads(output.getvalue())
            body = format_metrics(data).encode("utf-8")
        except (ValueError, KeyError, TypeError):
            self.send_error(503, "Invalid metrics")
            return

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; version=0.0.4; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9105)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MetricsHandler)

    print(f"GPU Node Exporter listening on http://{args.host}:{args.port}/metrics")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping exporter")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
