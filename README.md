# CommerceAI

**Rishabh Sharma · M25AI2094 · M.Tech. (Artificial Intelligence), IIT Jodhpur**

CommerceAI is a local, multi-tenant ecommerce support prototype with two fictional stores. It includes a catalogue workspace, a verified order assistant, versioned policy answers and a separate staff queue. The default runtime uses Python's standard library and a bundled intent model.

## Run on Windows

1. Extract the complete RAR to a writable folder. Open the `CommerceAI` folder inside it.
2. Install Python **3.10 or newer**. Double-click `Start_CommerceAI.bat`. The launcher starts the server and opens the browser.
3. If needed, open PowerShell in the same folder and run `py -3 run.py`. Go to **http://127.0.0.1:8790**. On Linux or macOS run `python3 run.py`.
4. Keep the terminal open. Press **Ctrl+C** to stop. Confirmed activity persists in `instance/commerce.sqlite3`.

Use `py -3 run.py --port 8791` if port 8790 is occupied. For a fresh demonstration use `py -3 run.py --db instance/presentation.db` with a new filename. All customers, PINs, orders, stock, payments and policies in the demo are synthetic.

## A short defense demonstration

| Goal | Steps | Expected result on a fresh database |
| --- | --- | --- |
| Compare products | In **Nook & Loom**, tick **Compare** on Arc Desk Lamp and Dune Desk Mat. Click **Compare selected**. | ₹1,799.00 versus ₹799.00, with the catalogue's descriptions and stock state. |
| Track a shipment | **Orders → Track an order → DEMO101 → current Demo inbox code → ORD-2402**. | Dispatched, Dune Desk Mat, `NOOK-SHIP-2402`. |
| Test tenant context | Switch to **Trail & Trek**. Start tracking and verify `DEMO101` again. Enter `ORD-2402`. | Summit Steel Bottle and `TRAIL-SHIP-2402` from the other store. The previous verification is cleared. |
| Cancel an owned order | In Nook, **Orders → Cancel an order → verify DEMO101 → ORD-2401 → Confirm**. | `Cancelled` for Nook's order. `ORD-2402` is already dispatched and is ineligible. |
| Edit a preference | **Change delivery preference → ORD-2407 → Call on arrival → Confirm**. | The new preference appears when tracking `ORD-2407`. |
| Request replacement | **Request a return or replacement → ORD-2403 → 01 → Damaged → Replacement → Confirm**. | A generated `RET-` reference and current policy v3.2. Line `02` is personalised and ineligible. |
| Compare store return policies | In each store, **Store policies → How many days is the return window?** | Nook 14 calendar days and Trail 30 calendar days, each with its own citation. A 20-day-old delivery `ORD-2409` is eligible at Trail. |
| Check refund | In Nook, verify and open **Check refund status → ORD-2404**. | Mock provider status `Processed`, ₹399.00. Trail's corresponding record is `In review`, ₹649.00. |
| Hand off to staff | **Support → Talk to an agent → Delivery → type a fictional issue → Confirm**. Save the `TKT-` reference. | Ticket opens in the current store's queue. Using the same conversation again links the existing open handoff. |
| Claim and resolve | Keep the same store. Open **Staff desk**, sign in with the agent ID shown below, claim the ticket, reply and resolve. | Status progresses to `In progress`, then `Resolved`. Verify the customer again and check the ticket to read the reply. |

Store prefixes for staff are `nook` and `trail`. Sample roles are `<store>.agent` with `2411`, `<store>.agent2` with `2412`, and `<store>.admin` with `2419`. Only the administrator can open aggregate activity. To switch back to a customer, use **New chat** or **Sign out**. Context and authorisation are session-bound. The demonstration inbox simulates delivery in the same browser. These intentionally displayed sample credentials have value only inside the loopback demo.

To simulate an unavailable Nook provider, use `py -3 run.py --provider-offline nook`. The order path returns an unavailable message and gives a retry. Trail remains available.

## Reproduce the evidence

Run from the `CommerceAI` project folder.

```powershell
py -3 -m unittest discover -v
py -3 evaluate.py --out evidence/recheck
```

The reproducibility suite exercises the actual local HTTP gateway and temporary SQLite databases. The intent split and knowledge test are separately scored. Raw results, per-intent precision/recall, reference IDs, and JSON dialogue traces are in `evidence/`. Timing varies by system. The fixture clock is fixed in `tests/scenarios.py` to avoid waiting for OTP timers.

To retrain, use a separate Python 3.11 or 3.12 environment. This regenerates the portable weights, training metadata and the Rasa NLU YAML.

```powershell
py -3.12 -m venv .training
.\.training\Scripts\python.exe -m pip install -r requirements-training.txt
.\.training\Scripts\python.exe train.py
.\.training\Scripts\python.exe evaluate.py
.\.training\Scripts\python.exe tools\plot_results.py
```

The graph script uses Graphviz `dot` on PATH for the architecture and database diagrams. For Linux or macOS, substitute `.training/bin/python` for the venv path. The frozen holdout and policy queries are used only for evaluation. The saved baseline is a word-unigram logistic classifier trained on the same training split.

## Optional Rasa DIET integration

Install 64-bit Python 3.10 for this pinned Rasa 3.6.21 recipe. Use a dedicated virtual environment. A short project path can help with the TensorFlow wheel on Windows.

```powershell
py -3.10 -m venv .rasa-env
.\.rasa-env\Scripts\python.exe -m pip install -r requirements-rasa.txt
.\.rasa-env\Scripts\python.exe -m rasa train nlu --config rasa/config.yml --nlu rasa/data/nlu.yml --out rasa/models --fixed-model-name commerce-nlu
.\.rasa-env\Scripts\python.exe -m rasa run --enable-api --interface 127.0.0.1 --port 5005 --model rasa/models/commerce-nlu.tar.gz
```

In a second terminal run `py -3 run.py --nlu-url http://127.0.0.1:5005/model/parse`. Type an opening request so it passes through the connector. The state machine handles verification, authorized fields and confirmations. The release checks the parse contract with a local Rasa-compatible stub. Train the optional DIET model in the separate environment to measure its own scores. The supplied intent numbers come from the portable classifier.

## Source map

| Path | Responsibility |
| --- | --- |
| `run.py`, `Start_CommerceAI.bat` | Entry points and runtime options |
| `commerce/fixtures.py`, `commerce/schema.sql` | Synthetic records, rules and schema |
| `commerce/auth.py`, `commerce/http.py` | Challenge and role handling, session and HTTP boundary |
| `commerce/engine.py`, `commerce/store.py` | Dialogue, eligibility, adapter, persistence, support and audit |
| `commerce/knowledge.py` | Tenant-filtered BM25 retrieval and evidence gate |
| `commerce/nlu.py`, `train.py`, `models/`, `corpus/` | Portable inference, training and evaluation splits |
| `rasa/` | Optional DIET NLU configuration and matching training data |
| `static/` | Responsive catalogue, order, support and staff interface |
| `evaluate.py`, `tests/`, `evidence/` | Scope controls, reproducible experiments and results |
| `figures/`, `tools/` | Measured charts, structural diagrams, interface walkthrough diagrams and plot code |
| `MANIFEST.sha256` | SHA-256 of every other archive file |

The deployment described in the proposal remains a separate engineering phase. Production would use real identity, an approved commerce provider, isolated credentials, and reviewed infrastructure. This project implements synthetic order operations, cited passages and a local staff queue.
