

import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
from scipy.signal import find_peaks
import winsound
import threading
import time


COM_PORT          = "COM5"   #  port COM Bluetooth
BAUD_RATE         = 9600
FENETRE           = 300      # nombre de points affichés (30 sec à 10 Hz)
WINDOW            = 15       # filtre moyenne glissante
APNEE_SEUIL_S     = 10       # alerte si pas de respiration depuis X sec
FREQ_ECHANT       = 10.0     # fréquence d'échantillonnage estimée (Hz)



#  CONNEXION BLUETOOTH

try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
    print(f"[OK] Connecté sur {COM_PORT}")
except serial.SerialException as e:
    print(f"[ERREUR] {e}")
    exit()


#  BUFFER
frequences        = deque([0.0] * FENETRE, maxlen=FENETRE)
frequences_lissee = deque([0.0] * FENETRE, maxlen=FENETRE)


#  VARIABLES PARTAGÉES

derniere_respiration = time.time() #enregistre le moment actuel
nb_respirations      = 0
alerte_active        = False
lock                 = threading.Lock()



#  THREAD ALERTE SONORE
def thread_alerte():
    """Joue un bip toutes les 1 sec si apnée détectée"""
    while True:
        time.sleep(1) #pour éviter de tourner en prémanece
        with lock:
            silence = time.time() - derniere_respiration
        if silence >= APNEE_SEUIL_S:
            try:
                winsound.Beep(1200, 400)  # 1200 Hz, 400 ms
            except RuntimeError:
                pass


t_alerte = threading.Thread(target=thread_alerte, daemon=True)
t_alerte.start()


#  DÉTECTION DES PICS DE RESPIRATION
def detecter_pics(data):
    """
    Détecte les pics de respiration et calcule le rythme.
    Retourne : (indices des pics, respirations/minute)
    """
    if len(data) < 30:
        return [], 0

    amplitude     = max(data) - min(data)
    prominence    = max(amplitude * 0.10, 50.0)  # 15% amplitude, min 50 Hz

    pics, _ = find_peaks(data,
                         prominence=prominence,
                         distance=10)  # min 1 sec entre 2 pics

    if len(pics) >= 2:
        duree_s   = (pics[-1] - pics[0]) / FREQ_ECHANT
        respi_min = (len(pics) - 1) / duree_s * 60.0 if duree_s > 0 else 0
    else:
        respi_min = 0

    return pics, respi_min


#  GRAPHE
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8),
                                gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle("Moniteur de Respiration — Détection d'Apnée",
             fontsize=14, fontweight="bold")

# Graphe du haut : signal
ligne_brute,  = ax1.plot([], [], color="#AACCE8", linewidth=1.0,
                         label="Signal brut", alpha=0.5)
ligne_lissee, = ax1.plot([], [], color="#185FA5", linewidth=2.0,
                         label="Signal lissé")
pics_markers, = ax1.plot([], [], "o", color="#E24B4A", markersize=8,
                         label="Respirations détectées")

ax1.set_xlim(0, FENETRE)
ax1.set_xlabel("Échantillons")
ax1.set_ylabel("Fréquence (Hz)")
ax1.set_title("Signal du conditionneur capacitif")
ax1.legend(loc="upper right")
ax1.grid(True, alpha=0.3)

# Texte info en haut à gauche
info_text = ax1.text(0.01, 0.95, "", transform=ax1.transAxes,
                     fontsize=11, va="top",
                     bbox=dict(boxstyle="round,pad=0.4",
                               facecolor="white", alpha=0.8,
                               edgecolor="#185FA5"))

# Graphe du bas : indicateur respirations/min
barre = ax2.bar([0], [0], width=0.6, color="#1D9E75")
texte_resp = ax2.text(0.5, 0.5, "", transform=ax2.transAxes,
                      ha="center", va="center",
                      fontsize=24, fontweight="bold")
ax2.axhline(y=12, color="#BA7517", linestyle="--", alpha=0.5)
ax2.axhline(y=20, color="#BA7517", linestyle="--", alpha=0.5)
ax2.set_xlim(-0.5, 0.5)
ax2.set_ylim(0, 40)
ax2.set_xticks([])
ax2.set_ylabel("Respirations / min")
ax2.set_title("Rythme respiratoire (normal : 12–20/min)")
ax2.grid(True, alpha=0.3, axis="y")

plt.tight_layout()

