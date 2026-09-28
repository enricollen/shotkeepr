# ADR-003: Comunicazione GUI↔nucleo tramite API HTTP locale e WebSocket

**Status:** Accepted

**Context:** Nucleo e GUI possono girare in processi o container diversi ([ADR-004](ADR-004-deployment-ibrido-nucleo-e-qdrant-in-docker-nucleo-eseguibil.md)); servono comandi, interrogazioni ed eventi di avanzamento aggiornati almeno ogni secondo; il nucleo deve essere riusabile come servizio.

**Decision:** Il nucleo espone un'API FastAPI su `127.0.0.1` con contratto OpenAPI versionato (`/api/v1`) e un canale WebSocket per eventi (avanzamento, notifiche, degrado). La GUI usa un client tipizzato generato dal contratto. Le miniature sono servite via HTTP con cache. Accesso protetto da un token locale generato all'avvio.

**Alternatives Considered:** Chiamate in-process (impossibile con il nucleo in container); gRPC (tooling più pesante, meno adatto a client web); code di messaggi (infrastruttura superflua).

**Consequences:** + Stessa API per desktop, CLI e altri client. + GUI mai bloccata dall'analisi. − Latenza HTTP da contenere (batch delle interrogazioni, miniature in cache) per mantenere la GUI reattiva.
