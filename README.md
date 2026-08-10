# opnsense-haproxy

Neue Webseite im Heimnetz erreichbar machen — mit einem Fenster, ein paar
Feldern und einem Knopf, statt mit fünf Formularen in der OPNsense-Oberfläche.

<img src="icon.png" alt="" width="96">

## Worum geht es hier?

Auf deiner OPNsense läuft **HAProxy**. Das ist ein Türsteher: Alle Anfragen aus
dem Netz kommen bei ihm an, und er entscheidet anhand des Namens, an welchen
Rechner dahinter sie weitergereicht werden. `wiki.example.com` geht an den
einen Server, `cloud.example.com` an den anderen — nach außen ist es dieselbe
Adresse und dasselbe Zertifikat.

Damit HAProxy einen neuen Namen kennt, müssen in OPNsense nacheinander vier
Dinge angelegt werden — Real Server, Backend Pool, Condition und Rule — und die
Rule muss danach noch beim Public Service eingehängt werden. Wer das zum ersten
Mal macht, sucht sich die Formulare zusammen; wer es zum zwanzigsten Mal macht,
hat keine Lust mehr darauf.

Dieses Programm macht alle vier Schritte auf einmal. Du tippst den Namen und
die IP-Adresse des Servers ein, klickst **Anlegen**, und es prüft anschließend
die Konfiguration und lädt HAProxy neu. Geht unterwegs etwas schief, wird alles
bereits Angelegte wieder entfernt — es bleibt nichts Halbfertiges zurück.

Auf Wunsch trägt es zusätzlich den passenden DNS-Eintrag in **AdGuard Home**
ein, damit der neue Name im Heimnetz auch gefunden wird.

Und weil die Dienste, die hinter HAProxy stehen, meist Docker-Container sind,
gibt es oben einen zweiten Tab: **Portainer**. Er zeigt, welche Stacks laufen
und welche Ports sie auf dem Host veröffentlicht haben — also genau die Ports,
die HAProxy ansprechen kann. Von dort aus lassen sich Stacks aus GitHub oder
GitLab ausrollen — aus einem **Katalog** bekannter Stacks, aus eigenen
Favoriten oder aus der Liste der eigenen Repositories —, mit einem Klick neu
deployen (auf Wunsch mit frischen Images) und wieder löschen, samt der
HAProxy-Einträge, die auf sie zeigten. Ein veröffentlichter Port wandert mit
**→ HAProxy** direkt in den ersten Tab.

**Du brauchst dafür kein Terminal.** Die ganze Anleitung unten funktioniert mit
der Maus. (Wer lieber tippt, findet die Kommandozeile ganz unten.)

---

## Was du vorher brauchst

Drei Häkchen, bevor es losgeht:

* **OPNsense mit HAProxy.** Unter *System → Firmware → Plugins* muss
  `os-haproxy` installiert sein, und HAProxy muss laufen.
* **Mindestens einen Public Service.** Das ist der Eingang, an dem HAProxy auf
  Port 443 lauscht (in OPNsense unter *Services → HAProxy → Settings → Public
  Services*). Den legt dieses Programm **nicht** an — es hängt seine Regeln nur
  dort ein. Wenn du HAProxy schon benutzt, hast du ihn längst.
* **Einen Rechner mit Windows oder Linux**, von dem aus du die OPNsense-
  Oberfläche erreichst. Dort läuft dieses Programm.

Schön, aber nicht nötig: der **ACME-Client** (Plugin `os-acme-client`) für
Let's-Encrypt-Zertifikate. Wenn du ihn hast, bietet dir das Programm deine
Domains zur Auswahl an und du tippst nur noch `wiki` statt
`wiki.home.example.com`.

---

## Schritt 1: Python installieren

Das Programm ist in Python geschrieben. Einmalig muss Python auf deinem Rechner
sein — danach nie wieder.

