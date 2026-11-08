# Änderungen

## 4.0.0 — 08.11.2026

Version 4 ist ein Umbau desselben Projekts. Der Anzeigename ist „Pforte“. Die Versionen bis 3.0.0-beta.1 stehen in den Zweigen `main` und `beta`.

- **Assistent beim ersten Start.** OPNsense ist Pflicht, AdGuard und Portainer sind optional. Jeder Zugang wird sofort getestet.
- **Ein Bildschirm zum Anlegen.** Name, Domain, Ziel, Anlegen. Die Domains stammen aus den ACME-Zertifikaten der OPNsense.
- **Eingang vorgewählt.** Der Public Service auf Port 443 mit den meisten Regeln ist gesetzt, die übrigen stehen in einer Auswahl.
- **Containervorschläge aus Portainer.** Beim Ziel erscheinen laufende Container mit ihrem Port.
- **Alles oder nichts.** Bei einem Fehler oder einer abgelehnten HAProxy-Konfiguration wird alles Angelegte zurückgenommen.
- **Eigenes Fenster mit Web-Oberfläche statt Tk.** Unter Linux ein natives GTK-Fenster, unter Windows ein Edge-App-Fenster, sonst der Browser. Das Programm braucht weiterhin nur Python.
- **Update aus dem Programm.** Neben dem Namen erscheint „Update x.y.z“, ein Klick installiert und startet neu. Die alte Version wird gesichert.
- **Von älteren Versionen aus erreichbar.** Der Updater von 1.x bis 3.x holt Version 4 selbst, auch auf der Beta-Schiene. Einstellungen lassen sich übernehmen.
- **Zwei Spalten, Hosts bearbeiten.** Links entsteht der neue Host, rechts stehen die vorhandenen mit Suche. Name, Ziel und Eingang lassen sich ändern, der DNS-Eintrag zieht mit.
- **Flüssiger.** Der animierte Weichzeichner im Hintergrund kostete zwei Drittel der Bildrate und ist ersetzt.
- **Entfernt:** Katalog, Stack-Verwaltung, Status-Kette, Updater, Dockhand und Git-Konten.
