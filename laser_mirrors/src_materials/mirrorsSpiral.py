import time
from epics import PV

def eckige_spirale(schritte=20, segment_laenge=1):

    x, y = 0, 0
#    richtungen = [(5, 0), (0, 5), (-5, 0), (0, -5)]  # rechts, oben, links, unten
    richtungen = [(6, 0), (0, 8), (-6, 0), (0, -8)]  # m1, m2, m1, m2
    richtung_index = 0
    aktuelle_laenge = segment_laenge
    erhoehungen = 0

    koordinaten = [(x, y)]

    for _ in range(schritte):
        dx, dy = richtungen[richtung_index]

        for _ in range(aktuelle_laenge):
            x += dx
            y += dy
            koordinaten.append((x, y))

        richtung_index = (richtung_index + 1) % 4
        erhoehungen += 1

        if erhoehungen % 2 == 0:
            aktuelle_laenge += 1

    return koordinaten


coords = eckige_spirale(schritte=30)
#values for PoPII laser
#offsetX = -680
#offsetY = -575
#offsetX = -675
#offsetY = -590
offsetX = 0
offsetY = -280

for x, y in coords:
    print(offsetX + x, offsetY + y)
    PV('MNF2C2L2RP.VAL').put(offsetX + x)
    PV('MNF2C1L2RP.VAL').put(offsetY + y)

    time.sleep(10)
    
