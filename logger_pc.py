#!/usr/bin/env python3
"""GPS Train - script PC de secours.

Lit l'API du Wi-Fi de bord SNCF (wifi.sncf), enregistre un CSV et, si demandé,
envoie des trames NMEA sur un port série (par exemple COM49 d'une paire
virtuelle com0com dont l'autre extrémité, COM50, est lue par Nemo Outdoor).

Exemples :
  python logger_pc.py                      # affiche la position, écrit un CSV
  python logger_pc.py --com COM49          # + envoie du NMEA sur COM49 (pip install pyserial)
  python logger_pc.py --url http://localhost:8765 --duree 30    # test avec un faux serveur
"""
import argparse, csv, json, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

def get(url, timeout=4):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def cs(body):
    c = 0
    for ch in body:
        c ^= ord(ch)
    return "%02X" % c

def dm(value, is_lat):
    h = "N" if value >= 0 else "S"
    if not is_lat:
        h = "E" if value >= 0 else "W"
    v = abs(value); d = int(v); m = (v - d) * 60
    return ("%02d%07.4f" % (d, m) if is_lat else "%03d%07.4f" % (d, m)), h

def nmea(g):
    t = datetime.fromtimestamp(g["ts"], timezone.utc)
    hh = t.strftime("%H%M%S") + ".00"
    la, ns = dm(g["lat"], True); lo, ew = dm(g["lon"], False)
    alt = g["alt"] if g["alt"] is not None else 0.0
    gga = "GPGGA,%s,%s,%s,%s,%s,1,08,1.0,%.1f,M,0.0,M,," % (hh, la, ns, lo, ew, alt)
    kn = (g["kmh"] or 0.0) / 1.852
    hdg = g["hdg"] if g["hdg"] is not None else 0.0
    rmc = "GPRMC,%s,A,%s,%s,%s,%s,%.2f,%.1f,%s,,,A" % (hh, la, ns, lo, ew, kn, hdg, t.strftime("%d%m%y"))
    return "".join("$%s*%s\r\n" % (s, cs(s)) for s in (gga, rmc)).encode("ascii")

def parse(j):
    if not j or j.get("success") is False: return None
    try:
        lat = float(j["latitude"]); lon = float(j["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    def f(k):
        try: return float(j[k])
        except (KeyError, TypeError, ValueError): return None
    ts = f("timestamp") or time.time()
    if ts > 1e12: ts /= 1000
    sp = f("speed")
    return {"ts": ts, "lat": lat, "lon": lon, "alt": f("altitude"),
            "kmh": None if sp is None else sp * 3.6, "hdg": f("heading"), "fix": j.get("fix")}

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="https://wifi.sncf", help="adresse de base de l'API")
    ap.add_argument("--intervalle", type=float, default=1.0, help="secondes entre deux lectures")
    ap.add_argument("--csv", default=None, help="fichier CSV de sortie")
    ap.add_argument("--com", default=None, help="port série pour le NMEA (ex. COM49)")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--duree", type=float, default=0, help="arrêt automatique après N secondes (0 = jamais)")
    a = ap.parse_args()
    ser = None
    if a.com:
        try:
            import serial
            ser = serial.Serial(a.com, a.baud, timeout=1)
        except Exception as e:
            sys.exit("Port série impossible : %s (pip install pyserial ?)" % e)
    name = a.csv or "gps_train_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M")
    out = open(name, "w", newline="", encoding="utf-8-sig")
    w = csv.writer(out, delimiter=";")
    w.writerow(["horodatage_utc", "latitude", "longitude", "altitude_m", "vitesse_kmh", "cap_deg", "fix"])
    print("Lecture de %s - fichier %s - Ctrl+C pour arrêter" % (a.url, name))
    t0 = time.time(); last = None; n = 0
    try:
        while True:
            try:
                g = parse(get(a.url.rstrip("/") + "/router/api/train/gps"))
                if g is None:
                    print("En attente de position...")
                else:
                    if g["ts"] != last:
                        last = g["ts"]; n += 1
                        w.writerow([datetime.fromtimestamp(g["ts"], timezone.utc).isoformat(),
                                    "%.7f" % g["lat"], "%.7f" % g["lon"],
                                    "" if g["alt"] is None else "%.1f" % g["alt"],
                                    "" if g["kmh"] is None else ("%.1f" % g["kmh"]).replace(".", ","),
                                    "" if g["hdg"] is None else "%.1f" % g["hdg"], g["fix"]])
                        out.flush()
                    if ser: ser.write(nmea(g))
                    print("%.6f %.6f  %s km/h  cap %s  (%d points)" % (g["lat"], g["lon"],
                          "-" if g["kmh"] is None else "%.0f" % g["kmh"], g["hdg"], n))
            except (urllib.error.URLError, OSError, ValueError) as e:
                print("API injoignable :", e)
            if a.duree and time.time() - t0 >= a.duree: break
            time.sleep(a.intervalle)
    except KeyboardInterrupt:
        pass
    out.close(); print("Terminé : %d points dans %s" % (n, name))

if __name__ == "__main__":
    main()
