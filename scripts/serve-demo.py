"""Serve only the public replay with explicit JS MIME types, including on Windows."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8080)
    args=parser.parse_args()
    mimetypes.add_type('text/javascript','.js')
    mimetypes.add_type('text/javascript','.mjs')
    folder=Path(__file__).resolve().parents[1]/'docs'
    handler=partial(SimpleHTTPRequestHandler,directory=str(folder))
    with ThreadingHTTPServer(('127.0.0.1',args.port),handler) as server:
        print(f'DocTrace saved-results replay: http://127.0.0.1:{args.port}/',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass

if __name__=='__main__':main()
