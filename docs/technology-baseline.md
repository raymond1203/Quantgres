# Technology Baseline

Quantgres is a DB study project. Technology choices should make PostgreSQL
behavior easier to inspect, not hide it.

All new technology adoption and major version changes must be researched through
Context7 first. If Context7 coverage is not useful, use official primary
documentation as fallback and record that fallback explicitly.

## Current Baseline

| Area | Choice | Local version | Decision |
| --- | --- | --- | --- |
| Python | Python 3.14 | `python`: 3.14.0, `uv`: 3.14.6 | Use one current Python minor line for predictable typing and tooling. |
| Package manager | uv | 0.11.21 | Use `uv sync` and `uv run` for dependency and command reproducibility. |
| Formatter/linter | Ruff | 0.15.20 | Use `ruff format --check` and `ruff check` as the fast default gate. |
| Type checker | ty | 0.0.55 | Use `ty check`; keep in mind ty is still young and may evolve quickly. |
| Test runner | pytest | 9.1.1 | Use focused tests for core behavior and DB helpers. |
| DB client | psycopg 3 | 3.3.4 | Use raw SQL, parameter binding, transactions, COPY, and PostgreSQL-specific features directly. |
| Database | PostgreSQL 18 | Docker image baseline | Use current stable major rather than older compatibility baseline. |
| Vector extension | pgvector | 0.8.3 | Use pgvector for VectorDB and agent-memory experiments. |
| Local DB runtime | Docker Compose | Docker 29.4.3 / Compose v5.1.4 | Use one local PostgreSQL service with named volume and init SQL. |
| Build backend | hatchling | build backend only | Keep packaging minimal; no separate Hatch workflow yet. |

## Context7 Research Log

### PostgreSQL

- Context7 library ID: `/websites/postgresql_current`
- Finding: current PostgreSQL documentation identifies PostgreSQL 18 as the
  current stable major release.
- Official fallback checked: PostgreSQL versioning policy and release news.
- Decision: use PostgreSQL 18 as the project baseline.

### pgvector

- Context7 library ID: `/pgvector/pgvector`
- Finding: pgvector documents PostgreSQL 18 Docker tags and HNSW/IVFFlat index
  support.
- Official fallback checked: pgvector repository Docker tag list.
- Decision: use `pgvector/pgvector:0.8.3-pg18-trixie`.

### Astral Tooling: uv, Ruff, ty

- Context7 library ID: `/astral-sh/docs`
- Finding: Astral docs support `uv sync`, `uv run`, Ruff format/check commands,
  and ty checking through the uv-managed environment.
- Decision: keep `uv + ruff + ty` as the default local gate.

### psycopg 3

- Context7 library ID: `/websites/psycopg_psycopg3`
- Finding: psycopg 3 supports parameterized execution, explicit transaction
  behavior, COPY, static typing, prepared statements, and binary communication.
- Decision: use `psycopg 3` as the primary PostgreSQL client and keep SQL
  explicit.

### Docker Compose

- Context7 library ID: `/docker/compose`
- Finding: Compose supports service definitions, images, ports, named volumes,
  bind mounts, and `docker compose config` validation.
- Decision: use Docker Compose for local PostgreSQL only; avoid adding extra
  infrastructure until an experiment needs it.

### pytest

- Context7 library ID: `/pytest-dev/pytest`
- Finding: Context7 identifies pytest as the current primary test framework
  documentation source.
- Decision: keep pytest for focused unit and integration tests.

### Hatchling

- Context7 library ID: `/pypa/hatch`
- Finding: Context7 identifies Hatch/Hatchling as the relevant packaging
  documentation source.
- Decision: use Hatchling only as the minimal PEP 517 build backend. Do not add
  Hatch environments or workflows unless packaging needs grow.

## References

- PostgreSQL versioning policy: https://www.postgresql.org/support/versioning/
- PostgreSQL 18.4 release: https://www.postgresql.org/about/news/postgresql-184-1710-1614-1518-and-1423-released-3297/
- PostgreSQL 18 release: https://www.postgresql.org/about/news/postgresql-18-released-3142/
- pgvector repository and Docker tags: https://github.com/pgvector/pgvector
- Astral docs: https://docs.astral.sh/
- psycopg 3 docs: https://www.psycopg.org/psycopg3/docs/
- Docker Compose docs: https://docs.docker.com/compose/
- pytest docs: https://docs.pytest.org/
- Hatch docs: https://hatch.pypa.io/
