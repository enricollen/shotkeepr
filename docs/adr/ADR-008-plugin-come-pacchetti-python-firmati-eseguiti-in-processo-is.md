# ADR-008: Plugin come pacchetti Python firmati eseguiti in processo isolato

**Status:** Accepted

**Context:** Marketplace on-demand, plugin eseguono codice sul computer dell'utente, modelli non commerciali solo come plugin e bloccati nelle edizioni commerciali.

**Decision:** Un plugin è un wheel con manifest (`id`, `version`, `api_version`, `license`, `non_commercial`, entry point) scaricato da un catalogo JSON firmato; il gestore verifica firma e checksum, mostra la licenza, installa in un ambiente isolato per plugin e lo esegue in un sottoprocesso dedicato con timeout, comunicando tramite la SPI. Un errore disattiva il plugin e lo segnala entro 5 s. L'edizione determina il blocco dei plugin non commerciali.

**Alternatives Considered:** Import diretto nel processo del nucleo (un plugin difettoso blocca l'analisi); plugin come container separati (troppo pesanti per l'uso desktop).

**Consequences:** + Isolamento e degrado controllato. + Licenze tracciate. − Overhead di comunicazione tra processi, accettabile per analisi per scatto.
