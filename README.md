# MusicXML Practice Map

<img src="pianohof-logo.png" width="110" alt="PIANOHOF Logo">

Eine lokale Übersicht für Musiker und Klavierlehrer: Das Werkzeug zeigt, an welchen Stellen einer MusicXML-Datei Tonart-, Takt-, Schlüssel-, Tempo- und Wiederholungsangaben stehen. Damit lässt sich vor dem Üben oder bei einer Rückfrage zum Notenexport gezielt nachsehen, welche Angaben tatsächlich in der Datei vorhanden sind. Die ausgewählte Datei bleibt unverändert auf deinem Rechner.

## Wofür die Übersicht hilft

Du möchtest beispielsweise wissen, ob der Export einen Taktwechsel enthält, ob zwei Schlüssel verschiedenen Notensystemen zugeordnet sind oder ob eine gedruckte Metronomangabe einen Punkt an der Zähleinheit hat. Statt den gesamten XML-Text zu durchsuchen, erhältst du eine Liste nach Part und Takteintrag. Notierte Werte bleiben als solche erkennbar; fehlende Angaben werden nicht geraten oder aus Nachbartakten ergänzt.

Die Ausgabe enthält zusätzlich Anzahlen von `note`-Elementen, Pausen, Akkord-Folgetönen und Vorschlagsnoten. Das sind Zählwerte der Datei. Sie beschreiben weder die Zahl gleichzeitig klingender Töne noch die Zahl der Anschläge in einer Aufnahme. Ein Akkord-Folgeton ist hier ein `note`-Element mit einem `chord`-Kind; Pausen und Vorschlagsnoten sind ebenfalls in der Gesamtzahl der `note`-Elemente enthalten.

## Starten

Benötigt wird ein gepflegtes Python ab Version 3.12 mit Expat ab 2.6.0. Es werden keine zusätzlichen Python-Pakete installiert. Die konkrete Prüfung erfolgte mit Python 3.12.14 und Expat 2.8.3. Lade die Projektdateien zusammen herunter und öffne ein Terminal in ihrem Ordner. Beginne mit der mitgelieferten künstlichen Testdatei:

```sh
python3 musicxml_practice_map.py example.musicxml
python3 musicxml_practice_map.py example.musicxml --json
python3 -m unittest -v
```

Für eine eigene Datei ersetzt du den Dateinamen. Pfade mit Leerzeichen kommen in Anführungszeichen. Die Endungen `.musicxml`, `.xml` und komprimiertes `.mxl` werden unterstützt, sofern der Inhalt eine partweise MusicXML-Partitur ist. JSON wird ebenfalls nur ins Terminal geschrieben; eine Datei entsteht erst, wenn du die Ausgabe selbst umleitest.

```sh
python3 musicxml_practice_map.py "Mein Stück.mxl" --json
```

## Den Bericht richtig lesen

Jeder Part behält seine Kennung und seinen vorhandenen Namen. Ein Takt erhält sowohl einen fortlaufenden Eintragsindex als auch seine ursprüngliche Beschriftung. Dadurch bleiben zwei Einträge mit derselben Beschriftung unterscheidbar; auch Bezeichnungen wie `2a` werden nicht in eine vermeintliche Zahl umgewandelt. Die XML-Position eines Ereignisses bezeichnet seine Stelle unter den direkten Kindern dieses Taktelements.

Wichtig ist die Grenze dieser Reihenfolge: Attribute können innerhalb eines Taktes stehen, während Stimmen durch `backup` und `forward` unterschiedliche zeitliche Positionen besitzen. Das Programm berechnet daraus keine musikalische Zeitachse. Es löst auch keine Wiederholungen, Volten, D.C.- oder D.S.-Sprünge auf. Für den tatsächlichen Spielablauf ist die Partitur im Notensatzprogramm zu prüfen.

Eine Metronomangabe und ein `sound`-Element mit Tempo bleiben getrennte Fundstellen. Zähleinheit, Punkte und vorhandene Unterelemente der Metronomangabe werden beibehalten. Das Programm macht daraus keine pauschale Viertelnoten-BPM-Zahl. Auch Angaben zu bestimmten Notensystemen, zusammengesetzte Taktarten und nichttraditionelle Tonartangaben werden nicht auf ein einzelnes vereinfachtes Feld reduziert.

## Das künstliche Beispiel nachvollziehen

`example.musicxml` enthält einen Klavier-Part mit vier Takteinträgen und zwei Notensystemen. Im dritten Eintrag stehen ein Wechsel auf 3/4, eine Metronomangabe mit punktierter Viertel und ein separates Tempoattribut. Im vierten findet sich eine Vorschlagsnote. Die Datei dient ausschließlich der Softwareprüfung; sie behauptet weder einen realen Unterrichtsfall noch eine Empfehlung zur Interpretation eines Musikstücks.

Die unabhängig festgelegten Erwartungen stehen in `expected_example.json`: Beschriftungen 1 bis 4, `note`-Anzahlen 2/3/2/3, eine Pause, ein Akkord-Folgeton und eine Vorschlagsnote. Die Tests prüfen außerdem die Fundstellen und die schriftlichen Elemente. Du kannst diese Werte direkt am kurzen XML-Beispiel nachzählen.

## Komprimierte Dateien und Grenzen

Bei MXL wird die erste in `META-INF/container.xml` deklarierte Wurzeldatei verwendet. Ein zufällig zuerst gespeichertes XML-Mitglied ist keine Ersatzregel dafür. Das Archiv wird nicht entpackt. Verlinkte Bilder, DTDs, Audio oder andere externe Ressourcen werden nicht geöffnet. `score-timewise` und `opus` werden mit einer verständlichen Meldung abgelehnt; in diesem Fall ist ein Export als `score-partwise` erforderlich.

Die Grenzen liegen bei 16 MiB Eingabe, 8 MiB je gelesener XML-Datei, 32 MiB deklarierter entpackter Archivgröße, 256 Archivmitgliedern, 100.000 XML-Elementen und 128 Verschachtelungsebenen. Für gelesene XML-Archivmitglieder gilt zusätzlich ein maximales Größenverhältnis von 200:1. Interne DTD-Untergruppen, benutzerdefinierte Entities, verschlüsselte Archive und mehrdeutige doppelte Mitgliedsnamen werden abgewiesen. Diese begrenzten Prüfungen sind keine allgemeine Sicherheitszertifizierung.

## Herkunft und Quellen

Das Projekt entstand mit KI-Unterstützung für die persönlichen Klaviernotizen von Juri Enes. Code, Anleitung und künstliches Beispiel sind neue Projektmaterialien. Es wurden keine Kundenpartituren, Aufnahmen oder fremden Kompositionen eingebaut. Das Werkzeug führt keine Netzwerk-, Geräte- oder Wiedergabebefehle aus und bewertet weder die Richtigkeit einer Notation noch den Klang oder den Zustand eines Instruments.

Primäre Formatquellen: [W3C MusicXML — MXL](https://www.w3.org/2021/06/musicxml40/tutorial/compressed-mxl-files/), [attributes](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/attributes/), [metronome](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/metronome/) und [repeat](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/repeat/). Die W3C beschreibt den Dateiaufbau; sie unterstützt oder zertifiziert dieses Projekt nicht. Der Quelltext und die Tests bestimmen den hier beschriebenen Funktionsumfang.

Herausgegeben im Umfeld von [PIANOHOF, Klavierwerkstatt in Berlin](https://www.pianohof.de/). Die MIT-Lizenz gilt für Code, Anleitung und künstliche Beispiele. Name, Logo und Markenrechte von PIANOHOF sind davon ausgenommen.
