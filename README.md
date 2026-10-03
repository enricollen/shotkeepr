# ShotKeepr

Selezione assistita (AI + misure deterministiche) delle foto migliori da raffiche e cluster di
scatti RAW/JPEG. Applicazione desktop locale, nucleo eseguibile in Docker o nativamente.

Licenza: [GNU AGPL-3.0-or-later](LICENSE) · contributi soggetti al [CLA](CLA.md).

## Struttura

| Percorso | Contenuto |
|---|---|
| `packages/core` | `shotkeepr.core` — dominio (`domain/`), casi d'uso e porte (`application/`), adattatori (`adapters/`), API locale (`api/`) |
| `packages/desktop` | `shotkeepr.desktop` — GUI PySide6, comunica col nucleo solo via API |
| `packages/plugin-sdk` | `shotkeepr.plugin_sdk` — SPI versionata per i plugin |
| `docker/` | Immagini del nucleo e `docker compose` |
| `models/` | Manifest dei modelli AI |
| `docs/adr/` | [Architecture Decision Records](docs/adr/README.md) |

## Sviluppo

Requisiti: [mise](https://mise.jdx.dev) (installa Python 3.12 e uv da `.mise.toml`).

```bash
mise install
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run lint-imports        # confini architetturali (ADR-001, ADR-012)
uv run pytest --cov        # copertura minima 80% (NFR-023)
uv run pre-commit install
```

## API locale e client tipizzato

Il nucleo espone `/api/v1` (FastAPI, bind `127.0.0.1`, token locale generato
all'avvio) e un canale WebSocket per gli eventi di avanzamento (ADR-003):

```bash
uv run shotkeepr-core serve [--port N]   # token e porta scritti in <app-data>/run/
```

La GUI parla col nucleo solo via HTTP/WebSocket (ADR-002): `packages/desktop/src/shotkeepr/desktop/api_client/`
è un client tipizzato **generato automaticamente** dal contratto OpenAPI — non va modificato a mano.
Dopo ogni cambio alle rotte del nucleo, rigenerarlo con:

```bash
scripts/generate_client.sh
```

Il canale WebSocket (non descritto da OpenAPI) ha un wrapper scritto a mano in
`packages/desktop/src/shotkeepr/desktop/api_events.py`.

## Applicazione desktop

```bash
uv run shotkeepr
```

La shell PySide6 avvia un processo nativo del nucleo e lo arresta alla chiusura.
Contiene albero delle cartelle, griglia con miniature e pannelli Dettagli/Criteri/Esclusi.
Aprire una cartella e premere **Importa**, con l'opzione Sottocartelle; avanzamento,
annullamento e risultati passano dall'API senza bloccare la finestra. I temi
chiaro/scuro sono persistenti. Anche le miniature vengono caricate via HTTP.
Il selettore **Sessioni salvate** e il pulsante **Apri sessione** permettono di
consultare importazioni precedenti senza reimportare gli originali.
**Raggruppa raffiche** usa modello/seriale fotocamera e orari EXIF, con intervallo
configurabile; il selettore dei gruppi consulta l'intera sessione, non solo la pagina.
Nel pannello Dettagli si possono salvare decisioni manuali Tenuta/Scartata/Da rivedere
ed esportare lo XMP dello scatto dopo conferma; queste azioni non avviano analisi AI.
Nel pannello Dettagli, **Misura esposizione (anteprima)** calcola indicatori
parziali sul JPEG in cache; non avvia l'analisi AI completa.
**Misura nitidezza (anteprima)** riporta il dettaglio globale del JPEG, non il fuoco
del soggetto. I dettagli sono scorrevoli anche con entrambe le misure presenti.
**Misura anteprime della sessione** esegue entrambe le misure su tutti gli scatti,
anche non caricati o nascosti dai filtri. **Ferma misure** conserva i risultati
gia' salvati; riavviare l'operazione riusa le misure invariate nel nucleo.
**Esporta XMP della sessione...** scrive gli stati salvati dell'intera sessione,
solo dopo conferma. **Ferma export** interrompe tra richieste, senza annullare
le scritture gia' completate.
Qt 6 gestisce automaticamente gli schermi HiDPI; il layout supporta 1366x768.
Scorciatoie: Ctrl+O apre una cartella, Ctrl+R riprova la connessione.

Per collegarsi a un nucleo gia' avviato, senza gestirne il processo:

```bash
uv run shotkeepr --core-url http://127.0.0.1:8321 --token-file /percorso/api.token
```

Il nucleo accetta anche `--data-dir` e `--runtime-dir` per isolare dati e credenziali
di avvio. Su Linux servono le librerie di sistema Qt (OpenGL/EGL, fontconfig,
FreeType, X11, xkbcommon, GLib e D-Bus) oltre a una sessione grafica.
I test della shell usano Qt offscreen: `QT_QPA_PLATFORM=offscreen uv run pytest packages/desktop/tests`.

## Nucleo in Docker (F1.D1.WP2)

Requisiti: Docker Engine/Desktop con Compose v2. Dalla radice del repository,
creare una directory privata per il token; poi avviare nucleo e Qdrant:

```bash
mkdir -p data/run && chmod 700 data/run
SHOTKEEPR_PHOTOS_DIR=/percorso/assoluto/foto \
  docker compose -f docker/compose.yaml up --build -d --wait
```

Il nucleo e' pubblicato **solo su `127.0.0.1:8321`** dell'host. Qdrant non espone
porte sull'host ed e' raggiungibile solo nella rete Compose. Le immagini girano
senza privilegi di root, con filesystem di sola lettura e senza capability.
Database/log e dati vettoriali persistono nei volumi `core-data` e `qdrant-data`;
foto (`/photos`) e modelli (`/models`) sono montati in sola lettura. Le cartelle
devono esistere: Compose non le crea silenziosamente. Il contesto di build include
solo manifest e sorgenti necessari, non dati locali o documentazione privata.

Su Linux, se UID/GID dell'utente non sono 1000, aggiungere alla stessa invocazione
`SHOTKEEPR_UID=$(id -u) SHOTKEEPR_GID=$(id -g)` per consentire al nucleo di scrivere
il token nella directory host. Non avviare come root. `SHOTKEEPR_RUNTIME_DIR`
puo' indicare un'altra directory privata **assoluta**; `SHOTKEEPR_PORT` cambia la
porta pubblicata sull'host, non quella interna (8321). Il token in `data/run/api.token`
e' leggibile solo dal proprietario e viene rigenerato a ogni avvio. Non usare
`api.port` per scoprire la porta dell'host quando `SHOTKEEPR_PORT` e' personalizzata.

Per collegare la GUI al nucleo in Docker:

```bash
uv run shotkeepr --core-url http://127.0.0.1:8321 --token-file data/run/api.token
```

Salute e arresto (mantenendo i dati):

```bash
docker compose -f docker/compose.yaml ps
docker compose -f docker/compose.yaml exec core shotkeepr-core healthcheck --port 8321
docker compose -f docker/compose.yaml down
```

Mantenere `SHOTKEEPR_PHOTOS_DIR` impostata anche per questi comandi. Entrambe le
immagini includono una sonda HTTP: `/api/v1/health` per il nucleo, `/readyz` per
Qdrant. Il nucleo parte solo dopo che Qdrant e' sano. Questa fase prepara Qdrant
e le librerie CUDA; la pipeline di valutazione, il client vettoriale e l'inferenza
dei modelli fotografici saranno implementati nelle fasi successive.

La variante CUDA richiede una GPU NVIDIA e NVIDIA Container Toolkit sull'host:

```bash
SHOTKEEPR_PHOTOS_DIR=/percorso/assoluto/foto \
  docker compose -f docker/compose.yaml -f docker/compose.cuda.yaml up --build -d --wait
```

Per `ps`, `exec` e `down` della variante CUDA usare entrambi i file Compose.
Su macOS usare l'immagine CPU o il nucleo nativo; Docker non accede a Metal/CoreML.
CPU e CUDA installano extras diversi, senza sovrapporre i due pacchetti ONNX.
ONNX Runtime 1.30.x richiede CUDA 13/cuDNN 9: l'immagine CUDA usa questa ABI.

## Installazione nativa del solo nucleo

```bash
uv tool install --with ./packages/plugin-sdk './packages/core[cpu]'
shotkeepr-core serve --port 8321
shotkeepr-core healthcheck --port 8321
```

L'installazione da sorgenti include esplicitamente l'SDK locale. Senza `--port`,
il server sceglie una porta libera e `healthcheck` legge il file `api.port` nella
directory runtime (personalizzabile con `--runtime-dir`). La sonda restituisce 0
solo se il nucleo risponde con `status=ok`, altrimenti 1 con un messaggio su stderr.
Il bind nativo resta loopback; `serve --host 0.0.0.0` e' un opt-in per il container,
non un'impostazione da usare sull'host. L'autenticazione bearer resta obbligatoria
per impostazioni ed eventi; la rotta di salute e' pubblica.

## Runtime e registro dei modelli AI (F1.D2.WP4.A1-A2)

```bash
uv run shotkeepr-core models providers
uv run shotkeepr-core models list --manifest models/manifest.json
uv run shotkeepr-core models fetch MODEL_ID --manifest models/manifest.json --cache-dir data/models
uv run shotkeepr-core models verify MODEL_ID --manifest models/manifest.json --cache-dir data/models
uv run shotkeepr-core models validate MODEL_ID --manifest models/manifest.json --cache-dir data/models --device cpu
```

`providers` mostra i provider disponibili e la preferenza, **non** certifica che
una sessione GPU sia inizializzata. `validate` verifica prima i pesi in cache e
carica realmente il grafo ONNX, riportando provider attivo, input e output.
`verify` e `validate` non accedono alla rete. `fetch` usa la cache se gia' valida;
scarica in streaming solo un artefatto assente, con progressi su stderr e risultato
JSON su stdout. Se un file in cache e' corrotto, il comando fallisce esplicitamente
senza sovrascriverlo: rimuovere il solo artefatto indicato prima di riscaricarlo.
Non si scarica nulla durante il normale avvio dell'API o della GUI.

Il manifest `models/manifest.json` e' intenzionalmente vuoto: nessun peso, hash o
licenza viene inventato. La conversione/validazione di SigLIP/OpenCLIP, DINOv2,
RF-DETR, MediaPipe ed estetica resta l'attivita' **F1.D2.WP4.A3**. Per ogni modello
approvato inserire `model_id`, `version`, `url`, `sha256`, `size_bytes`, `license`,
`license_url` e `source_url`; lo schema per gli editor e' `models/manifest.schema.json`.
Gli URL devono essere HTTPS senza credenziali, query o frammenti; redirect verso
HTTP, indirizzi privati espliciti e nomi locali sono rifiutati. Le licenze ammesse
sono MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause e CC0-1.0; la dichiarazione nel
manifest non sostituisce la verifica legale dei pesi e della loro provenienza.
Se sono presenti piu' versioni dello stesso modello, specificare `--version`.

La cache predefinita e' `<app-data>/models`; ogni coppia identificativo/versione
ha file ONNX e record di provenienza/licenza separati, identificati dal SHA-256.
Hash e dimensione vengono ricontrollati anche offline. Lock tra processi e rename
atomici evitano la pubblicazione di download parziali e serializzano richieste
concorrenti. In Docker il manifest e' `/models/manifest.json` (sola lettura) e la
cache scrivibile/persistente deve essere `--cache-dir /data/models`.

Le sessioni scelgono CUDA, poi CoreML, poi CPU (`--device auto`). Un provider
accelerato disponibile ma non inizializzabile produce un avviso e un motivo di
degrado; un device imposto (`cpu`, `cuda`, `coreml`) non degrada silenziosamente.
Il nucleo base puo' gestire manifest e download senza ONNX; per l'inferenza
installare l'extra `cpu` o `cuda`, mai entrambi. L'ambiente di sviluppo include
automaticamente l'extra CPU. I test generano un piccolo grafo sintetico e lo
eseguono realmente su CPU, senza scaricare modelli fotografici.

## Importazione fotografica headless (F2.D1.WP1.A1-A3)

Installare **ExifTool** e renderlo disponibile nel `PATH` per l'importazione
nativa; le immagini Docker lo includono gia'. Metadati e riconoscimento formato
usano ExifTool, le anteprime Pillow/pillow-heif e rawpy (LibRaw).

```bash
uv run shotkeepr-core photos import /percorso/foto --data-dir data/catalog
uv run shotkeepr-core photos import /percorso/foto --no-subfolders --data-dir data/catalog
uv run shotkeepr-core photos list --data-dir data/catalog
uv run shotkeepr-core photos show SESSION_UUID --data-dir data/catalog
```

Le sottocartelle sono incluse per impostazione predefinita, ma nessun collegamento
simbolico viene seguito: file/link non accessibili, formati non supportati e immagini
corrotte sono elencati nelle esclusioni, senza fermare gli altri file. Un errore
globale (ExifTool non disponibile, disco pieno, salvataggio fallito) restituisce 1
e viene segnalato su stderr. Progressi su stderr, risultati JSON su stdout.

La classificazione usa il **contenuto**, non il suffisso: JPEG, PNG, TIFF, HEIC,
WebP e RAW ARW/CR2/CR3/NEF/ORF/RAF/RW2/PEF/DNG. I RAW richiedono anche una decodifica
riuscita con la versione di LibRaw installata: il riconoscimento non garantisce
la compatibilita' di ogni modello di fotocamera. I metadati mancanti restano assenti.
Gli orari EXIF con offset sono normalizzati in UTC; senza offset, l'ora locale della
fotocamera viene archiviata con UTC come convenzione, **non** come fuso accertato.
Le frazioni di secondo sono conservate.

Una coppia RAW+JPEG richiede stessa cartella, stesso nome base e istante di scatto
noto e identico. Fotocamere/seriali discordanti o piu' candidati impediscono
l'abbinamento. PNG/TIFF non vengono abbinati ai RAW; se manca l'ora, i file restano
scatti distinti. Copie con gli stessi contenuti sono una sola unita' con tutti i
percorsi conservati, senza violare l'unicita' delle impronte del catalogo.

Le miniature JPEG, orientate e limitate a 512 pixel, sono salvate in
`<data-dir>/previews/v1-512/`, indicizzate dal SHA-256 e pubblicate con rename
atomico. Un file modificato durante lettura/decodifica e' escluso. Per RAW si
preferisce il JPEG incorporato, altrimenti la decodifica a meta' risoluzione.
La cache gia' valida viene riutilizzata, anche tra nuove sessioni. `photos show`
espone percorsi delle anteprime, file, metadati ed esclusioni persistenti.

**Database e cache devono essere esterni alla cartella sorgente.** L'importazione
non scrive sugli originali; sessione, scatti ed esclusioni finali vengono pubblicati
insieme in SQLite. Lo stato finale e' `IMPORTED`, non `ANALYZED`, e il riepilogo
riporta `analysis_performed: false`. Ogni comando import crea una nuova sessione;
la ripresa incrementale dell'analisi non e' ancora implementata.

In Docker usare `photos import /photos --data-dir /data` tramite `compose exec core`;
foto in sola lettura e cache/database nel volume persistente. L'importazione e'
ora disponibile anche tramite API e GUI; la valutazione AI resta da implementare.
I test di integrazione fotografica richiedono ExifTool; un DNG sintetico prova anche la
decodifica reale con LibRaw. Il resto usa immagini generate e prove isolate dei
decoder. La convalida RAW multi-produttore resta da eseguire
su campioni reali, senza dedurla dai test di riconoscimento del formato.

## Importazione in background, API e GUI (F2.D1.WP1.A4-A5)

Il nucleo esegue **una sola importazione API alla volta** in un worker separato.
Non si mettono in coda richieste illimitate: una seconda importazione riceve HTTP
409. Il server resta disponibile per salute, impostazioni, stato e annullamento.
Se ExifTool non e' installato, l'avvio dell'API resta disponibile ma l'importazione
riceve HTTP 503 con indicazioni; percorsi relativi e richieste non valide sono rifiutati.
Gli errori del worker vengono registrati e riportati nello stato, mai come successi.

| Metodo e percorso `/api/v1` | Risultato |
|---|---|
| `POST /photos/imports` | HTTP 202 e job; body `source_folder`, `include_subfolders` |
| `GET /photos/imports/{job_id}` | Stato e contatori aggiornati |
| `POST /photos/imports/{job_id}/cancel` | Richiesta di annullamento cooperativo |
| `GET /photos/sessions` | Sessioni persistenti |
| `GET /photos/sessions/{session_id}` | Riepilogo e file esclusi |
| `GET /photos/sessions/{session_id}/shots?limit=100&offset=0` | Scatti paginati, massimo 200 |
| `GET /photos/shots/{shot_id}/thumbnail` | Miniatura JPEG, non il file originale |

Tutte le rotte fotografiche, incluse le miniature, richiedono il token bearer.
Il percorso sorgente e' **assoluto e relativo al filesystem del nucleo**. I job
passano per `QUEUED`/`RUNNING` e terminano in `SUCCEEDED`, `FAILED` o `CANCELLED`.
`SUCCEEDED` significa importazione completata, non valutazione della qualita'.
Lo stato dei 20 job piu' recenti resta in memoria fino al riavvio; sessioni, scatti
ed esclusioni restano in SQLite. Una richiesta rifiutata o annullata prima della
creazione della sessione non produce necessariamente una riga nel catalogo.

I progressi emettono anche eventi `PROGRESS`/`NOTIFICATION` su `/api/v1/events`,
con `operation: photo-import`, job e contatori. La GUI usa il polling dello stato
ogni 500 ms e offre **Riprova stato** se la connessione si interrompe; un errore
di rete non avvia automaticamente un'altra importazione. L'annullamento viene
controllato tra i file e prima della pubblicazione atomica: nessun catalogo
parziale viene pubblicato, e un import gia' completato non viene annullato a posteriori.

La GUI carica 40 scatti per pagina tramite il client generato; **Carica altri
scatti** aggiunge la pagina successiva. Mostra miniature, metadati e le prime 200
esclusioni, riportando il numero delle ulteriori esclusioni. Non apre immagini
o cache dal filesystem dell'host, quindi funziona anche con il nucleo in Docker:
nel campo del percorso del nucleo inserire `/photos` (o una sua sottocartella),
senza supporre che il percorso della cartella host coincida con quello del container.

Alla chiusura del nucleo i worker ricevono l'annullamento e vengono attesi prima
di disporre il database. La GUI lascia fino a 35 secondi al processo di cui e'
proprietaria, cosi' puo' terminare anche una lettura di metadati con timeout di 30 s.
Un nucleo esterno non viene arrestato chiudendo la GUI. La generazione OpenAPI usa
`scripts/openapi-client.yaml` per trattare le risposte JPEG come file binari; il
client generato non richiede modifiche manuali.

## Sessioni salvate nella GUI

Il selettore mostra le sessioni del catalogo del **nucleo connesso**, dalla piu'
recente, con data, percorso sorgente, stato e numero di scatti. L'elenco si aggiorna
alla connessione e dopo un'importazione completata o annullata; **Aggiorna sessioni**
permette di ricaricarlo manualmente. Le sessioni restano disponibili dopo il riavvio.

Selezionare una voce e premere **Apri sessione**: la GUI carica scatti paginati,
miniature, metadati ed esclusioni attraverso le API esistenti. Non richiede che il
percorso sorgente esista sull'host desktop o che gli originali siano ancora online:
le miniature gia' in cache restano consultabili. La vista viene sostituita solo
dopo un caricamento riuscito; gli errori conservano gli scatti gia' visualizzati
e consentono di riprovare. Le sessioni in importazione o analisi non vengono aperte.

Questa funzione consulta il catalogo persistente, **non riprende job interrotti**
e non avvia analisi AI o nuove importazioni.

## Esposizione delle anteprime (primo incremento di FR-017)

Selezionare uno scatto nella GUI e premere **Misura esposizione (anteprima)**
nel pannello Dettagli. La richiesta usa il client generato in un thread separato;
la finestra resta navigabile. Il risultato e' salvato in SQLite, incluso nelle
pagine degli scatti e ricaricato alla riapertura della sessione.

```bash
uv run shotkeepr-core photos exposure SESSION_UUID --data-dir data/catalog
uv run shotkeepr-core photos show SESSION_UUID --data-dir data/catalog
```

Il comando CLI misura tutta la sessione: avanzamento su stderr e riepilogo JSON
su stdout. Ogni misura e' persistita per scatto: se un'anteprima manca o e' corrotta,
il comando restituisce 1 senza stampare un riepilogo di successo, ma conserva le
misure gia' completate. Una nuova esecuzione le riusa se sono ancora valide.

| Metodo e percorso `/api/v1` | Risultato |
|---|---|
| `POST /photos/shots/{shot_id}/exposure` | Misura o riuso verificato dell'esposizione |
| `GET /photos/shots/{shot_id}/exposure` | Ultima misura salvata; HTTP 404 se assente |

Entrambe le rotte richiedono il token bearer. Il metodo `preview-rgb-exposure-v1`
usa esclusivamente miniature JPEG fino a 512 pixel e 2 MiB, senza aprire gli
originali: alte luci = quota dei pixel con almeno un canale RGB >= 250;
ombre = quota dei pixel con tutti i canali <= 5; luminosita' media = media di
`(0.2126 R + 0.7152 G + 0.0722 B) / 255`. L'indice euristico e'
`100 * (1 - quota_alte_luci - quota_ombre)`, **non un voto fotografico complessivo**.
Non misura gamma dinamica o clipping del sensore RAW, non compensa profili colore
e non distingue scelte artistiche come low-key/high-key da errori di esposizione.

La misura registra SHA-256 dell'anteprima, impronta del file scelto, versione del
metodo e data UTC. `POST` controlla il contenuto attuale della cache e ricalcola
solo se anteprima, impronta o metodo sono cambiati; un errore non sovrascrive il
risultato precedente. `GET`, `photos show` e le pagine del catalogo leggono lo
storico salvato senza verificarlo o ricalcolarlo. Nelle coppie RAW+JPEG si preferisce
l'anteprima del JPEG, come per la miniatura della GUI. Lo stato della sessione e
il checkpoint non cambiano: non si dichiara `ANALYZED`, non si calcolano fuoco,
mosso, rumore, occhi o estetica e non si assegnano decisioni Tenuta/Scartata.

## Revisione manuale e sidecar XMP

Nel pannello Dettagli scegliere **Tenuta**, **Scartata** o **Da rivedere** e premere
**Salva decisione manuale**. La griglia mostra lo stato solo dopo il salvataggio
riuscito; gli errori non cambiano la decisione visualizzata. Decisioni e cronologia
dei cambiamenti sono pubblicate insieme in SQLite e restano disponibili dopo il
riavvio, anche con originali offline. Una richiesta identica non duplica la cronologia.
Il filtro sopra la griglia riguarda soltanto gli scatti delle pagine gia' caricate:
**Carica altri scatti** amplia l'insieme, senza modificare la sessione.

**Esporta XMP dello scatto...** richiede conferma e usa la decisione gia' salvata,
non un valore appena cambiato nel selettore ma non salvato. Scrive i sidecar nel
filesystem del **nucleo**, accanto agli originali, mai nel filesystem del desktop.
La revisione manuale non richiede ExifTool; l'export si'. Gli originali devono essere
online e avere contenuto e dimensione identici a quelli importati.

**Esporta XMP della sessione...** include tutti gli scatti della sessione aperta,
anche fuori dal gruppo corrente, nascosti dal filtro di revisione o non ancora
caricati. La conferma, predefinita su No, dichiara esplicitamente che sono inclusi
anche Scartata e Da rivedere. Gli stati sono letti dal catalogo, non dal selettore
non salvato nel pannello Dettagli, e verificati dal nucleo prima di ciascuna scrittura.
La GUI mostra avanzamento e conteggio dei sidecar senza cambiare selezione o filtri.
**Ferma export** si arresta dopo la richiesta in corso: nessun rollback degli XMP
gia' scritti. In caso di errore si interrompe senza ripetere automaticamente le
richieste; il conteggio comprende solo risposte di scrittura confermate. Un timeout
lascia ignoto l'esito della richiesta in corso: verificare i sidecar nel nucleo prima
di avviare un nuovo export, che richiede nuovamente conferma. L'operazione non e'
atomica per sessione e non continua in modo autonomo dopo la chiusura della GUI.

```bash
uv run shotkeepr-core photos review SHOT_UUID KEEP --data-dir data/catalog
uv run shotkeepr-core photos review SHOT_UUID REJECT --data-dir data/catalog
uv run shotkeepr-core photos review SHOT_UUID REVIEW --data-dir data/catalog
uv run shotkeepr-core photos export-xmp SESSION_UUID --data-dir data/catalog          # solo piano
uv run shotkeepr-core photos export-xmp SESSION_UUID --write --data-dir data/catalog  # scrive davvero
```

Il comando di sessione pianifica tutti i percorsi prima di scrivere, senza analisi
AI e senza scritture sugli originali. Il piano e' JSON su stdout; durante la scrittura
i percorsi completati sono riportati su stderr. Un errore restituisce 1 e non produce
un riepilogo di successo: i sidecar gia' pubblicati restano, con i progressi necessari
per identificarli. La pubblicazione e' atomica **per sidecar**, non per intera sessione.

| Stato | `xmp:Rating` | `xmp:Label` |
|---|---:|---|
| Tenuta (`KEEP`) | 5 | Green |
| Scartata (`REJECT`) | -1 | Red |
| Da rivedere (`REVIEW`, anche senza decisione salvata) | 0 | Yellow |

Questa prima mappatura e' fissa: le stelle non sono punteggi AI. Lo stato di scarto
usa il valore XMP standard -1, non flag proprietari pick/reject. La visualizzazione
di etichette e sidecar JPEG dipende dalle impostazioni del software fotografico;
la compatibilita' end-to-end con Lightroom/Capture One resta da convalidare.

Il sidecar e' `nome-base.xmp`; una coppia RAW+JPEG dello stesso scatto condivide
un solo sidecar, mentre eventuali copie in cartelle diverse ricevono ciascuna il
proprio. Sidecar esistenti vengono elaborati da ExifTool su copie temporanee:
si aggiornano solo Rating/Label, preservando didascalie, regolazioni e altri campi.
Si conserva la grafia di un sidecar esistente (`.XMP` incluso). File corrotti,
symlink, percorsi fuori dalla sorgente, originali cambiati e nomi XMP condivisi
da scatti distinti sono rifiutati. Lock nel catalogo coordinano gli export del nucleo;
modifiche esterne rilevate prima della pubblicazione interrompono il merge senza
sovrascriverle. Un errore di rete dalla GUI lascia l'esito dell'export **non noto**:
verificare i sidecar nel nucleo prima di riprovare.

| Metodo e percorso `/api/v1` | Risultato |
|---|---|
| `GET /photos/shots/{shot_id}/review` | Stato salvato o default Da rivedere |
| `PUT /photos/shots/{shot_id}/review` | Salva `status`: `KEEP`, `REJECT` o `REVIEW` |
| `POST /photos/shots/{shot_id}/xmp` | Merge esplicito con `confirm: true` e `expected_status` |

Tutte le rotte richiedono il token bearer; le pagine del catalogo e `photos show`
includono la revisione. Una decisione diversa da `expected_status` restituisce 409.
Revisione ed export non promuovono la sessione ad `ANALYZED` e non eliminano foto.
Raggruppamento per similarita' visiva e selezione automatica AI non sono ancora implementati.

In Docker il mount foto predefinito resta in sola lettura. Per autorizzare gli XMP,
usare esplicitamente l'override dedicato (ed eventualmente quello CUDA):

```bash
SHOTKEEPR_PHOTOS_DIR=/percorso/assoluto/foto \
  docker compose -f docker/compose.yaml -f docker/compose.xmp.yaml up --build -d --wait
```

L'utente del container deve avere permessi di scrittura sulla cartella e sui sidecar.
Gli altri mount, il filesystem del container e i vincoli di sicurezza non cambiano.

## Raffiche temporali persistenti

Aprire una sessione salvata, impostare **Intervallo raffica** e premere
**Raggruppa raffiche**. L'operazione usa soltanto i metadati del catalogo, senza
aprire originali o anteprime: funziona anche offline e non richiede modelli AI.
La GUI resta responsiva e ricarica la sessione solo dopo una pubblicazione riuscita.
I gruppi, il metodo e la soglia vengono conservati dopo il riavvio del nucleo.

```bash
uv run shotkeepr-core photos group SESSION_UUID --gap-seconds 2 --data-dir data/catalog
uv run shotkeepr-core photos show SESSION_UUID --data-dir data/catalog
```

Il metodo `camera-time-bursts-v1` ordina gli scatti per ora UTC e identificativo,
separatamente per coppia **modello + seriale** fotocamera. Unisce scatti consecutivi
con intervallo **minore o uguale** alla soglia (default 2 s, ammessi 0.01-60 s);
la raffica puo' quindi durare piu' della soglia complessiva. Ogni raffica contiene
almeno due scatti. RAW+JPEG rimane una sola unita' di selezione. Le sottocartelle
non separano automaticamente scatti della stessa fotocamera.

Modello, seriale o ora mancanti/contraddittori non vengono inventati: lo scatto
resta **Senza raffica**, insieme agli scatti isolati. Non si assume che due corpi
dello stesso modello siano la stessa fotocamera se manca il seriale. Orari senza
offset mantengono la convenzione UTC gia' adottata in importazione, non un fuso
accertato. Non si riconoscono similarita' visiva, quasi-duplicati o cluster semantici.

Il selettore sopra la griglia offre tutte le raffiche della sessione, con numero
di scatti, fotocamera e ora iniziale; **Senza raffica** mostra gli scatti indipendenti.
Il filtro del gruppo avviene nel nucleo **prima** della paginazione: Carica altri
scatti continua lo stesso gruppo. Il filtro Tenuta/Scartata/Da rivedere resta invece
limitato alle pagine caricate nella vista corrente. Un cambio gruppo fallito conserva
la vista precedente e ripristina il selettore. Se il raggruppamento e' salvato ma la
ricarica fallisce, la GUI lo segnala e permette di riaprire la sessione.

| Metodo e percorso `/api/v1` | Risultato |
|---|---|
| `GET /photos/sessions/{session_id}/groups` | Raffiche, soglia, metodo, data e numero di scatti senza raffica |
| `POST /photos/sessions/{session_id}/groups/bursts` | Ricalcolo esplicito con body `gap_seconds` |
| `GET /photos/sessions/{session_id}/shots?group_id=GROUP_UUID` | Scatti paginati della raffica |
| `GET /photos/sessions/{session_id}/shots?ungrouped=true` | Scatti paginati senza gruppo |

Tutte le rotte sono autenticate. Gruppi sconosciuti o di un'altra sessione ricevono
404; `group_id` e `ungrouped=true` non sono combinabili. I dettagli della sessione
includono il riepilogo dei gruppi, gli scatti includono `group_id` e `photos show`
mostra entrambi. La lettura non avvia un raggruppamento automaticamente.

Gruppi e appartenenze vengono sostituiti insieme in una sola transazione SQLite:
un errore conserva il risultato precedente. Gli ID sono stabili a parita' di membri;
un ricalcolo identico conserva anche la data. Decisioni manuali, cronologia, misure
di esposizione, stato e checkpoint della sessione non cambiano. Il ricalcolo e'
consentito su sessioni IMPORTED/ANALYZED e rifiuta gruppi manuali/non temporali,
correzioni o run di selezione preesistenti per non invalidarli silenziosamente.

## Nitidezza globale dell'anteprima (CLI, API e GUI)

```bash
uv run shotkeepr-core photos sharpness SESSION_UUID --data-dir data/catalog
uv run shotkeepr-core photos show SESSION_UUID --data-dir data/catalog
```

Il comando misura il dettaglio globale dei JPEG in cache, senza aprire gli originali
o scaricare modelli. Il metodo `preview-luma-laplacian-v1` usa luminanza normalizzata
`Y = (0.2126 R + 0.7152 G + 0.0722 B) / 255`: riporta la varianza del Laplaciano
a quattro vicini, escludendo il bordo, e la media delle energie delle differenze
orizzontali/verticali. Le anteprime devono essere JPEG tra 3 e 512 pixel per lato,
di dimensione non superiore a 2 MiB.

Questi indicatori **non sono un voto fotografico ne' una verifica del fuoco del
soggetto**: texture, contrasto, rumore, compressione e risoluzione possono aumentarli
o ridurli. Non individuano occhi o regioni del soggetto e non distinguono mosso,
sfocatura e scelte artistiche. Non vengono applicate soglie automatiche di scarto.

Ogni risultato e' persistito separatamente in SQLite, con impronta del file scelto,
SHA-256 dell'anteprima, versione del metodo e data UTC. Le coppie RAW+JPEG preferiscono
il JPEG, come la GUI. Una nuova misura riusa il risultato solo se contenuto, impronta
e metodo coincidono; un'anteprima mancante/corrotta non sovrascrive il risultato
precedente. `photos show` consulta lo storico senza ricalcolarlo.

Progressi su stderr e riepilogo JSON su stdout; un errore restituisce 1 senza un
riepilogo di successo e conserva le misure gia' completate. Stato, checkpoint,
esposizione, gruppi e decisioni manuali non cambiano; l'analisi AI resta separata.

Nella GUI selezionare uno scatto e premere **Misura nitidezza (anteprima)** nel
pannello Dettagli. Il client generato esegue la richiesta in un thread separato:
la finestra resta navigabile e la risposta aggiorna soltanto lo scatto richiesto,
anche se la selezione corrente cambia. Un errore conserva il risultato precedente
e permette di riprovare, senza presentare un nuovo valore come salvato.
Il pannello scorre per rendere consultabili insieme metadati, esposizione e nitidezza
su schermi 1366x768. Alla riapertura della sessione, la GUI legge le misure salvate;
non esegue analisi automaticamente e non richiede gli originali online.

Il pulsante **Misura anteprime della sessione** percorre tutte le pagine del
catalogo, ignorando i filtri di raffica e di revisione della vista corrente.
Richiede esposizione e nitidezza per ogni scatto di una sessione importata o
analizzata. La barra conta gli scatti per cui entrambe le richieste sono riuscite;
la griglia resta navigabile e i valori salvati aggiornano gli scatti gia' caricati
senza cambiare selezione, filtro o posizione di paginazione.

**Ferma misure** arresta l'operazione tra richieste: la richiesta gia' in corso
puo' ancora completarsi. Le misure parziali restano salvate nel nucleo, anche se
di uno scatto e' stata misurata solo l'esposizione. Un errore interrompe il batch,
mostra la causa e il numero di scatti completati, senza dichiarare un successo.
Riavviare ripercorre la sessione e riusa le misure con impronta, anteprima e metodo
invariati; non esiste un job batch autonomo che continui dopo la chiusura della GUI.
Lo stato della sessione, i gruppi e le decisioni manuali non vengono modificati;
queste misure non costituiscono analisi AI completa o selezione automatica.

| Metodo e percorso `/api/v1` | Risultato |
|---|---|
| `POST /photos/shots/{shot_id}/sharpness` | Misura o riuso verificato della nitidezza globale |
| `GET /photos/shots/{shot_id}/sharpness` | Ultima misura salvata, senza rilettura dell'anteprima |

Entrambe le rotte richiedono il token bearer. HTTP 404 indica scatto/risultato assente,
409 un'anteprima inutilizzabile, 503 servizio non configurato o catalogo non disponibile.
Le pagine degli scatti includono `sharpness`, nullo se non misurato o non configurato.
La risposta riporta varianza, energia, dimensioni, versione e provenienza: nessun voto
0-100, classificazione del soggetto o decisione automatica viene derivato dalla misura.
