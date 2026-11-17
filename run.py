"""Start CommerceAI and its local synthetic commerce adapter."""

from argparse import ArgumentParser
from pathlib import Path
import os
import webbrowser

from commerce.auth import Sessions
from commerce.engine import Desk
from commerce.fixtures import STORES
from commerce.http import make_server
from commerce.knowledge import Knowledge
from commerce.nlu import PortableNLU, RasaNLU
from commerce.store import CommerceAdapter, Repository


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "commerce_intents.json"


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8790")))
    parser.add_argument("--db", type=Path, default=ROOT / "instance" / "commerce.sqlite3")
    parser.add_argument("--nlu-url", help="Optional Rasa loopback /model/parse URL")
    parser.add_argument("--provider-offline", choices=STORES, action="append", default=[])
    parser.add_argument("--open", action="store_true", help="Open the local browser after binding")
    args = parser.parse_args()
    repo = Repository(args.db)
    model = RasaNLU(args.nlu_url) if args.nlu_url else PortableNLU(MODEL)
    desk = Desk(repo, CommerceAdapter(repo, args.provider_offline), Knowledge(repo), Sessions(), model)
    try:
        with make_server(ROOT, desk, args.port, host=os.environ.get("HOST", "127.0.0.1")) as server:
            url = f"http://127.0.0.1:{server.server_port}"
            print(f"CommerceAI ready at {url}", flush=True)
            print(f"NLU: {model.name}. Fictional stores and records. Ctrl+C to stop.", flush=True)
            if args.open:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nCommerceAI stopped.", flush=True)
    except OSError as problem:
        parser.exit(1, f"The local server could not start: {problem}. Try --port 8791.\n")


if __name__ == "__main__":
    main()
