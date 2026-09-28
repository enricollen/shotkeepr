# ADR-006: Pipeline di analisi a fasi con pool di worker e checkpoint

**Status:** Accepted

**Context:** L'analisi è il carico dominante; deve essere incrementale, ripresabile, con avanzamento dettagliato e memoria ≤ 8 GB.

**Decision:** L'orchestratore scompone l'analisi in fasi idempotenti: *scan → decode → deterministic → ai → embed → group → select*. Ogni scatto attraversa le fasi in un `ProcessPoolExecutor` dimensionato su core e memoria; i modelli sono caricati una volta per worker; lavoro in streaming a lotti. Chiave di cache: impronta del contenuto + versioni degli analizzatori. Ogni fase pubblica eventi di avanzamento con stima del tempo residuo.

**Alternatives Considered:** Job queue esterna (Celery/Redis: infrastruttura superflua); elaborazione sequenziale (troppo lenta su sessioni grandi).

**Consequences:** + Ripresa per scatto e rianalisi solo di ciò che cambia. + Memoria limitata dai lotti. − Il parallelismo va tarato per CPU e GPU (con GPU: un worker di inferenza e più worker di decodifica).
