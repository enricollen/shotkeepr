# ADR-009: Integrazione LLM tramite LiteLLM dietro una porta con redazione dei dati

**Status:** Accepted

**Context:** Spiegazioni discorsive opzionali con qualsiasi provider, nessuna uscita di dati senza consenso, credenziali protette, mai blocco della selezione.

**Decision:** L'adattatore LLM implementa la porta LLM del nucleo con LiteLLM. Per impostazione predefinita invia solo motivazioni strutturate, punteggi e metadati non personali; l'invio dell'immagine richiede consenso esplicito. Timeout configurabile (default 10 s) e ripiego automatico sulle motivazioni strutturate. Le chiavi sono lette dal portachiavi del sistema operativo tramite il modulo di configurazione (libreria `keyring`), mai salvate in SQLite né nei log. Supporto a provider locali (es. Ollama).

**Alternatives Considered:** SDK diretti dei singoli provider (legano il nucleo a pochi provider); nessuna spiegazione LLM (le motivazioni restano meno comprensibili).

**Consequences:** + Nessun blocco e dati sotto controllo dell'utente. − Qualità delle spiegazioni dipendente dal provider scelto.
