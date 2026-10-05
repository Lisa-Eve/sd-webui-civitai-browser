# CivitAI Browser+ (Lisa-Eve fork)

Eine Weiterentwicklung von [sd-civitai-browser-plus](https://github.com/BlafKing/sd-civitai-browser-plus)
für Stable Diffusion WebUI / Forge. Das Originalprojekt wird vom Autor nicht mehr
gepflegt — diese Version ist der gepflegte Stand.

## Was diese Version anders macht

**Downloads**
- Downloads laufen in `.civitai-part`-Dateien und werden erst nach Erfolg unter dem
  endgültigen Modellnamen abgelegt. Ein abgebrochener Download hinterlässt keine
  halbe Datei im Modellordner.
- Ein erneuter Versuch nutzt den bereits geladenen Teil weiter.
- Vor dem Download wird der freie Platz des Ziellaufwerks geprüft, mit 512 MiB Reserve.
  Liefert CivitAI keine Dateigröße, wird nur die Reserve geprüft.
- Die Warteschlange bleibt auch nach einem Fehler benutzbar. Ein Fehler beendet den
  aktuellen Eintrag und räumt den internen Zustand auf, statt das Tool dauerhaft zu
  blockieren.

**Metadaten**
- Modell- und Info-JSONs werden atomar ersetzt (tempfile + fsync + os.replace).
  Ein fehlgeschlagener Schreibvorgang lässt die alte Datei unangetastet.
- Leere oder beschädigte `.cm-info.json`-Dateien anderer Erweiterungen werden nicht
  als CivitAI-Modellmetadaten gelesen. Sie werden weder gelöscht noch repariert.
- Der SHA256 wird auch dann gespeichert, wenn die Sidecar-JSON beschädigt ist.

**Update-Scan**
- Der Scan betrachtet standardmäßig nur neuere Versionen derselben
  `baseModel`-Variante wie die installierte. Die Checkbox im Reiter
  **Update Models** zählt andere Varianten ausdrücklich mit.
- Welche Version installiert ist, wird über den Dateinamen *und* den SHA256
  erkannt. Vorher konnte nur der Hash greifen, Modelle ohne gespeicherten Hash
  galten fälschlich als nicht installiert.
- **Select all loaded updates** markiert alle geladenen Update-Ergebnisse.
  **Queue all found updates** reiht alle Ergebnisse des Scans über sämtliche
  Ergebnisseiten ein.

**Versionen-Verwaltung**
- **Show installed versions per model** listet im Update-Reiter pro Model alle
  Versionen mit Base-Model, Version-ID, Dateien und Zustand. Damit lässt sich
  vor dem Entfernen sehen, welche alten Versionen noch installiert sind.
- Mehrere ausgewählte Versionen lassen sich gesammelt in den Papierkorb geben.
  Gelöscht wird **erst nach ausdrücklicher Bestätigung** und ausschließlich über
  den Papierkorb, nicht endgültig.

**Diagnose**
- Extended Logging inklusive rotierender Logdatei.
- **Copy diagnostics** erzeugt einen Textbericht mit Version, Pfaden, Laufzeit und
  den letzten Logzeilen — ohne Zugangsdaten.

## Installation mit bestehenden Einstellungen

1. Stable Diffusion WebUI/Forge vollständig beenden.
2. Den bisherigen Erweiterungsordner und die WebUI-Dateien `config.json`,
   `ui-config.json` sowie `config_states/civitai_subfolders.json` sichern. Diese
   Konfigurationsdateien können je nach Installation an einem anderen
   WebUI-Arbeitsverzeichnis liegen.
3. Den bisherigen Erweiterungsordner durch diese Version ersetzen und dabei
   denselben Ordnernamen beibehalten: `sd-civitai-browser-plus`.
4. WebUI/Forge starten. Die bisherigen `civitai_*`-Optionen bleiben unverändert;
   es ist keine Einstellungsumwandlung nötig. Modellordner und Sidecar-Dateien
   werden bei der Installation nicht verändert.

## Tests

```bash
python3 -m unittest discover -s tests
```

Hinweis: `python3 -m unittest tests.test_regressions` funktioniert **nicht**, weil
`tests/` bewusst kein `__init__.py` hat. Nutze `discover -s tests`.

Die Testsuite läuft ohne WebUI/Gradio, weil die reine Logik über AST-Isolation
einzeln geladen wird. Der Import der Extension selbst benötigt die WebUI-Laufzeit
(`modules.shared`).

## Bekannte Grenzen

Ein vollständiger Test in einer laufenden Forge-Installation ist nicht möglich.
Der Download-Pfad ist über Argumentaufbau und Zustandslogik abgedeckt, ein echter
Download mit laufendem aria2 und echter CivitAI-Antwort nicht.

---

## Über das Originalprojekt

Dieses Repository ist ein Fork. Das Original — ein Gradio-Plugin für die CivitAI-API —
wird vom Autor nicht weiterentwickelt und steht unter **AGPL-3.0**.

Das Original-Projekt: <https://github.com/BlafKing/sd-civitai-browser-plus>

Der Autor empfahl dort die Weiterentwicklung
[SignalFlagZ/sd-civbrowser](https://github.com/SignalFlagZ/sd-civbrowser), auf die
dieses Projekt ursprünglich zurückgeht. Beide Projekte sind eigenständige
Implementierungen mit unterschiedlichen Ansätzen.
