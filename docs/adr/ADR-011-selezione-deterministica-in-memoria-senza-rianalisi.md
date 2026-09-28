# ADR-011: Selezione deterministica in memoria senza rianalisi

**Status:** Accepted

**Context:** Riselezione ≤ 3 s su 5.000 immagini, riproducibilità, prevalenza delle modifiche manuali, motivazioni al 100%.

**Decision:** Il motore di selezione è una libreria pura (nessun I/O) che riceve punteggi, gruppi, impostazioni e modifiche manuali e restituisce decisioni e motivazioni; calcolo vettoriale con NumPy; ordinamenti stabili con tie-break sull'identificativo; ogni esecuzione salva l'istantanea delle impostazioni. L'anteprima dell'aggressività usa lo stesso algoritmo senza persistere.

**Alternatives Considered:** Selezione in SQL (logica difficile da testare e da spiegare); selezione dentro la pipeline di analisi (costringerebbe a rianalizzare).

**Consequences:** + Test unitari esaustivi e risultati identici a parità di input. − Tutti i punteggi della sessione in memoria (≈ decine di MB per 20.000 scatti, entro il limite di memoria).
