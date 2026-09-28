# ADR-010: Lettura RAW con rawpy/LibRaw e metadati/XMP con ExifTool

**Status:** Accepted

**Context:** RAW di tutti i principali produttori; sidecar XMP compatibili con Lightroom/Capture One preservando i campi esistenti; originali mai alterati.

**Decision:** La decodifica usa rawpy (LibRaw) per la decodifica e preferisce l'anteprima JPEG incorporata quando la risoluzione è sufficiente per l'analisi; Pillow (con pillow-heif) per i formati standard. Catalogo ed esportazione usano ExifTool (processo persistente `-stay_open`) per leggere EXIF e per il merge dei sidecar XMP (`xmp:Rating`, `xmp:Label`, stato pick/reject). Scrittura atomica (file temporaneo + rename) e verifica dell'impronta degli originali prima/dopo ogni export.

**Alternatives Considered:** pyexiv2 (binding meno portabili, GPL); scrittura XMP manuale (rischio di perdere campi esistenti).

**Consequences:** + Copertura ampia dei formati e compatibilità con i cataloghi. − ExifTool va incluso nell'immagine `core` e nella distribuzione nativa.
