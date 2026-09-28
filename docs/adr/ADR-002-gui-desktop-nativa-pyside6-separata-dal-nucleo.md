# ADR-002: GUI desktop nativa PySide6 separata dal nucleo

**Status:** Accepted

**Context:** Serve una GUI desktop nativa in Python, eseguita sull'host e non dentro Docker; servono griglie con migliaia di miniature, confronto con zoom sincronizzato, HiDPI e temi.

**Decision:** La GUI è un'applicazione PySide6 (Qt 6, LGPL, compatibile con l'AGPL e con la licenza commerciale) eseguita sull'host e distribuita con PyInstaller per Windows, macOS e Linux. Usa esclusivamente l'API del nucleo; vista griglia con `QListView` virtualizzata e cache di miniature, confronto con `QGraphicsView` sincronizzate.

**Alternatives Considered:** PyQt6 (GPL: incompatibile con la licenza commerciale); Electron/Tauri (non Python); NiceGUI/pywebview (non nativo); Flet/Kivy/Tkinter (meno adatti a un viewer fotografico professionale).

**Consequences:** + Prestazioni e resa nativa su tutti i sistemi operativi. + Tema chiaro/scuro con palette neutre. − Packaging e firma del codice per tre piattaforme da gestire in CI.