**Windows:** [python.org/downloads](https://www.python.org/downloads/) öffnen,
den großen gelben Knopf drücken, die heruntergeladene Datei starten. Wichtig:
im ersten Fenster des Installers ganz unten **„Add python.exe to PATH"**
ankreuzen, erst dann auf *Install Now*. Ohne dieses Häkchen findet Windows
Python später nicht.

**Linux:** Python ist schon da. Es fehlt nur die Fenster-Bibliothek; unter
Debian, Ubuntu oder Mint installiert sie die Paketverwaltung als `python3-tk`.
Falls sie fehlt, sagt dir das Programm beim Start genau das.

**Mac:** funktioniert ebenfalls (Python von python.org installieren), ist aber
weniger getestet als Windows und Linux.

## Schritt 2: Programm herunterladen

**[opnsense-haproxy-2.6.0.zip](https://github.com/DukyNuky/opnsense-haproxy-config/releases/latest/download/opnsense-haproxy-2.6.0.zip)**
herunterladen und **entpacken** — in einen Ordner deiner Wahl, zum Beispiel
`Dokumente\opnsense-haproxy`. Nicht direkt im ZIP starten, sonst findet das
Programm seine eigenen Dateien nicht.

Alle Fassungen liegen unter
[Releases](https://github.com/DukyNuky/opnsense-haproxy-config/releases), und
was sich zuletzt geändert hat, steht im
[Änderungsverzeichnis](CHANGELOG.md).

## Schritt 3: Programm starten

**Windows:** im entpackten Ordner **`HAProxy-Starter.bat`** doppelklicken.

Meldet Windows „Der Computer wurde durch Windows geschützt", ist das der
SmartScreen-Filter, der jede unbekannte Datei anhält: *Weitere Informationen* →
*Trotzdem ausführen*. Fehlt Python oder ist es zu alt, sagt der Starter das im
Klartext, statt sich wortlos zu schließen.

**Linux:** `haproxy_gui.py` doppelklicken (im Dateimanager ggf. „Ausführen"
bestätigen).

Es geht ein Fenster auf und fragt nach deinen Zugangsdaten. Die holen wir uns
jetzt.

## Schritt 4: In OPNsense einen Benutzer und einen Schlüssel anlegen

Das Programm meldet sich nicht mit deinem Passwort an der OPNsense an, sondern
mit einem **API-Schlüssel**. Das ist ein Paar aus zwei langen Zeichenketten —
*Key* und *Secret* —, das nur für Programme gedacht ist und genau die Rechte
hat, die du dem zugehörigen Benutzer gibst.

Wichtig ist die Reihenfolge: **erst der Benutzer, dann der Schlüssel.** Der
Schlüssel wird dem fertigen Benutzer angehängt — und zwar aus der
Benutzer*übersicht* heraus, nicht aus der Maske, in der du ihn gerade
bearbeitest. Das ist die Stelle, an der die meisten suchen.

**4a — Benutzer anlegen.** In der OPNsense-Oberfläche zu
**System → Zugriff → Benutzer** gehen und rechts unten das **+** drücken.

* *Benutzername*: zum Beispiel `haproxy-tool`.
* *Passwort*: irgendetwas Langes. Du wirst es nie brauchen — angemeldet wird
  sich mit dem Schlüssel.
* Bei *Anmeldeshell* nichts ändern.

Unten **Speichern**.

**4b — Rechte geben.** Den Benutzer wieder öffnen (das Stift-Symbol rechts in
seiner Zeile) und zum Abschnitt **Effektive Berechtigungen** (*Effective
Privileges*) scrollen. Über das **+** daneben zwei Rechte hinzufügen:

| Recht | wofür |
| --- | --- |
| **Services: HAProxy** | zwingend — ohne das geht gar nichts. |
| **Services: ACME Client** | liest die Zertifikate für die Domain-Auswahl. Fehlt es, bleibt die Liste leer und du tippst den ganzen Namen selbst; alles andere funktioniert weiter. |

Wieder **Speichern**. Die Rechte hängen am *Benutzer*, nicht am Schlüssel — ein
Schlüssel kann nie mehr als sein Benutzer.

**4c — Schlüssel erzeugen.** Der Schlüssel wird **nicht** in der
Bearbeitungsmaske angelegt — dort steht nichts davon. Zurück in der
**Benutzerübersicht** (*System → Zugriff → Benutzer*): ganz rechts in der Zeile
deines Benutzers stehen ein paar kleine Symbole. Eines davon sieht aus wie ein
Viereck mit gezacktem Rand, wie eine **Briefmarke** — das ist „API-Schlüssel
erstellen". Ein Klick darauf, und der ganze Vorgang ist erledigt: OPNsense legt
den Schlüssel an und lädt sofort eine kleine Textdatei namens **`apikey.txt`**
herunter (schau im Download-Ordner deines Browsers). Darin stehen zwei Zeilen:

```
key=Ab3dEf…
secret=Xy9zQ…
```

**Diese Datei ist deine einzige Gelegenheit.** Das Secret zeigt OPNsense nie
wieder an. Ist sie weg, klickst du einfach noch einmal auf die Briefmarke — das
kostet nichts, du hast dann nur zwei Schlüssel und kannst den alten löschen.

## Schritt 5: Verbindung eintragen

Zurück im Programm-Fenster, das seit Schritt 3 wartet. Es zeigt die
**Einstellungen** mit vier Abschnitten untereinander — **OPNsense**, **AdGuard
Home**, **Portainer** und **Git-Konto**. Jeder führt seine eigene Liste, und
jeder hat ein **＋ Hinzufügen**. Für den Anfang genügt die erste OPNsense: **＋ Hinzufügen**
im obersten Abschnitt, dann füllt sich das Fenster so:

| Feld | was hinein gehört |
| --- | --- |
| **Name** | Ein Name für dich, z.B. `Zuhause`. |
| **Adresse** | Die Adresse deiner OPNsense-Oberfläche, z.B. `https://192.168.1.1` oder `https://opnsense.fritz.box`. |
| **API-Key** | Die Zeile `key=…` aus `apikey.txt` — **ohne** das `key=` davor. |
| **API-Secret** | Entsprechend die Zeile `secret=…`. Darunter steht der Weg aus Schritt 4 noch einmal in Kurzform, mit einem Link direkt auf die Benutzerverwaltung der Adresse, die du eine Zeile höher eingetragen hast. |
| **IP von HAProxy** | Die Adresse, unter der HAProxy erreichbar ist — meistens die IP deiner OPNsense, z.B. `192.168.1.1`. Darauf zeigen später die DNS-Einträge. |

Das Häkchen **TLS-Zertifikat der OPNsense prüfen** bleibt aus, solange deine
OPNsense ein selbstsigniertes Zertifikat hat (der Normalfall im Heimnetz).
Sonst schlägt die Verbindung mit einem Zertifikatsfehler fehl.

Ganz unten steht **Arbeitet zusammen mit** — die Vorauswahl, welches AdGuard
und welcher Portainer zu dieser Firewall gehören. Beim ersten Mal ist dort
nichts zu wählen; das kommt gleich.

**Speichern**, und wenn du magst gleich weiter im Abschnitt **AdGuard Home**
mit **＋ Hinzufügen**: Name, Adresse (`https://adguard.example.de`, oder mit
Port: `http://192.168.1.2:3000`), Benutzer und Passwort. Dann legt das Programm
zu jedem neuen Host auf Wunsch den DNS-Eintrag mit an. Ohne AdGuard bleibt DNS
unangetastet; nachtragen geht jederzeit.

**Fertig** schließt die Einstellungen. Ein Druck auf **Verbinden** oben rechts
holt, was auf der OPNsense schon da ist: die Anzeige wechselt von „nicht
verbunden" auf den Namen deiner Firewall, und rechts füllt sich die Liste der
bestehenden Hosts.

Deine Eingaben landen in einer Datei in deinem Benutzerprofil
(`~/.config/opnsense-haproxy/config.json`, unter Windows entsprechend), die nur
du lesen darfst.

## Schritt 6: Den ersten Host anlegen

Oben rechts über der Liste sitzt **＋ Neuer Host**. Der Knopf öffnet das
Formular in einem eigenen Fenster:

1. **Basis-Domain** aus der Liste wählen (z.B. `home.example.com`) — das sind
   deine Zertifikats-Domains. Ist die Liste leer, macht das nichts: dann trägst
   du unten einfach den vollen Namen ein.
2. **Hostname**: `wiki` — darunter steht laufend mit, welcher Name daraus wird,
   also `wiki.home.example.com`. Oder gleich der volle Name.
3. **Server-IP**: die Adresse des Rechners, der die Seite ausliefert, z.B.
   `192.168.10.20`.
4. **Port**: auf dem der Rechner lauscht, z.B. `8080`.
5. **SSL zum Backend**: aus, wenn dein Server intern nur HTTP spricht (der
   häufigste Fall). An, wenn er HTTPS erwartet. Unter dem Schalter steht immer,
   was gerade gilt.
6. **Vorschau** drücken. Das ändert noch **nichts**, sondern zeigt im Protokoll
   des Hauptfensters, was angelegt würde. Ein guter Reflex beim ersten Mal —
   das Formular bleibt dabei stehen.
7. **Anlegen**. Unten läuft mit, was passiert: die vier Objekte, das Einhängen
   in den Public Service, der Konfigurationstest, der Reload. Danach schließt
   sich das Fenster; geht etwas schief, bleibt es offen und sagt es in seiner
   Fußzeile.

Danach steht der Name in der Liste **Bestehende Hosts**. Ein Klick darauf
öffnet die Seite im Browser.

Klappt der Aufruf nicht sofort: Dein Rechner muss den Namen erst zur HAProxy-IP
auflösen können. Mit AdGuard erledigt das Programm das mit; ohne trägst du den
Namen in deinem DNS-Server oder Router selbst ein.

## Schritt 7: Ordentlich einrichten (optional, aber angenehm)

Damit das Programm nicht für immer im Download-Ordner wohnt, kann es sich
selbst an einen festen Platz legen: oben rechts **⤓ Installieren**, Zielordner
bestätigen, fertig.

Es kopiert sich dorthin, trägt sich mit seinem Symbol ins Startmenü
(Windows) bzw. ins Anwendungsmenü (Linux) ein, und von dort lässt es sich an
die **Taskleiste anheften**. Auf Wunsch legt es auch eine Verknüpfung auf den
Schreibtisch. Deine Zugangsdaten fasst es dabei nicht an.

Den ursprünglich entpackten Ordner kannst du danach löschen. Startest du das
Programm ab jetzt aus dem Menü, fehlt der Knopf **⤓ Installieren** — dort ist
nichts mehr zu installieren, und zweimal dasselbe anzubieten hilft niemandem.

---

## Das Fenster im Überblick

**Oben links** die drei großen Tabs, **HAProxy**, **Portainer** und
**AdGuard**. Dieser Abschnitt beschreibt den ersten; die anderen beiden haben
weiter unten ihren eigenen. Die Kopfzeile und das Protokoll unten gehören
allen: der Umschalter für die Verbindung, die Statusanzeige und **Verbinden**
meinen immer den Tab, der gerade vorne ist.

**Oben rechts** liegen die Knöpfe: der Umschalter für die Verbindung, das
Zahnrad ⚙ für die Einstellungen, **Verbinden**, **⇩ Update**, **⤓ Installieren**
und der Mond/Sonne-Knopf für hell oder dunkel. Was ein Knopf tut, verrät ein
Hinweis, wenn die Maus einen Moment darauf liegt.

**⤓ Installieren steht nur da, solange es etwas zu installieren gibt.** Läuft
das Programm aus dem Ordner, auf den die Starter zeigen, ist die Frage schon
beantwortet — der Knopf ist dann weg. Aus einem entpackten ZIP heraus oder aus
einer Arbeitskopie ist er da.

Der Umschalter meint immer den Tab, der vorne ist: auf **HAProxy** wählt er die
OPNsense, auf **Portainer** den Docker-Host, auf **AdGuard** den DNS-Server.
Ganz unten in seiner Liste steht **⚙ Einstellungen …** — der zweite Weg
dorthin.

**Von allein verbindet sich nichts.** Das Fenster geht auf und wartet; erst
**Verbinden** holt die Daten von der OPNsense. Danach heißt derselbe Knopf
**Neu laden**. Beim Wechsel der Firewall und nach dem Schließen der
Einstellungen wird automatisch gelesen — das ist ja schon die Ansage, dass es
losgehen soll.

**Der Tab selbst** zeigt über die ganze Breite die bestehenden Hosts, sortiert
nach Public Service. Über der Liste stehen die zwei Knöpfe, mit denen etwas
dazukommt: **＋ Neuer Host** und **＋ TCP-Listener**. Beide öffnen ein eigenes
Fenster — wie **＋ Neuer Stack** im Portainer-Tab, und aus demselben Grund: Als
Spalte am linken Rand hatte das Formular ein Drittel des Fensters für Felder,
die mehr wollen, und die Liste hatte den Rest der Zeit zu schmal zu sein.

Die Formulare sind **nicht modal**: Das Protokoll unten gehört zum Hauptfenster,
und eine **Vorschau** ist zum Lesen da, während das Formular noch steht. Fertig
angelegt schließt sich das Fenster von selbst; schlägt etwas fehl, bleibt es
offen und sagt den Grund in seiner Fußzeile.

Im Formular **Neuer Host** steht auch **DNS-Eintrag in**: Dort wählst du,
welches AdGuard den Eintrag bekommt — oder *kein DNS-Eintrag*, dann bleibt DNS
unangetastet. Die Wahl bleibt an der Firewall hängen, beim nächsten Start ist
wieder dasselbe Paar da. Rechts daneben die **Erweiterten Optionen** für alles,
was man selten braucht (Backend-Zertifikat prüfen, X-Forwarded-For, Health
Monitor, Backend-Modus, Namens-Präfix, „nur speichern, nicht neu laden").

Was in die Formulare eingetragen wurde, gehört dem Fenster und nicht ihnen:
Zumachen und wieder aufmachen verliert keine getroffene Wahl.

Jede Zeile der Liste zeigt, was AdGuard zu diesem Namen weiß:

| | |
| --- | --- |
| **DNS ✓** | Es gibt eine Umschreibung, und sie zeigt auf die HAProxy-IP. |
| **DNS → …** | Es gibt eine, sie zeigt aber woanders hin. |
| **kein DNS** | AdGuard kennt den Namen nicht. |

Der Knopf daneben bringt das in Ordnung: **DNS eintragen**, **auf HAProxy
zeigen** oder **DNS löschen**, je nachdem was fehlt. Das geht nur an AdGuard,
an HAProxy ändert sich dabei nichts. **Entfernen** räumt umgekehrt den ganzen
Eintrag ab — Real Server, Backend, Condition, Rule und DNS.

Ein Public Service, der **alles** auf seinem Port weiterreicht statt nach Namen
zu sortieren, hat gar keine Rules. Er steht trotzdem in der Liste — mit einer
Zeile **alles auf Port …** und der Marke **Listener**, dazu **TLS** in der
Kopfzeile, wenn die Verschlüsselung dort endet. So sieht man einen frisch
angelegten TCP-Listener sofort, statt „keine Rules" zu lesen.

Rules, die du früher in OPNsense von Hand angelegt hast, stehen mit in der
Liste: ihr Hostname wird auch aus einer `hdr_beg`-Bedingung gelesen, sie sind
also anklickbar und bekommen ihren DNS-Knopf. **Entfernen** gibt es für sie
nicht — dafür müssten die Objekte so heißen, wie dieses Programm sie benennt.

**Unten** das Protokoll: jede Zeile, die das Programm gerade tut, farblich nach
Anlegen, Löschen und Fehler getrennt. Wenn etwas schiefgeht, steht der Grund
dort — nicht in einem Popup, das man wegklickt und dann nicht mehr findet.

Alle Abfragen laufen im Hintergrund, das Fenster friert also nicht ein, während
die OPNsense antwortet. Theme und Fenstergröße merkt es sich.

## Ein eigener Listener: TLS außen, ohne innen

Alles oben Beschriebene hängt einen **Namen** in einen Eingang, den es schon
gibt: HAProxy liest den Host-Header (oder die SNI) und sortiert danach. Für
einen Webdienst ist das genau richtig.

Ein TURN-Server, ein IMAP-Server oder eine Datenbank haben aber keinen Namen im
Protokoll, nach dem sich sortieren ließe — sie haben einen **Port**. Und oft
sprechen sie gar kein TLS, obwohl sie von außen erreichbar sein sollen. Dafür
ist **＋ TCP-Listener** da: HAProxy nimmt die Verbindung auf einem eigenen Port
an, beendet dort die Verschlüsselung mit einem öffentlichen Zertifikat und
spricht nach innen so, wie der Dienst es will.

> **Beispiel.** Ein TURN-Server auf `192.168.1.40:3478`, ohne TLS. Außen soll
> `turn.example.com:5349` mit einem gültigen Zertifikat antworten. Ein Listener
> auf Port 5349, Modus **TCP**, Zertifikat gewählt, Ziel `192.168.1.40:3478`,
> *TLS zum Server* aus — fertig. Der Client redet TLS mit HAProxy, HAProxy
> redet Klartext mit dem TURN-Server.

Das Fenster hat zwei Spalten, und die sind genau die beiden Seiten:

**Außen — was ankommt**

| Feld | |
| --- | --- |
| **Name** | So heißt der Public Service danach in OPNsense, z.B. `turn-tls`. |
| **Port** | Worauf HAProxy nach außen hört. Ist der Port schon von einem anderen Public Service belegt, sagt das Programm das, bevor es etwas anlegt. |
| **Adresse** | `0.0.0.0` = alle IPv4-Adressen der Firewall. |
| **Modus** | **TCP** — die TLS-Verbindung endet hier (der Fall oben). **SSL** — sie wird durchgereicht und nur nach SNI sortiert, der Dienst braucht dann sein eigenes Zertifikat. **HTTP** — der übliche Web-Eingang. |
| **Zertifikat** | Die Liste kommt aus der Firewall selbst — dieselbe, die auch das HAProxy-Plugin anbietet, also auch die Zertifikate des ACME-Clients. Ohne Zertifikat reicht der Listener nur weiter. |

**Innen — wohin es geht**

| Feld | |
| --- | --- |
| **Server-IP / Port** | Der Dienst dahinter. Ohne Port derselbe wie außen. |
| **TLS zum Server** | Aus, wenn der Dienst Klartext spricht. An, wenn er selbst TLS erwartet — dann optional noch **Zertifikat des Servers prüfen** für den Fall, dass es kein selbstsigniertes ist. |
| **Öffentlicher Name** | Nur für den DNS-Eintrag, z.B. `turn.example.com`. Leer lassen heißt: kein DNS-Eintrag. |

Angelegt werden drei Dinge: Real Server, Backend Pool im Modus `tcp` und der
Public Service selbst, der alles an diesen Pool schickt. Keine Condition, keine
Rule — es gibt ja nichts zu prüfen. Danach steht der Listener in der Liste, mit
der Marke **Listener** und der Zeile, wohin er alles weiterreicht.

**Nachgelesen wird, was ankam.** Das Plugin nimmt die Felder, die es kennt, und
übergeht den Rest wortlos — ein Feldname, den eine andere Plugin-Version anders
schreibt, kostet also keine Fehlermeldung, sondern einen Listener auf dem
falschen Port. Deshalb wird der frisch angelegte Public Service sofort wieder
gelesen und mit dem verglichen, was geschickt wurde. Stimmt etwas nicht, wird
alles wieder abgeräumt und der Grund steht im Protokoll.

**Löschen** geht hier nicht: Ein Public Service, an dem später Rules hängen,
wäre mit einem Klick zu viel weg. Wer einen Listener wieder loswerden will,
löscht ihn in OPNsense unter *Services → HAProxy → Real Servers / Backend
Pools / Public Services*.

## Der zweite Tab: Portainer

Oben sitzen drei große Tabs. **HAProxy** ist alles, was oben beschrieben ist.
**Portainer** ist die zweite Hälfte: die Docker-Container, die hinter HAProxy
stehen.

Ein Standort hat meist eine OPNsense und einen Portainer, also merkt sich jede
Firewall, welcher Portainer zu ihr gehört: wer die OPNsense wechselt, bekommt
den Docker-Host gleich mit. Zwingend ist die Zuordnung nicht — solange dieser
Tab vorne ist, wählt der Umschalter oben rechts den Portainer, unabhängig
davon, was die Firewall vorschlägt. **Verbinden** gilt immer für den Tab, der
gerade vorne ist.

Eine OPNsense braucht es dafür nicht: wer nur einen Portainer einträgt, kann
diesen Tab allein benutzen.

### Einrichten

Im Zahnrad ⚙ im Abschnitt **Portainer** auf **＋ Hinzufügen**:

* **Name** — wie du ihn nennen willst, z.B. `Docker Zuhause`.
* **Adresse** deines Portainers, z.B. `https://portainer.example.de:9443`.
* **Anmeldung** — entweder ein **Zugriffstoken** (in Portainer oben rechts auf
  den Benutzer, dann *My account → Access tokens → Add access token*) oder
  **Benutzer und Passwort** wie in der Weboberfläche. Beim Token wird nichts
  weiter gebraucht; beim Passwort holt sich das Programm bei jedem Start selbst
  ein Token. Unter dem Feld steht ein Link, der genau diese Seite auf der
  Adresse öffnet, die du eine Zeile darüber eingetragen hast — das Token zeigt
  Portainer nur ein einziges Mal an, also gleich herüberkopieren.
* **IP des Docker-Hosts** — die Adresse, an die HAProxy die Anfragen schickt.
  Bleibt sie leer, wird der Rechner aus der Portainer-Adresse genommen. Das
  stimmt, solange Portainer auf demselben Host läuft wie die Container;
  ansonsten hier die richtige IP eintragen.

Damit der Tab weiß, welchen Portainer er zeigen soll, wählst du ihn bei der
OPNsense unter **Arbeitet zusammen mit** — oder jederzeit oben rechts im
Umschalter, solange dieser Tab vorne ist. Läuft Portainer über mehrere
Umgebungen (*Environments*), steht im Tab selbst noch ein Auswahlfeld dafür.
Welche Umgebung du zuletzt benutzt hast, merkt sich das Programm je Portainer.

### Was die Liste zeigt

Jeder Stack als Karte: Name, Art (**Compose**), ob er sich selbst aktualisiert
(**⟳ auto**), wie viele seiner Container laufen (**2/2**), und darunter das
Repository, aus dem er kommt. Danach folgt Zeile für Zeile jeder Port, den er
**auf dem Host veröffentlicht** hat:

```
8080  →  80/tcp     app                        HAProxy ✓
9000  →  9000/tcp   app          nur lokal     → HAProxy
```

Links der Port auf dem Host, rechts daneben der Port im Container. Das ist die
Zahl, die du für HAProxy brauchst: die linke.

| | |
| --- | --- |
| **nur lokal** | Der Port ist an `127.0.0.1` gebunden. Von einem anderen Rechner — also auch von HAProxy — ist er nicht erreichbar. |
| **HAProxy ✓** | Es gibt schon eine Rule, deren Real Server auf genau diese IP und diesen Port zeigt. |
| **→ HAProxy** | Noch keine. Der Knopf legt sie an. |

Veröffentlicht ein Stack **mehr als fünf Ports**, zeigt die Karte die ersten
vier und darunter **▾ n weitere Ports**. Ein Klick klappt sie auf, einer klappt
sie wieder zu. Bei genau fünf bleibt alles stehen — eine einzelne Zeile zu
verstecken hilft niemandem.

Container, die ohne Stack gestartet wurden, stehen darunter als eigene Gruppe —
sie belegen dieselben Ports auf demselben Host, und ein Port, der schon vergeben
ist, ist beim Planen genauso wichtig.

Ob ein Port **wirklich aus dem Internet** erreichbar ist, kann Docker nicht
sagen; das entscheidet die Firewall davor. Die Liste sagt daher, was sie weiß:
woran der Port gebunden ist.

### Vom Port zum Namen

**→ HAProxy** öffnet ein kleines Fenster mit allem schon ausgefüllt: der
**Name des Stacks** als Vorschlag, die IP des Docker-Hosts, der veröffentlichte
Port. Du wählst noch die Basis-Domain und den Public Service, drückst
**Anlegen** — und der Rest läuft wie im ersten Tab, samt DNS-Eintrag in AdGuard
und Protokoll unten. Unter dem Namensfeld steht mit, was daraus wird.

Vorgeschlagen wird der Stack-Name und nicht der Dienst aus der Compose-Datei:
Den Stack hast du benannt, und es gibt ihn auf dem Host genau einmal — der
Dienst darin heißt in jeder Kopie gleich. Ein `dhom-time2` neben einem
`dhom-time` bekäme sonst den Namen des ersten vorgeschlagen, was aussieht, als
wäre die Zahl verlorengegangen. Veröffentlicht ein Stack Ports aus **mehreren**
Diensten, steht der Dienst vorne dabei: `web-shop`, `admin-shop`.

Dafür muss der HAProxy-Tab verbunden sein; ohne die Public Services von der
OPNsense weiß das Programm nicht, wo die Rule hin soll.

Ist für diese OPNsense **kein AdGuard gewählt** (oder fehlt die HAProxy-IP),
steht das an der Stelle, an der sonst das DNS-Häkchen sitzt — und im Protokoll
steht dann `dns rewrite : none` samt Grund. Ein Host ohne DNS-Eintrag löst
nirgends auf; das soll man beim Anlegen sehen und nicht beim Aufrufen.

### Einen Stack neu deployen

**Neu deployen** auf der Karte fragt zwei Dinge:

* **Images neu herunterladen (Update)** — an: Portainer holt die Images
  frisch, der Stack läuft danach auf dem neuesten Stand. Aus: dieselben Images
  werden noch einmal gestartet.
* **Container entfernen, die nicht mehr in der Compose-Datei stehen** (prune).

Kommt der Stack aus einem privaten Repository, kannst du Benutzer und Token
angeben. Lässt du die Felder leer, benutzt Portainer die Zugangsdaten, die es
für diesen Stack schon gespeichert hat — das ist der Normalfall.

Stacks ohne Repository (in Portainer aus dem Editor angelegt) gehen genauso:
dann wird die Compose-Datei benutzt, die Portainer für sie aufbewahrt.

### Einen Stack löschen

**Löschen** auf der Karte zeigt erst, was passieren würde: die Container beim
Namen, und die Host-Ports, die wieder frei werden. Portainer stoppt die
Container und entfernt den Stack samt seinen Netzwerken. **Benannte Volumes
bleiben liegen** — die Daten sind also nicht weg, und wer sie auch loswerden
will, räumt sie in Portainer unter *Volumes* ab.

Interessanter ist die zweite Hälfte: **die HAProxy-Einträge dazu ebenfalls
entfernen.** Zeigt eine Rule auf einen Port dieses Stacks, steht sie im Fenster
namentlich, und der Haken nimmt sie mit — Real Server, Backend Pool, Condition
und Rule, dazu der DNS-Eintrag, wenn im Formular ein AdGuard gewählt ist. Ohne
den Haken bleibt sie stehen und zeigt auf einen Port, an dem nichts mehr
antwortet.

Damit das angeboten werden kann, muss der HAProxy-Tab verbunden sein und beim
Portainer eine **IP des Docker-Hosts** stehen — sonst weiß das Programm nicht,
welche Rules überhaupt hierher zeigen, und sagt das an der Stelle auch.

### Der Katalog: Stacks, die schon jemand aufgeschrieben hat

**★ Katalog** oben öffnet eine Sammlung, aus der heraus deployt wird. Oben
rechts steht, aus welcher der drei Listen:

**Bekannte Stacks** kommen aus der Datei [catalog.json](catalog.json) im
Repository dieses Programms — Einträge mit Beschreibung, deren Compose-Datei an
der angegebenen Stelle wirklich liegt. Die Liste wird höchstens einmal am Tag
geholt und dazwischen aus dem Zwischenspeicher gezeigt; ↻ holt sie sofort neu.
Ist GitHub nicht erreichbar, gilt die Fassung, die mit dem Programm gekommen
ist. Fehlt dir etwas darin: ein Pull Request mit einem weiteren Eintrag ist
willkommen, das Format steht in der Datei.

**Meine Favoriten** sind dieselben Angaben, selbst hinterlegt — für das, was du
öfter brauchst. **☆** an einem Eintrag der anderen Listen legt ihn dorthin,
**＋ Eigener Favorit** legt einen von Grund auf an: Name, Beschreibung,
Repository, Branch und Pfad zur Compose-Datei. Zugangsdaten stehen dort
**nicht** — die kommen beim Deployen aus dem Git-Konto, dessen Adresse zum
Repository passt. Favoriten stehen in derselben Datei wie die Systeme.

**Meine Repos** listet auf, was der Token eines Git-Kontos sehen darf, private
wie öffentliche. Deployst du eines davon, geht das Formular auf mit Repository,
Pfad **und den Zugangsdaten dieses Kontos in den sichtbaren Feldern** — nichts
wird heimlich mitgeschickt, und du kannst es vor dem Deployen noch ändern.

Vor einem Deploy wird geprüft, ob **beides** verbunden ist — Portainer für den
Stack, OPNsense für den Weg über HAProxy gleich danach. Fehlt eines, kommt
*Wohin deployen?*; wer dort *— keiner —* als OPNsense wählt, wird in dieser
Sitzung nicht wieder gefragt.

Der Katalog lässt sich auch ohne Verbindung durchsehen — für *Meine Repos*
genügt der Token, Portainer wird dafür nicht gebraucht. Erst zum **Deployen**
muss verbunden sein, und wenn es das nicht ist, fragt **Wohin deployen?** in
einem Zug nach beidem: dem **Portainer**, auf den der Stack geht, und der
**OPNsense** für den Weg über HAProxy danach. Die OPNsense darf dabei
*— keiner —* bleiben; deployt wird trotzdem, der Weg über HAProxy lässt sich
später nachholen. Danach verbindet das Programm beides der Reihe nach und macht
von allein weiter, wo du geklickt hast.

In allen drei Listen ist **Deployen** dasselbe: das Fenster *Neuer Stack* geht
auf, vorausgefüllt — und weil aus einer Liste heraus niemand wissen kann, was
so ein Stack braucht, wird die **Compose-Datei gleich gelesen** und ihre
Variablen stehen im Feld, bevor du danach suchen musst. Es ist derselbe
Vorgang wie der Knopf *aus dem Repository*, nur ungefragt. Name, Variablen und alles Übrige bleiben deine Sache — der
Katalog spart das Abtippen, nicht das Nachdenken.

### Ein Git-Konto einrichten

Nötig für *Meine Repos* und für private Repositories. Unter ⚙ im Abschnitt
**Git-Konto** auf **＋ Hinzufügen**:

* **Name** — wie du es nennen willst, z.B. `GitHub privat`.
* **Adresse** — `https://github.com`, `https://gitlab.com` oder die deines
  eigenen GitLab.
* **Benutzer** — dein Anmeldename dort.
* **Token** — lesen genügt. Bei einem GitHub *Fine-grained token*:
  **Repository access → Only select repositories** und **Permissions →
  Repository permissions → Contents: Read-only**. Bei GitLab die Scopes
  `read_api` (für die Liste) und `read_repository` (fürs Klonen). Unter dem
  Feld steht ein Link, der die Seite für neue Token auf genau diesem Host
  öffnet.

Der Token steht danach in der Konfigurationsdatei, die mit Rechten 600 im
eigenen Benutzerordner liegt. Beim Deployen geht er an Portainer, das ihn beim
Stack hinterlegt — das braucht Portainer, um bei einem automatischen Update
noch einmal klonen zu können.

### Einen neuen Stack anlegen

**＋ Neuer Stack** oben rechts öffnet ein eigenes Fenster — breit genug für
Repository-Pfade und einen ordentlichen Block Umgebungsvariablen. Ganz oben
steht **Deployen auf**: welcher Portainer und welche Umgebung. Beides lässt
sich hier noch ändern, damit ein Stack nicht auf dem falschen Docker-Host
landet.

Darunter links die Angaben zum Repository, rechts das Seltenere:

* **Name** — Kleinbuchstaben, wie bei Portainer. Er wird zum Compose-Projekt.
* **Repository** — die HTTPS-Adresse bei GitHub oder GitLab. Für Portainer ist
  beides nur eine Git-URL, einen Unterschied gibt es nicht.
* **Branch oder Tag** — leer heißt Standardbranch.
* **Datei im Repository** — der Pfad zur Compose-Datei, voreingestellt
  `docker-compose.yml`.
* **Umgebungsvariablen** — eine Zeile je Variable, `KEY=wert`, genau wie im
  Textfeld von Portainer. Leere Zeilen und `#`-Kommentare werden übergangen,
  Anführungszeichen um den Wert fallen weg. Den Anfang macht der Knopf
  **aus dem Repository** daneben, siehe unten.
* **Freie Host-Ports** — unter den Variablen liegt eine Liste der Ports, die
  auf der gewählten Umgebung niemand belegt, abgeglichen mit allem, was die
  Container dort nach außen veröffentlichen. **einsetzen** schreibt die Zahl an
  die Stelle, an der der Cursor im Feld steht; darunter steht, was schon
  vergeben ist. Sichtbar ist nur, was Portainer sieht — ein Dienst außerhalb
  von Docker kann denselben Port trotzdem halten.
* **Privates Repository** — Benutzer und Token. Sie gehen an Portainer, das sie
  beim Stack hinterlegt; **in der Konfigurationsdatei dieses Programms landen
  sie nicht**. Als Benutzer der eigene Anmeldename, als Passwort ein Token —
  das eigentliche Passwort nehmen GitHub und GitLab dafür nicht mehr an. Lesen
  genügt: bei einem GitHub *Fine-grained token* **Repository access → Only
  select repositories** und **Permissions → Repository permissions →
  Contents: Read-only**, bei GitLab der Scope `read_repository`. Links zu
  beiden Seiten stehen unter dem Feld.
* **Automatisch aktualisieren** — *regelmäßig nachsehen* (Abstand als `5m`,
  `30m`, `24h`) oder *auf Webhook warten*. Beim Webhook steht die fertige
  URL nach dem Deploy im Protokoll; wer sie in GitHub oder GitLab als Webhook
  einträgt, bekommt den Stack bei jedem Push neu ausgerollt.
* **danach den Weg über HAProxy anbieten** — sobald die Container laufen, wird
  für den ersten veröffentlichten Port gleich das Fenster von oben geöffnet.

### Die Variablen aus dem Repository holen

Neben *Umgebungsvariablen* sitzt der Knopf **aus dem Repository**. Er füllt das
Feld schon einmal vor, damit du nur noch die Werte anpasst.

Was dabei passiert:

1. Die **Compose-Datei** wird gelesen — an dem Pfad, dem Branch und mit den
   Zugangsdaten, die im Formular stehen. Daraus jedes `${VAR}`, samt Vorgabe
   bei `${VAR:-wert}`. Das ist die verbindliche Liste dessen, was der Stack
   braucht.
2. Zeigt sie mit `env_file:` auf eine Datei, wird dort nachgesehen. Sonst
   werden daneben und im Wurzelverzeichnis die üblichen Namen probiert:
   `.env.example`, `.env`, `example.env`, `.env.sample`, `.env.template`,
   `stack.env`. Beim ersten Treffer ist Schluss.
3. Beides wird zusammengeführt und ins Feld geschrieben — mit einer
   Kommentarzeile, woher welcher Teil kommt.

```
# aus docker/example.env
UPLOAD_LOCATION=./library
DB_PASSWORD=postgres

# in docker/docker-compose.yml verwendet, bitte ausfüllen
IMMICH_SERVER_URL=
```

**Was du schon eingetippt hast, bleibt.** Ergänzt wird nur, was noch fehlt —
ein zweiter Druck fügt also nichts doppelt ein. Die Kommentarzeilen dürfen
stehen bleiben, sie werden beim Deploy überlesen.

Gelesen wird über Portainer, nicht von hier aus: GitHub und GitLab sind für
Portainer dieselbe Git-URL, und ein privates Repository geht mit denselben
Zugangsdaten, die auch der Deploy benutzt. Nebenbei ist das eine **Probe vor
dem Deploy** — kommt die Compose-Datei zurück, stimmen Adresse, Branch, Pfad
und Zugangsdaten. Sonst steht der Grund im Protokoll.

Liegt im Repository eine echte `.env` (nicht `.env.example`), liest Docker
Compose sie beim Deploy ohnehin selbst aus dem geklonten Verzeichnis. Was hier
im Feld steht, setzt Portainer zusätzlich — praktisch zum Anpassen, aber nicht
der einzige Weg, wie die Werte wirken.

### Zweimal dasselbe Repository

Ein zweiter Stack aus demselben Repository — die Vorschau neben dem laufenden
Stand — scheitert leicht an etwas, das nicht dem Stack gehört, sondern dem
ganzen Docker-Host: dem **Container-Namen** und dem **Host-Port**. Beide gibt es
dort nur einmal. Docker lehnt den zweiten Stack dann mit
`the container name "/dhom-time" is already in use` ab, und in Portainer bleibt
ein halb angelegter Stack stehen.

Darum sieht das Programm **vor** dem Deploy nach. Es liest die Compose-Datei
(dieselbe Leseweise wie oben), rechnet die Variablen mit dem aus, was im Feld
steht, und vergleicht das Ergebnis mit dem, was auf der Umgebung schon läuft.
Findet es etwas, kommt der Deploy gar nicht erst los:

```
Auf Portainer · docker-01 ist schon vergeben:

• Container-Name „dhom-time“ — belegt von dhom-time
• Host-Port 8088 — belegt von dhom-time

Container-Namen und Host-Ports gelten für den ganzen Docker-Host, nicht für
den einzelnen Stack. Docker würde den Deploy darum abweisen.

Diese Werte kommen aus Variablen und lassen sich hier ändern:
    DHOM_TIME_NAME=dhom-time-vorschau
    DHOM_TIME_PORT=8089
```

**Ja** trägt die freien Werte in die Umgebungsvariablen ein — an Ort und Stelle,
falls die Variable schon im Feld steht — und deployt damit. Der Name kommt vom
Stack selbst, der Port ist der nächste freie darüber. **Nein** deployt
unverändert, **Abbrechen** führt zurück ins Formular.

Steht der Wert fest in der Compose-Datei (`container_name: dhom-time` statt
`container_name: ${DHOM_TIME_NAME:-dhom-time}`), kann das Programm nichts
anbieten: dann hilft nur eine Änderung im Repository — die Zeile auf eine
Variable umstellen oder ganz streichen, dann benennt Docker die Container nach
dem Stack. Gesagt wird es trotzdem, mitsamt dem Namen dessen, der den Wert
gerade hält.

Kommt eine solche Absage doch von Portainer — weil die Compose-Datei vorher
nicht zu lesen war oder in der Zwischenzeit ein Container dazukam —, steht
unter der Fehlermeldung im Protokoll dieselbe Erklärung.

## Der dritte Tab: AdGuard

Der erste Tab sagt zu jedem Host, was AdGuard über ihn weiß — aber nur zu
denen, für die es schon eine Rule in HAProxy gibt. Ein DNS-Server hält mehr als
das: die NAS, den Drucker, die Maschine, die auf einem eigenen Port antwortet.
Namen also, die nie über einen Reverse Proxy gelaufen sind. Der dritte Tab
zeigt die **ganze Liste** und schreibt auch hinein.

**Verbinden** oben rechts liest die Umschreibungen; von allein passiert auch
hier nichts. Wer den ersten Tab verbindet, bekommt die Liste gleich mit — sie
wird ohnehin für die DNS-Markierungen in der Hostliste gelesen.

Eine OPNsense braucht es dafür nicht: wer nur ein AdGuard einträgt, kann diesen
Tab allein benutzen.

### Was die Liste zeigt

Eine Zeile je Eintrag, **Name** und darunter **→ Ziel**, sortiert nach Domain
von hinten — `example.de`, `*.example.de` und `app.example.de` stehen also
beieinander und nicht über die ganze Liste verteilt. Rechts die Markierungen:

| | |
| --- | --- |
| **HAProxy** | Das Ziel ist die HAProxy-IP dieser Verbindung. Der Name geht also den Weg über den Reverse Proxy. |
| **alle darunter** | Ein Eintrag mit `*.` davor. Er gilt für jeden Namen unter dieser Domain — ein eigener Eintrag geht immer vor. |

Das Feld daneben **sucht**, in Name und Ziel zugleich. Die Zeile unter der
Überschrift zählt mit, wie viele Einträge es sind, wie viele davon auf HAProxy
zeigen und wie viele gerade zur Suche passen.

### Eine Umschreibung anlegen oder ändern

**＋ Neue Umschreibung** fragt nach zweierlei:

* **Name** — `nas.example.de`, oder `*.example.de` für alles darunter.
* **Ziel** — eine Auswahlliste, in die man auch tippen kann. Darin stehen alle
  Adressen, auf die dieses AdGuard schon zeigt, die HAProxy-IP zuerst; eine
  neue IP trägt man einfach ein. Unter dem Feld steht, was die gewählte
  Adresse bedeutet: *ist HAProxy*, *dorthin zeigen schon 3 andere Namen* oder
  *neue Adresse*. Vorausgefüllt ist die HAProxy-IP, denn das ist der häufigste
  Fall.

**Ändern** an einer Zeile öffnet dasselbe Fenster mit den Werten darin,
**Löschen** fragt einmal nach und nimmt den Eintrag heraus. Danach löst der
Name wieder ganz normal auf.

AdGuard kennt kein „ändern": ein Eintrag wird gelöscht und neu geschrieben.
Genauso wenig kennt es eindeutige Namen — derselbe Name darf zweimal dastehen,
etwa mit einer IPv4- und einer IPv6-Adresse. Steht ein Name also schon da,
fragt das Programm, ob der neue Wert den alten **ersetzen** soll oder ob
**beide** bleiben. Was passiert, steht danach im Protokoll, Zeile für Zeile.

Alles, was hier geschrieben wird, sieht der erste Tab sofort: die
DNS-Markierungen in der Hostliste kommen aus derselben Liste.

## Mehrere Systeme

Seit 2.0 führen **OPNsense, AdGuard und Portainer je eine eigene Liste**. Das
Zahnrad ⚙ zeigt alle drei untereinander, mit **＋ Hinzufügen** und
**Bearbeiten** je Eintrag. Der Umschalter oben rechts wechselt die OPNsense; die
letzte Zeile in seiner Liste, **⚙ Einstellungen …**, führt in dieselbe
Übersicht.

Warum getrennt: ein AdGuard bedient oft mehrere Standorte, und ein Docker-Host
gehört nicht zwingend zu genau einer Firewall. Vorher musste beides in jedem
Profil noch einmal stehen — dieselben Zugangsdaten an zwei Stellen, die man
beide pflegen musste.

Jede OPNsense sagt unter **Arbeitet zusammen mit**, welches AdGuard und welchen
Portainer sie gewöhnlich benutzt. Das ist die Vorauswahl, mehr nicht:

* Beim Anlegen eines Hosts steht im Formular **DNS-Eintrag in** — dort geht
  auch ein anderes AdGuard oder gar keins, für genau diesen Host.
* Im Fenster **＋ Neuer Stack** steht ganz oben **Deployen auf** — dort wählst
  du Portainer und Umgebung.
* Auf dem Tab **AdGuard** wählt der Umschalter oben rechts, wessen Liste zu
  sehen ist. Das ist dieselbe Wahl wie **DNS-Eintrag in** im Formular: was hier
  gewählt wird, steht auch dort.

Was du dort wählst, merkt sich das Programm bei der Firewall: beim nächsten
Start ist wieder das Paar da, das zuletzt zusammen benutzt wurde. Standort A
mit DNS, Standort B ohne, beide am selben AdGuard: alles möglich.

## Updates

Einmal am Tag schaut das Programm beim Start still bei GitHub nach, ohne zu
fragen und ohne das Fenster aufzuhalten. Gibt es etwas Neues, trägt der Knopf
**⇩ Update** die neue Versionsnummer und ist farbig hinterlegt. Mehr passiert
von allein nicht — installiert wird erst, wenn du drückst.

Der Knopf zeigt dann die Versionsnummer und, sofern hinterlegt, was sich
geändert hat. Nach der Installation ist ein Neustart nötig, den der Dialog
gleich anbietet.

Ersetzt werden nur die Programmdateien selbst — alles, was aus dem Archiv wie
eine davon aussieht (`.py`, `.json`, `.md`, `.bat`, die Symbole), außer
`config.json` und `gui.json`. **Zugangsdaten und Einstellungen bleiben
unangetastet**, und die alten Dateien landen vorher in einem Ordner
`backup-<version>/` daneben. Heruntergeladener Code wird vor dem Schreiben
geprüft; ist das Archiv unvollständig oder beschädigt, wird nichts angefasst.
Ist GitHub nicht erreichbar, bleibt das folgenlos.

Das ist bewusst eine Regel und keine Liste von Dateinamen: Ein Update wird von
der Fassung ausgeführt, die gerade installiert ist, und eine Liste in ihr kann
eine Datei, die es damals noch nicht gab, nicht kennen. Genau daran sind 1.4.0
(`portainer.py`) und 2.3.0 (`catalog.py`) gescheitert — beide Male ließ das
Update eine Datei zurück, die die neue Fassung braucht.

Fehlt trotzdem einmal etwas, ist nichts verloren: der Portainer-Tab sagt dann,
welche Datei es ist, und der Update-Knopf daneben holt sie nach. Startet das
Programm gar nicht mehr, hilft das
[ZIP](https://github.com/DukyNuky/opnsense-haproxy-config/releases/latest),
über den Ordner entpackt.

Wer die tägliche Nachfrage nicht möchte, setzt in
`~/.config/opnsense-haproxy/gui.json` `"update_check": false`; der Knopf
funktioniert weiter.

---

## Wenn etwas nicht klappt

**Das Fenster geht gar nicht auf / schließt sich sofort.**
Unter Windows `HAProxy-Starter.bat` benutzen, nicht die `.py`-Datei — der
Starter prüft Python und sagt, was fehlt. Unter Linux fehlt meist `python3-tk`.

**„cannot reach" oder Zeitüberschreitung beim Verbinden.**
Stimmt die Adresse, inklusive `https://`? Erreichst du dieselbe Adresse im
Browser? Hängt dein Rechner im richtigen Netz?

**Zertifikatsfehler beim Verbinden.**
Das Häkchen *TLS-Zertifikat der OPNsense prüfen* im Zahnrad-Dialog ausschalten.
Selbstsignierte Zertifikate sind im Heimnetz normal.

**„401" oder „Authentifizierung fehlgeschlagen".**
Key und Secret vertauscht, oder das `key=` bzw. `secret=` aus der Datei
mitkopiert. Beide Felder noch einmal sauber einfügen. Zur Not in der
Benutzerübersicht mit der Briefmarke einen neuen Schlüssel erzeugen.

**„403" oder leere Listen.**
Dem Benutzer fehlen die Rechte — siehe Schritt 4b. Sie hängen am Benutzer, auch
wenn der Schlüssel längst existiert.

**Die Basis-Domains bleiben leer.**
Der ACME-Client ist nicht installiert oder dem Benutzer fehlt das Recht
*Services: ACME Client*. Kein Beinbruch: den vollen Hostnamen eintippen.

**Im Feld „Public Service" fehlt einer.**
Zur Wahl stehen nur die Listener, die auf **Port 443** hören — dort kommen die
Anfragen an. Ein zweiter auf Port 80, der Browser nur weiterschickt, ist keine
Stelle für eine Regel und wird darum ausgeblendet; unter dem Feld steht, wie
viele das betrifft. Wer seinen Eingang auf einem anderen Port betreibt (etwa
8443), holt sie mit **Erweiterte Optionen → „Auch Public Services ohne Port 443
zeigen"** zurück. Hört überhaupt keiner auf 443, stehen ohnehin alle da.

**Der Name ist schon vergeben.**
Bestehendes wird nie überschrieben. Das Programm bricht ab und sagt, welches
Objekt im Weg ist.

**Angelegt, aber die Seite lädt nicht.**
Erst prüfen, ob der Name überhaupt auf die HAProxy-IP zeigt (Spalte *DNS* in
der Liste). Dann, ob der Zielserver auf der angegebenen IP und dem Port
antwortet. Spricht er HTTPS, muss der Schalter *SSL zum Backend* an sein.

---

## Was genau angelegt wird

Für `app.example.com` mit Ziel `192.168.1.50:8080`:

| Objekt in OPNsense | Name | Inhalt |
| --- | --- | --- |
| Real Server | `srv_app.example.com` | 192.168.1.50:8080 |
| Backend Pool | `be_app.example.com` | verweist auf den Real Server |
| Condition | `acl_app_example_com` | `hdr` — Host-Header ist `app.example.com` |
| Rule | `rule_app_example_com` | `if` Condition → `use_backend` |
| Public Service | (bestehend) | Rule wird an `linkedActions` angehängt |
| AdGuard-Umschreibung | — | `app.example.com` → HAProxy-IP (optional) |

Bei einem Pfad (`example.com/api`) kommt eine zweite Condition `path_beg` dazu;
beide werden mit **AND** verknüpft.

Für einen **TCP-Listener** `turn-tls` auf Port 5349 mit Ziel `192.168.1.40:3478`
sind es drei andere Objekte — ohne Condition und ohne Rule, denn es gibt keinen
Namen zu prüfen:

| Objekt in OPNsense | Name | Inhalt |
| --- | --- | --- |
| Real Server | `srv_turn-tls` | 192.168.1.40:3478 |
| Backend Pool | `be_turn-tls` | Modus `tcp`, verweist auf den Real Server |
| Public Service | `turn-tls` | `bind 0.0.0.0:5349`, Modus `tcp`, Zertifikat, Default Backend |
| AdGuard-Umschreibung | — | `turn.example.com` → HAProxy-IP (optional) |

## Entscheidungen, die das Programm trifft

* **Public Service**: Vorgewählt ist der Listener auf **Port 443** — mit dem
  Namen hat das nichts zu tun, es zählt, worauf er hört. Gibt es mehrere auf
  443, steht der erste davon da und die anderen daneben zur Wahl. Unter dem
  Feld steht immer, auf welche Adresse der gewählte hört, damit die Entscheidung
  nicht am Namen hängt. Auf der Kommandozeile gilt dasselbe: Bei mehreren
  Listenern wird der eine auf 443 genommen; sind es dort mehrere, fragt das
  Programm nach `--frontend`.
* **Host-Header oder SNI**: läuft der Public Service im Modus `http`, wird auf
  den Host-Header gematcht. Bei `ssl`/`tcp` (SSL-Passthrough) sieht HAProxy
  keinen Host-Header, deshalb wird dort auf **SNI** gematcht und der Backend
  Pool auf `tcp` gesetzt. Ein Pfad ist in diesen Modi nicht möglich und wird
  mit einer Fehlermeldung abgelehnt.
* **Das Backend-Zertifikat wird nicht geprüft**, wenn *SSL zum Backend* an ist.
  OPNsense schaltet die Prüfung per Default an, was bei internen Hosts mit
  selbstsignierten Zertifikaten sofort zu 503ern führt. Wer eine saubere
  interne CA hat, setzt den Haken in den erweiterten Optionen.
* **`X-Forwarded-For` ist bei HTTP-Backends an** — damit der Zielserver die
  echte Besucher-IP sieht.
* **Health-Monitor**: standardmäßig keiner. In den erweiterten Optionen lässt
  sich ein bereits in OPNsense angelegter verknüpfen.
* **Namen**: `srv_`/`be_`/`acl_`/`rule_` + Hostname. Real Server und Backend
  dürfen Punkte enthalten, Conditions und Rules nicht (Vorgabe des Plugins) —
  dort werden Punkte zu `_`.
* **Reload**: nach dem Anlegen läuft `haproxy -c`. Nur wenn der Test sauber
  ist, wird neu geladen.
* **Public Service**: es wird ausschließlich die Rule-Liste geschrieben, nie
  der ganze Eintrag. Ein Roundtrip über alle Felder quittiert die OPNsense-API
  je nach Feldtyp mit einem 500er — und könnte im Vorbeigehen Einstellungen wie
  das SSL-Zertifikat leeren.

## Grenzen

* **Entfernen** findet die Objekte über das Namensschema. Wurden sie in
  OPNsense umbenannt, greift es nicht mehr — dann per Hand löschen.
* Bestehende Einträge werden nicht verändert; ist ein Name schon vergeben,
  bricht das Anlegen ab und sagt, was im Weg ist.
* Zertifikate für den Public Service (Let's Encrypt o.ä.) verwaltet das
  Programm nicht — das bleibt Sache des ACME-Clients. Es sucht sie nur aus der
  Liste, die die Firewall selbst anbietet.
* Einen Public Service legt **＋ TCP-Listener** an, aber er löscht keinen: an
  einem hängen später womöglich Rules, und das wäre ein Klick zu viel. Weg
  kommt er in OPNsense.
* Ein bestehender Listener wird nicht verändert — kein Umstellen von Port,
  Modus oder Zertifikat. Auch das macht OPNsense selbst.
* Bei Portainer geht es um **Compose-Stacks auf einem einzelnen Docker-Host**.
  Swarm- und Kubernetes-Stacks werden in der Liste als solche gekennzeichnet,
  aber nicht deployt — dort kommen die Ports aus den Services und nicht aus den
  Containern, das wäre eine eigene Baustelle.
* Ein Stack wird angelegt, neu deployt und gelöscht, aber nicht bearbeitet.
  Wer die Compose-Datei oder die Variablen eines laufenden Stacks ändern will,
  macht das in Portainer selbst.
* Beim Löschen bleiben **benannte Volumes** liegen — Docker gibt sie mit dem
  Stack nicht frei, und dieses Programm greift sie nicht an. Die Daten sind
  also noch da, aufgeräumt wird in Portainer.
* Ob ein Port von außerhalb des Heimnetzes erreichbar ist, weiß Docker nicht;
  die Liste sagt nur, an welche Adresse er auf dem Host gebunden ist.

---

# Für Fortgeschrittene

Ab hier geht es um die Kommandozeile und die Konfigurationsdatei. Für den
normalen Gebrauch ist nichts davon nötig.

## Dateien

| Datei | |
| --- | --- |
| `opnsense_haproxy.py` | Logik und CLI |
| `haproxy_gui.py` | Fenster (tkinter) |
| `portainer.py` | Portainer-API: Stacks, Container, Ports, Deploys |
| `portainer_gui.py` | der zweite Tab |
| `adguard_gui.py` | der dritte Tab |
| `catalog.py` | Katalog, Favoriten, Git-Konten, eigene Repos |
| `catalog.json` | die bekannten Stacks — im Programm über GitHub geholt |
| `HAProxy-Starter.bat` | Doppelklick-Start für Windows |
| `icon.png` / `icon.ico` | Symbol für Fenster und Starter |

Nur Python 3 (Standardbibliothek), keine weiteren Abhängigkeiten, kein
Build-Schritt.

## Kommandozeile

```sh
./opnsense_haproxy.py init                                         # einrichten
./opnsense_haproxy.py add app.example.com -i 192.168.1.50 --no-ssl # anlegen
./opnsense_haproxy.py certificates                                 # Zertifikate
./opnsense_haproxy.py listener turn-tls -p 5349 -i 192.168.1.40 \
    --backend-port 3478 --certificate 5f2a1b3c4d5e6                # Listener
./haproxy_gui.py                                                   # Fenster
```

Ohne Argumente fragt `add` die vier Werte nacheinander ab:

```
$ ./opnsense_haproxy.py add
URL / hostname: wiki.example.com
real server IP: 192.168.10.20
use SSL to the backend? (yes/no) [no]: yes
real server port [443]: 8443
```

Oder alles direkt:

```sh
# Basis-Domain wählen und nur den Hostnamen angeben
./opnsense_haproxy.py add wiki -b home.example.com -i 192.168.10.20 -p 8443 --ssl

# HTTP zum Backend, voller Name
./opnsense_haproxy.py add app.example.com -i 192.168.1.50 -p 8080 --no-ssl

# nur ein Pfad-Präfix auf ein eigenes Backend
./opnsense_haproxy.py add https://example.com/api -i 10.0.0.9 -p 3000 --no-ssl

# die Basis-Domain selbst, ohne Subdomain
./opnsense_haproxy.py add @ -b home.example.com -i 10.0.0.8 --no-ssl

# ohne AdGuard-Eintrag
./opnsense_haproxy.py add test -b home.example.com -i 10.0.0.5 --no-ssl --no-dns

# erst mal nur anschauen, nichts ändern
./opnsense_haproxy.py add test.example.com -i 10.0.0.5 --no-ssl --dry-run
```

Ein eigener Listener geht genauso. `certificates` sagt vorher, welche
Zertifikate es gibt — die refid davor ist, was `--certificate` erwartet (der
Name geht auch):

```sh
# TLS außen, Klartext innen -- der TURN-Fall
./opnsense_haproxy.py listener turn-tls -p 5349 -i 192.168.1.40 \
    --backend-port 3478 --certificate 5f2a1b3c4d5e6 \
    --host turn.example.com

# durchgereicht, der Dienst hat sein eigenes Zertifikat
./opnsense_haproxy.py listener imap -p 993 -i 192.168.1.60 --mode ssl --ssl

# erst mal nur anschauen
./opnsense_haproxy.py listener db -p 5432 -i 10.0.0.7 --dry-run
```

Weitere Befehle:

```sh
./opnsense_haproxy.py list                        # was hängt an welchem Public Service
./opnsense_haproxy.py certificates                # Zertifikate für einen Listener
./opnsense_haproxy.py domains                     # Basis-Domains aus dem ACME-Client
./opnsense_haproxy.py profiles                    # eingerichtete Verbindungen
./opnsense_haproxy.py -P Zweitstandort list       # eine bestimmte Verbindung
./opnsense_haproxy.py remove app.example.com      # alle vier Objekte wieder weg
./opnsense_haproxy.py apply                       # Configtest + Reload
./opnsense_haproxy.py status                      # läuft HAProxy?
./opnsense_haproxy.py install                     # fester Platz + Starter
./opnsense_haproxy.py update --check              # nur nachsehen
./opnsense_haproxy.py update                      # nachsehen und installieren
./opnsense_haproxy.py gui                         # Fenster
./opnsense_haproxy.py --version
```

Zugangsdaten gehen auch über `--url/--key/--secret` bzw. die Umgebung
`OPNSENSE_URL`/`OPNSENSE_KEY`/`OPNSENSE_SECRET`. Bei selbstsigniertem
Zertifikat: `--insecure`.

`install` legt die Befehle `haproxy-gui` und `opnsense-haproxy` in
`~/.local/bin` an; andere Ziele über `install /pfad`, `--bin ~/bin`,
`--desktop`, `--no-menu`, `--no-commands`. Von Hand geht es auch:

```sh
chmod +x opnsense_haproxy.py
sudo ln -s "$PWD/opnsense_haproxy.py" /usr/local/bin/haproxy-add
```

Liegt das Programm in einer git-Arbeitskopie, verweigert `update` den Dienst und
verweist auf `git pull` — sonst wären eigene Änderungen weg.

## Konfigurationsdatei

`~/.config/opnsense-haproxy/config.json` (Modus 600), siehe
[config.example.json](config.example.json). Seit 2.0 stehen die drei Sorten
Systeme in drei Listen nebeneinander, und eine OPNsense nennt die beiden
anderen beim Namen:

```json
{
  "active": { "opnsense": "Zuhause", "adguard": "Zuhause",
              "portainer": "Docker Zuhause" },
  "opnsense": [
    { "name": "Zuhause", "url": "…", "key": "…", "secret": "…",
      "haproxy_ip": "192.168.1.1", "verify_ssl": false,
      "adguard": "Zuhause", "portainer": "Docker Zuhause" },
    { "name": "Zweitstandort", "url": "…", "key": "…", "secret": "…",
      "adguard": "Zuhause" }
  ],
  "adguard": [
    { "name": "Zuhause", "url": "https://adguard.example.de",
      "username": "admin", "password": "…", "target": "", "verify_ssl": false }
  ],
  "portainer": [
    { "name": "Docker Zuhause", "url": "https://portainer.example.de:9443",
      "api_key": "ptr_…", "host_ip": "192.168.1.20", "verify_ssl": false }
  ],
  "git": [
    { "name": "GitHub privat", "url": "https://github.com",
      "username": "…", "token": "github_pat_…" }
  ],
  "favorites": [
    { "name": "immich", "description": "Fotos selbst gehostet",
      "repository": "https://github.com/immich-app/immich",
      "reference": "", "compose_file": "docker/docker-compose.yml" }
  ]
}
```

Das `adguard` und das `portainer` einer OPNsense sind **Namen**, keine
Abschnitte: dasselbe AdGuard darf bei beliebig vielen Firewalls stehen, ohne
zweimal in der Datei zu stehen. Wer nichts nennt, arbeitet ohne — und was
tatsächlich benutzt wird, entscheidest du beim Anlegen ohnehin neu.

`haproxy_ip` ist das Ziel aller DNS-Einträge; ein `target` beim AdGuard sticht
es aus, `--dns-target` für einen einzelnen Aufruf. Bei der AdGuard-`url` genügt
die Adresse der Oberfläche — die kopierte Browser-Zeile
(`https://adguard.example.de/#dns_rewrites`) geht genauso, der API-Pfad wird
selbst angehängt. Fehlt das Schema, wird `https://` angenommen.

Beim Portainer gilt entweder `api_key` **oder** `username` und `password` —
beim Speichern wird der jeweils andere Weg geleert, damit später nicht ein
vergessener Rest entscheidet, womit angemeldet wird. `host_ip` ist die Adresse,
an die HAProxy Anfragen an Container schickt; ohne Angabe wird der Rechner aus
der `url` genommen.

Ein **`git`**-Eintrag ist kein System, mit dem dieses Programm dauernd redet:
der Token listet die eigenen Repositories auf und wird beim Deployen ins
Formular eingesetzt, geklont wird von Portainer. Welches Konto für ein
Repository gilt, ergibt sich aus dem **Host** der Adresse — es wird nichts
ausgewählt und nichts verknüpft. Wer keines anlegt, tippt Benutzer und Token
beim Deploy von Hand ein wie bisher; in der Datei landen sie dann nicht.

**`favorites`** sind Stacks, die du wieder deployen willst — dieselben Felder
wie im Katalog, ohne Zugangsdaten.

**Ältere Dateien werden beim Lesen umgesetzt**, von Hand ist nichts zu tun. Aus
jedem Profil wird eine OPNsense, aus seinem AdGuard- und Portainer-Abschnitt je
ein eigener Eintrag, benannt nach dem Profil. Zwei Profile, die auf dasselbe
AdGuard zeigten, teilen sich hinterher einen Eintrag — es war immer eine
Maschine. Geschrieben wird die neue Form erst, wenn du das nächste Mal etwas in
den Einstellungen speicherst; bis dahin bleibt die Datei, wie sie ist. Auch
eine Datei mit nur einer Verbindung ganz oben funktioniert weiter — sie
erscheint als OPNsense „Standard".

## Basis-Domains

Die Auswahlliste kommt aus dem **ACME-Client** und braucht keine eigene
Einrichtung — die dort gepflegten Zertifikate werden gelesen:

* Ein Wildcard-Zertifikat `*.home.example.com` ergibt die Basis-Domain
  `home.example.com`, unter der jeder Hostname möglich ist.
* Ein Zertifikat für einen einzelnen Namen wird als exakter Name angeboten.

Passt der zusammengesetzte Name nicht zum Zertifikat (`a.b.home.example.com`
unter einem Wildcard, das nur eine Ebene abdeckt), gibt es eine Warnung —
angelegt wird trotzdem, denn das Zertifikat kann auch von woanders kommen.

## Ein Paket bauen

`./make_release.py` liest die Versionsnummer aus `opnsense_haproxy.py` und legt
`releases/opnsense-haproxy-<version>.zip` an. Das Symbol zeichnet
`./make_icon.py` neu — reine Standardbibliothek, jede Form als Abstand
beschrieben, daraus fallen `icon.png` und `icon.ico` heraus.
