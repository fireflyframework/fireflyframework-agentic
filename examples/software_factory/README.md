# Software factory: build, verify, and archive a Python project

This offline example produces a usable `order_totals.py` module, compiles it,
runs six behavioral unit tests in a child Python process, and creates a ZIP
archive with a SHA-256 checksum. Build and QA statuses reflect actual results.
It requires no API key, network access, package installation during a run, or
external service by default.

The example demonstrates Firefly's state pipeline API. Its nodes are ordinary
async functions, rather than LLM agents. The generator implements one documented
recipe: integer-cent order totals with percentage discounts, half-cent rounding,
and input validation. `--request` records a description in the architecture
record; it does not turn the example into an arbitrary application generator.
For model-backed application code, see [the model-agnostic agent](../model_agnostic_agent.py).

## Run

From the repository root, after installing the project:

```bash
uv run python -m examples.software_factory --workspace /tmp/firefly-order-project
```

Use a dedicated output directory. The generator writes its named project files
there. Omitting `--workspace` creates and prints a retained temporary directory.
The final JSON output and `run.json` contain the run ID, success status, artifact
path, and artifact checksum. A failed pipeline exits with code 1.

The retained files include:

| File | Contents |
|---|---|
| `order_totals.py` | Importable implementation of `total_price(price_cents, quantity, discount_percent=0)` |
| `test_order_totals.py` | Six unittest cases covering ordinary orders, discounts, rounding, zero/full-discount orders, ranges, and input types |
| `README.md` | The generated architecture record and usage instructions |
| `build/order_totals.pyc` | Compiled source |
| `qa-report.json` | Actual test process exit code, test output, and tested source digest |
| `order-totals-sha256-*.zip` | Source, tests, usage instructions, and QA report |
| `run.json` | Run summary and archive digest |
| `.checkpoints/`, `.audit/` | Persistent recovery state and per-node execution records |

The release step checks the source digest again and verifies the archive CRCs.
It creates a local artifact; it does not publish a package or deploy a service.
Unpack the ZIP and run `python -m unittest discover -v` to verify the delivered
project independently. `total_price(1999, 3, 10)` returns `5397` cents.

## Pipeline and recovery

```text
architect -> codegen -> builder -> qa -> stable_release
                 ^                 |
                 +-- failed QA ----+
```

| Node | Work performed |
|---|---|
| `architect` | Records the recipe's contract and design decisions in shared state. |
| `codegen` | Generates the implementation or accepts an initial implementation supplied with `--source`. After failed QA, regenerates the complete recipe. |
| `builder` | Validates permitted syntax, writes the project and tests, and compiles the module. |
| `qa` | Runs the generated tests, stores their output, and reports the actual process result. |
| `stable_release` | Requires passing build/QA, checks the source digest, and writes and verifies the ZIP. |

The `extend` state reducer preserves QA feedback. The QA router loops back to
`codegen` on a test failure, with a maximum of three visits per node. A valid
fresh generation normally completes in one iteration.

To evaluate and repair an existing implementation of this same recipe:

```bash
uv run python -m examples.software_factory \
  --workspace /tmp/firefly-order-repair --source /path/to/order_totals.py
```

The source gate accepts a single `total_price` function with finite arithmetic,
comparisons, and input-validation builtins. Imports, attribute access, loops,
recursive calls, and other application logic are rejected before execution.
QA runs only the generated test module with a ten-second process timeout. This
is a bounded arithmetic recipe, not a sandbox for arbitrary Python applications.

An environmental error, such as a file blocking creation of the `build/`
directory, produces a failed run and a checkpoint. Correct the underlying error,
then use the run ID printed by that run:

```bash
uv run python -m examples.software_factory \
  --workspace /tmp/firefly-order-project --resume RUN_ID
```

The builder is retried from the checkpoint. Completed architect/codegen nodes
are retained. There is no forced failure counter or assumed successful retry.
The regression tests exercise a real filesystem obstruction followed by an
actual failing unit test, checkpoint resume, QA repair, and release.

## External checkpoint adapters

File checkpoints are the default. To opt into an external development service,
install its driver and supply its connection configuration:

```bash
uv run --with 'psycopg[binary]' python -m examples.software_factory --workspace /tmp/firefly-pg-project
uv run --with redis python -m examples.software_factory --workspace /tmp/firefly-redis-project
```

For the first command, set `FIREFLY_CKPT=postgres` and `PG_DSN` in the environment.
For the second, set `FIREFLY_CKPT=redis` and `REDIS_URL`. The CLI closes the clients
it creates. PostgreSQL creates `firefly_checkpoints` if absent; Redis writes
under `firefly:ckpt`. These commands write to the explicitly configured service.

- [PostgreSQL checkpointer](checkpointers/postgres.py) stores checkpoint history
  with parameterized SQL, idempotent sequence updates, and latest-record lookup.
- [Redis checkpointer](checkpointers/redis.py) stores expiring JSON checkpoints,
  scans keys incrementally, compares sequence numbers numerically, and filters
  expired runs. Its default retention is 30 days; set `ttl_seconds` when creating
  an adapter directly. Both byte and decoded-string Redis clients are accepted.
- [PostgreSQL audit log](audit/postgres.py) implements append-only visit recording
  and ordered read-back through `QueryableAuditLog`. Pass it as
  `build_pipeline(checkpointer, audit_log=PostgresAuditLog(connection))`.

These adapters implement Firefly protocols and are complete example integrations.
When instantiating the PostgreSQL adapters directly, use an autocommit connection
or explicitly commit your own transactions; adapters do not own caller connections.
The CLI uses autocommit. Server durability and retention remain properties of the
configured database; the adapters do not configure replication, backups, or WAL/AOF.

The adapter tests replace only the external client/connection boundary. They
verify SQL parameters, JSON round trips, numeric ordering, byte decoding, and
expiry behavior. They do not claim a live PostgreSQL or Redis deployment test.

## Tests

```bash
uv run --extra dev pytest -q tests/examples/software_factory
```

The suite builds and independently tests an extracted release, verifies recovery
and QA repair, checks CLI/audit outputs and source integrity, and covers the
external adapter contracts.
