# Refactoring notes: from prototype to production shape

This document is the engineering narrative behind the first two commits:

1. **`Initial prototype`**, the original service, with editor auto-generated
   filenames normalized to their intended module names but the code otherwise
   untouched.
2. **`Production-ready rebuild`**, the refactor described below.

To see the change as code, read the diff between those two commits. This file
explains the *why*. I've written it the way I'd walk a teammate through a review:
lead with what would page us at 3am, then work down to polish.

---

## The one-paragraph summary

The prototype couldn't start. It imported a `models` module that didn't exist,
and it drove an **async** database engine with the **synchronous** ORM API,
two independent showstoppers. Underneath those, the security and correctness
story had holes: a hardcoded JWT secret, no login endpoint despite advertising
one, every annotation attributed to `user_id=1`, a reporting router that was
never mounted, tests that asserted essentially nothing, and a CI pipeline that
could never pass. The rebuild fixes all of that, commits to a single coherent
(synchronous) stack, adds the missing identity/authorization layer, and backs
it with a test suite and CI that actually run.

| Area | Before | After |
| --- | --- | --- |
| Boot | `ModuleNotFoundError: models` on import | Boots; schema created in a lifespan hook |
| DB stack | Async engine + sync `db.query()` (incoherent) | Fully synchronous SQLAlchemy 2.0 |
| Secret | `SECRET_KEY = "your-secret"` in source | Env-driven; ephemeral random key if unset |
| Login | `tokenUrl="token"` → no such route | Real `POST /auth/token` with hashed passwords |
| Attribution | `user_id=1` hardcoded | `user_id = current_user.id` from the JWT |
| Reports | Router defined, never mounted | Mounted; returns a real aggregate |
| Authorization | Any user could read any row | Owner/admin scoping, 404 on non-owner |
| Validation | `label: str` (free text) | `Label` enum + DB `CHECK` constraints |
| Tests | `assert status != 401` (vacuous) | Isolated DB, exact codes, authz coverage |
| CI | CodeQL `analyze` with no `init`; never installs deps | Lint + test matrix + proper CodeQL |

---

## 1. The two showstoppers

### 1a. `models.py` never existed

Three modules did `from models import Annotation`, but there was no `models`
module anywhere. `schemas.py` only defined *Pydantic* models, which are
validation contracts, not ORM tables. So the very first import crashed and the
app never constructed.

The fix is the new [`app/models.py`](app/models.py): SQLAlchemy 2.0 typed models
for `User` and `Annotation`. I used the modern `Mapped[...]` / `mapped_column`
style rather than the legacy `Column(...)` idiom because it gives real static
types and reads better:

```python
class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(index=True)
    score: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
```

### 1b. Async engine, synchronous usage

`database.py` built an async stack (`create_async_engine`, `AsyncSession`), but
every router called it synchronously:

```python
# before: this cannot work
engine = create_async_engine(DATABASE_URL, echo=True)   # async engine
...
db.add(annotation); db.commit(); db.refresh(annotation) # sync API, no await
db.query(Annotation).filter(...).first()                # AsyncSession has no .query()
```

`AsyncSession` has no `.query()`, and `.commit()`/`.refresh()` are coroutines
that must be awaited; un-awaited, every write silently no-ops. On top of that,
`main.py` called `Base.metadata.create_all(bind=engine)` **at import time**
against the async engine, which raises.

**Decision: go fully synchronous.** The routers already spoke the sync API, the
workload is human-paced (annotators click at human speed, not machine speed), and
sync + FastAPI's threadpool is the simpler, correct thing to demonstrate. The
alternative, rewriting every handler to `await db.execute(select(...))` with an
async test harness, buys concurrency this app will never need. So
[`app/database.py`](app/database.py) is a plain `create_engine` + `sessionmaker`
+ a `get_db` dependency that yields and closes a `Session`. (If we later needed
async, the rule still holds: pick one stack and keep it consistent everywhere,
never mix.)

`create_all` also moved out of import time into a **lifespan** handler in
[`app/main.py`](app/main.py), so it runs once, at startup, after the models are
registered, and doesn't touch a database just because someone imported the app.

---

## 2. Security

### 2a. Hardcoded secret → environment