# Pour détecter de nouvelles respirations en temps réel
dernier_pic_index = -1


def actualiser(frame):
    global derniere_respiration, dernier_pic_index

    # Lecture Bluetooth
    nouvelle_donnee = False 
    try:
        derniere_val = None
        while ser.in_waiting > 0: #Tant qu'il reste des données on lit
            raw = ser.readline().decode("utf-8", errors="ignore").strip()
            if raw:
                derniere_val = raw

        if derniere_val:
            freq = float(derniere_val)
            frequences.append(freq)

            data = list(frequences) 
            if len(data) >= WINDOW:
                lissee = sum(data[-WINDOW:]) / WINDOW
            else:
                lissee = freq
            frequences_lissee.append(lissee)
            nouvelle_donnee = True

    except (ValueError, serial.SerialException):
        pass

    # Détection des pics 
    data_lissee   = list(frequences_lissee)
    pics, resp_min = detecter_pics(data_lissee)

    # Détection de nouvelle respiration (pic le plus récent)
    if len(pics) > 0:
        dernier_pic_pos = pics[-1]
        # Si le pic est proche de la fin du buffer (récent)
        if dernier_pic_pos > len(data_lissee) - 15:
            if dernier_pic_pos != dernier_pic_index:
                with lock:
                    derniere_respiration = time.time()
                dernier_pic_index = dernier_pic_pos

    # État apnée
    with lock:
        silence = time.time() - derniere_respiration

    apnee = silence >= APNEE_SEUIL_S

    # Mise à jour du graphe
    data_brute = list(frequences)
    ligne_brute.set_data(range(len(data_brute)),   data_brute)
    ligne_lissee.set_data(range(len(data_lissee)), data_lissee)

    # Marqueurs des pics
    if len(pics) > 0:
        pics_x = pics
        pics_y = [data_lissee[i] for i in pics]
        pics_markers.set_data(pics_x, pics_y)
    else:
        pics_markers.set_data([], [])

    # Ajustement axe Y
    valeurs = [v for v in data_lissee if v > 0]
    if valeurs:
        mini, maxi = min(valeurs), max(valeurs)
        marge = max(300.0, (maxi - mini) * 0.3)
        ax1.set_ylim(max(0, mini - marge), maxi + marge)

    # Texte d'information
    if apnee:
        info_text.set_text(
            f"⚠  APNÉE DÉTECTÉE  ⚠\n"
            f"Pas de respiration depuis {silence:.0f}s\n"
            f"Pics détectés : {len(pics)}")
        info_text.set_bbox(dict(boxstyle="round,pad=0.4",
                                facecolor="#FFE0E0",
                                edgecolor="#E24B4A", linewidth=2))
    else:
        info_text.set_text(
            f"État : Respiration normale\n"
            f"Dernière respiration : il y a {silence:.1f}s\n"
            f"Pics détectés (30s) : {len(pics)}")
        info_text.set_bbox(dict(boxstyle="round,pad=0.4",
                                facecolor="#E0F5E8",
                                edgecolor="#1D9E75", linewidth=1))

    # Indicateur du bas
    resp_int = int(round(resp_min))
    barre[0].set_height(resp_int)

    if apnee:
        barre[0].set_color("#E24B4A")
        texte_resp.set_text("APNÉE !")
        texte_resp.set_color("#E24B4A")
    elif 12 <= resp_int <= 20:
        barre[0].set_color("#1D9E75")
        texte_resp.set_text(f"{resp_int}/min")
        texte_resp.set_color("#1D9E75")
    elif resp_int > 0:
        barre[0].set_color("#BA7517")
        texte_resp.set_text(f"{resp_int}/min")
        texte_resp.set_color("#BA7517")
    else:
        barre[0].set_color("#888888")
        texte_resp.set_text("--")
        texte_resp.set_color("#888888")

    return (ligne_brute, ligne_lissee, pics_markers,
            info_text, barre[0], texte_resp)



#  LANCEMENT

print("=" * 50)
print("  Moniteur de Respiration")
print(f"  Port : {COM_PORT}  |  Baud : {BAUD_RATE}")
print(f"  Seuil apnée : {APNEE_SEUIL_S} secondes")
print("=" * 50)

ani = animation.FuncAnimation(fig, actualiser,
                               interval=100, blit=False,
                               cache_frame_data=False)
plt.show()
ser.close()
