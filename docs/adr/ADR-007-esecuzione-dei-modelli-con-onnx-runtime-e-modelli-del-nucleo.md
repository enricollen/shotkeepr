# ADR-007: Esecuzione dei modelli con ONNX Runtime e modelli del nucleo a licenza compatibile

**Status:** Accepted

**Context:** Tutte le funzioni devono girare solo su CPU; i modelli del nucleo devono avere licenze compatibili con l'AGPL e con la licenza commerciale; approccio ibrido deterministico + AI.

**Decision:** I modelli del nucleo sono esportati in ONNX ed eseguiti con ONNX Runtime (CPU; CUDA o CoreML se disponibili), eventualmente quantizzati INT8 su CPU. Nucleo: embedding SigLIP/OpenCLIP (semantica e criteri) e DINOv2 (quasi-duplicati), rilevamento persone/animali RF-DETR, volti e occhi MediaPipe Face Landmarker, estetica tramite predittore leggero sugli embedding CLIP (MIT). Le misure deterministiche usano OpenCV/NumPy (varianza del Laplaciano e gradienti sulla regione del soggetto, analisi spettrale del mosso, istogrammi, stima del rumore). I pesi sono scaricati al primo avvio con verifica dell'hash e registrati nel manifest delle licenze. InsightFace e pyiqa sono disponibili solo come plugin non commerciali ([ADR-008](ADR-008-plugin-come-pacchetti-python-firmati-eseguiti-in-processo-is.md)).

**Alternatives Considered:** PyTorch in produzione (immagini più pesanti, CPU più lenta); modelli non commerciali nel nucleo (licenze incompatibili).

**Consequences:** + Stesse prestazioni e risultati su tutti gli OS (tolleranza ≤ 1%). − Pipeline di conversione ONNX da mantenere; accuratezza dei modelli a licenza permissiva da validare.