`SECRET_KEY = "your-secret"` sat in source. Anyone with the repo could forge
tokens. Config now lives in [`app/config.py`](app/config.py) via
`pydantic-settings`, read from the environment. If `SECRET_KEY` is unset, we mint
a **strong ephemeral key** at boot rather than falling back to a weak default;
the demo still runs `git clone && uvicorn`, but no shared secret is ever
committed. (Any deployment sets a stable `SECRET_KEY`; the app logs a warning
when it doesn't.) Treat the original `"your-secret"` as compromised.

### 2b. JWT hardening

Decoding now pins the algorithm list and rejects tokens with a missing/empty
`sub`, and issuance always sets `exp`:

```python
def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None                      # bad signature / expired / malformed → caller returns 401
    subject = payload.get("sub")
    return subject if isinstance(subject, str) and subject else None
```

Pinning `algorithms=[...]` is what closes the classic `alg=none` /
algorithm-confusion attack.

### 2c. Real passwords

The prototype had no notion of a stored password. Registration now hashes with
**bcrypt** ([`app/security.py`](app/security.py)) and login verifies against the
hash. I deliberately used `bcrypt` directly instead of `passlib`: passlib is
effectively unmaintained and its bcrypt backend throws against modern bcrypt
releases. Two small helpers (with explicit 72-byte truncation) are more robust
than a broken dependency.

### 2d. Object-level authorization (IDOR)

Previously any authenticated user could read any annotation by id. Now reads are
ownership-scoped, and a non-owner gets **404, not 403**, so we never confirm that
someone else's annotation exists:

```python
annotation = db.get(Annotation, annotation_id)
if annotation is None or (current_user.role != Role.ADMIN and annotation.user_id != current_user.id):
    raise HTTPException(status_code=404, detail="Annotation not found")
```

### 2e. Roles are server-controlled, not client-settable

The `admin` role is the only thing that bypasses ownership scoping, so where an
account's role comes from *is* the security boundary. Registration therefore
accepts only `email` + `password`; there is no `role` field on `UserCreate`, and
`register()` always creates an annotator. Admins are provisioned out-of-band (a
DB seed / CLI step), and the previously-unused `require_admin` dependency now
guards a real admin-only endpoint (`GET /auth/users`). A regression test asserts
that a request smuggling `{"role": "admin"}` still yields an annotator. (Letting
the client pick its own role would turn "admin" into open self-service, the kind
of privilege-escalation bug that's easy to write and easy to miss.)

---

## 3. Correctness & identity

- **`user_id=1` → the real user.** `create_annotation` now sets
  `user_id=current_user.id`. Per-annotator attribution is the whole point of an
  annotation platform (RLHF accountability, vendor billing), so this was a
  correctness bug, not a nicety. It's enabled by `get_current_user` resolving the
  JWT `sub` to an actual `User` row ([`app/dependencies.py`](app/dependencies.py)).
- **The reports router is mounted.** It was defined but never `include_router`'d,
  so `GET /reports/summary` was dead. It's wired up in `main.py` and now returns
  totals, a per-label breakdown, and the mean score.
- **The login endpoint exists.** `OAuth2PasswordBearer(tokenUrl="token")`
  promised a `/token` route that didn't exist; `tokenUrl` now points at the real
  `auth/token`, so Swagger's "Authorize" flow works end to end.

---

## 4. Data integrity

`label` was a free-text `str`, and nothing stopped `"banna"` or `"HALUCINATION"`
from poisoning the eval data. It's now a `Label` enum validated by Pydantic at
the edge, **and** mirrored by database `CHECK` constraints for defense in depth
(so a bad row can't sneak in via a migration or a direct write):

```python
__table_args__ = (
    CheckConstraint("score >= 1.0 AND score <= 5.0", name="ck_annotations_score_range"),
    CheckConstraint("label IN ('hallucination', 'correct', 'partial')", name="ck_annotations_label"),
)
```

I also added a paginated, filterable `GET /annotations` list endpoint (there was
no way to list before) with a server-capped `limit`, because an unbounded list endpoint
is a latent denial-of-service.

---

## 5. Structure & packaging

The prototype was a flat pile of files named after their first line of code
(`Untitled-2.py`, `from fastapi import FastAPI.py`), with a **byte-identical
duplicate** of `auth.py` and no package `__init__`. It's now a proper `app/`
package with one responsibility per module (`config`, `database`, `models`,
`schemas`, `security`, `dependencies`, `routers/`), the duplicate deleted, and a
single source of truth for each concern.

---

## 6. Configuration

Everything tunable (secret, token lifetime, database URL, SQL echo, CORS) is a
typed field on `Settings`, documented in [`.env.example`](.env.example). No magic
constants scattered through the code, and one obvious place to look when
something needs changing per environment.

---

## 7. Tests

The original suite asserted `response.status_code != 401`. A 404, a 422, even a
500 all satisfy that, and since the app couldn't import, the tests would have
errored at collection anyway. It validated nothing.

The rewritten suite ([`tests/`](tests/)) runs against the real stack on an
isolated, per-test SQLite database with a fixed test secret, and asserts **exact**
status codes. It covers the token lifecycle (valid/expired/tampered/unknown-user),
a create→read round-trip, `422` validation, and, importantly, the
ownership/IDOR scoping, which is exactly the kind of authorization logic that
breaks silently without a test.

---

## 8. CI

The prototype's workflow could never pass: it called `github/codeql-action/analyze`
with **no `init` step** (CodeQL needs `init` to build its database first), used a
Snyk step gated on a `SNYK_TOKEN` a fork/public repo won't have, pinned deprecated
action majors, and never installed dependencies or ran the tests.

The new [`ci.yml`](.github/workflows/ci.yml) has two jobs: a **lint + test matrix**
across Python 3.11 to 3.13 that actually installs deps and runs `ruff` + `pytest`,
and a **CodeQL** job done correctly (`init` → `analyze`, pinned to v3). It keeps
the original's security intent while being a pipeline that can go green.

---

## 9. What I deliberately did *not* do

Good engineering is as much about scope discipline as feature count. I left these
out on purpose, and listed them in the README roadmap instead:

- **Alembic migrations / Postgres.** `create_all` is fine for a two-table
  reference app; Alembic is the right call the moment the schema is real and
  shared, but it's boilerplate that would distract here.
- **A separate CRUD/service layer.** With two models, routers querying directly
  is more readable than an extra layer of indirection. I'd introduce one as the
  domain logic grows.
- **Docker / rate limiting / tracing.** These are production concerns worth naming, not
  worth simulating in a portfolio-scale reference.

The goal was a service that is *correct, secure, tested, and honest about its
scope*, not one that cosplays as a platform it isn't.
