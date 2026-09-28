# ADR-001: Monolite modulare esagonale con microkernel a plugin

**Status:** Accepted

**Context:** Team piccolo, prodotto locale mono-utente con forte complessità algoritmica e requisito di estendibilità tramite plugin. Il nucleo deve poter funzionare anche senza GUI, come servizio.

**Decision:** Il nucleo è un unico pacchetto Python (`shotkeepr.core`) organizzato per bounded context in moduli con porte (interfacce) e adattatori: dominio puro al centro, adattatori per persistenza, vector store, LLM, decodifica. Il gestore plugin espone una SPI versionata come microkernel.

**Alternatives Considered:** Microservizi (costo operativo eccessivo per un singolo sviluppatore e per un'app locale); monolite a strati senza porte (renderebbe difficile plugin e uso come servizio); applicazione in-process senza API (blocca l'uso headless).

**Consequences:** + Un solo artefatto da testare e rilasciare; logica di dominio testabile senza infrastruttura. + Estrazione futura di servizi lungo i confini dei moduli. − Serve disciplina sulle dipendenze tra moduli (lint di import, vedi [ADR-012](ADR-012-struttura-del-repository-tooling-e-qualita.md)).
