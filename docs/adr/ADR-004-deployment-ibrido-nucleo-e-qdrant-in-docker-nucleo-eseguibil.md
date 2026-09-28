# ADR-004: Deployment ibrido — nucleo e Qdrant in Docker, nucleo eseguibile anche nativamente

**Status:** Accepted

**Context:** Container Docker per la portabilità, GPU opzionale, esecuzione completa su CPU; su macOS Docker non accede alla GPU.

**Decision:** `docker compose` avvia due container: `core` (nucleo + worker) e `qdrant`. Le cartelle foto sono montate come volumi (sola lettura di default; lettura/scrittura solo per XMP ed export). Un'immagine `core` CPU e una variante CUDA. Lo stesso pacchetto `shotkeepr-core` è installabile anche nativamente (`uv tool install`) per usare CoreML/Metal su Apple Silicon o per l'uso headless; la GUI si collega a un endpoint configurabile.

**Alternatives Considered:** Solo Qdrant in Docker (meno portabile, dipendenze native sull'host); tutto in Docker inclusa la GUI (GUI in container non portabile).

**Consequences:** + Installazione con un unico comando. + GPU sfruttata dove possibile. − I percorsi host/container vanno tradotti (mappa dei volumi nelle impostazioni); la GUI verifica lo stato dei servizi all'avvio.
