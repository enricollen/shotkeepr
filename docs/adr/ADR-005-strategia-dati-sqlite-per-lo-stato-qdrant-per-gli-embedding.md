# ADR-005: Strategia dati — SQLite per lo stato, Qdrant per gli embedding

**Status:** Accepted

**Context:** Utente singolo, sessioni fino a 20.000 immagini, ripresa dopo crash, 0 perdite di modifiche manuali; gli embedding vanno gestiti con Qdrant.

**Decision:** SQLite in modalità WAL (volume `data/`) è la fonte di verità per catalogo, risultati di analisi, gruppi, esecuzioni, decisioni, profili, feedback e plugin, con SQLAlchemy 2 e migrazioni Alembic. Qdrant contiene solo gli embedding con payload `session_id`, `shot_id`, `model_id`; una collection per modello. Gli embedding sono ricostruibili dai file: in caso di disallineamento si rigenerano. Checkpoint di analisi scritti per scatto in transazione.

**Alternatives Considered:** PostgreSQL in container (più operatività senza benefici per un utente singolo); vettori in SQLite (non rispetta il vincolo Qdrant); Qdrant come unica base (inadatto a dati relazionali e transazioni).

**Consequences:** + Semplicità, backup copiando una cartella. + Riselezione in memoria da SQLite in ≤ 3 s. − Due archivi da mantenere coerenti (riconciliazione all'avvio).
