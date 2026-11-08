# Änderungen

## 4.0.0-dev

Neuanfang als Pforte. Die Versionen bis 3.0.0-beta stehen in den Zweigen `main` und `beta`.

- **Assistent beim ersten Start.** OPNsense ist Pflicht, AdGuard und Portainer sind optional. Jeder Zugang wird sofort getestet.
- **Ein Bildschirm zum Anlegen.** Name, Domain, Ziel, Anlegen. Die Domains stammen aus den ACME-Zertifikaten der OPNsense.
- **Eingang vorgewählt.** Der Public Service auf Port 443 mit den meisten Regeln ist gesetzt, die übrigen stehen in einer Auswahl.
- **Containervorschläge aus Portainer.** Beim Ziel erscheinen laufende Container mit ihrem Port.
- **Alles oder nichts.** Bei einem Fehler oder einer abgelehnten HAProxy-Konfiguration wird alles Angelegte zurückgenommen.
- **Oberfläche im Browser statt in Tk.** Das Programm braucht weiterhin nur Python.
- **Entfernt:** Katalog, Stack-Verwaltung, Status-Kette, Updater, Dockhand und Git-Konten.
