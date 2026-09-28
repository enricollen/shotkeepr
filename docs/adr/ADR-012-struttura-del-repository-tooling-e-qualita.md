# ADR-012: Struttura del repository, tooling e qualità

**Status:** Accepted

**Context:** Struttura Python professionale, chiara e semplice con separazione tra GUI, dominio e integrazioni; AGPL con CLA; copertura ≥ 80%; log sicuri; manifest licenze.

**Decision:** Monorepo gestito con uv (workspace) e `pyproject.toml`: `packages/core` (`shotkeepr.core`: `domain/`, `application/`, `adapters/`, `api/`), `packages/desktop` (`shotkeepr.desktop`), `packages/plugin-sdk`, `docker/`, `models/` (manifest), `docs/adr/`, `tests/`. Regole di import verificate con import-linter (il dominio non importa adattatori né Qt). ruff, mypy strict, pytest con coverage, pre-commit; CI GitHub Actions su Windows/macOS/Linux con build delle immagini e dei pacchetti desktop; generazione del manifest licenze a ogni rilascio; log strutturati con rotazione e redazione.

**Alternatives Considered:** Repository separati per GUI e nucleo (versioni da sincronizzare); poetry (più lento, workspace meno naturali).

**Consequences:** + Confini architetturali verificati automaticamente. − Configurazione iniziale della CI multipiattaforma.
