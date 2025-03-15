from pyrogram import Client, filters 
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import subprocess
import platform
import threading
import time
import re
import json
import os
import socket
import paramiko  # Para conexión SSH
import logging
import concurrent.futures
import qbittorrentapi  # Para consultar qBittorrent
import math  # Para redondeos en barras

# Configuración del logging
logging.basicConfig(
    level=logging.INFO,  # Puedes usar DEBUG para mayor detalle
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("mi_bot.log"),
        logging.StreamHandler()
    ]
)
logging.info("El bot ha iniciado correctamente.")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Obtiene la ruta donde está el script
CONFIG_PATH = os.path.join(BASE_DIR, "ipbot_netatmo.json")

try:
    with open(CONFIG_PATH, "r") as f:
        netatmo_config = json.load(f)
except Exception as e:
    logging.error("Error al cargar ipbot_netatmo.json: " + str(e))
    netatmo_config = {}

# Parámetros de Tautulli
TAUTULLI_URL = netatmo_config.get("TAUTULLI_URL", "")
TAUTULLI_APIKEY = netatmo_config.get("TAUTULLI_APIKEY", "")

# Configuración para el servidor Plex (QNAP)
QNAP_HOST = "192.168.0.160"
QNAP_USER = "admin"
QNAP_PASSWORD = ""

# Configuración para Wake on LAN
QNAP_MAC = "24:"

# Interfaz de red a monitorear en el QNAP
NET_INTERFACE = "eth0"
INTERVAL = 1  # Intervalo para lecturas (usado en funciones SSH)

# CONFIGURACIÓN DEL BOT
API_ID = ''
API_HASH = ''
BOT_TOKEN = ''

DUCKDNS_TOKEN = ''
DUCKDNS_DOMAIN = ''
DUCKDNS_URL = f"https://www.duckdns.org/update?domains={DUCKDNS_DOMAIN}&token={DUCKDNS_TOKEN}&ip="

# Lista de chats permitidos
ALLOWED_CHAT_IDS = [123456789]

app = Client("ip_monitor_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Obtiene la ruta del script actual
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")  # Asegura la ruta completa del archivo JSON


# VARIABLES GLOBALES
UPDATE_INTERVAL = 10  # Intervalo de actualización en segundos

ips_publicas = {}
ips_privadas = {}

status_messages = {}         # {chat_id: status_message_id}
tracked_message_ids = {}     # {chat_id: set(message_ids)}
shutdown_confirmations = {}
apertura_confirmations = {}
user_states = {}
lights_on_times = {}


IP_REGEX = r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"

last_public_ip = None
last_public_ip_change_time = None
previous_public_ip = None
last_update_time = None
entrada_piso_last_state = None
entrada_piso_last_change_time = None
battery_value = None
battery_last_update = 0

# Variables globales
DEFAULT_OPENWEATHER_COORDS = (42.026057409514756, 2.87957567194319)
DEFAULT_LOCATION_NAME = "Celra"
current_openweather_coords = DEFAULT_OPENWEATHER_COORDS
current_location_name = DEFAULT_LOCATION_NAME
openweather_location_set_time = 0
TEMP_LOCATION_DURATION = 4 * 3600  # 4 horas en segundos

cached_openweather_data = None
openweather_last_update = 0

# (Opcional) Obtener IPs locales
def get_local_ips():
    try:
        return socket.gethostbyname_ex(socket.gethostname())[2]
    except Exception:
        return []
local_ips = get_local_ips()

# CONFIGURACIÓN (CARGA/ALMACENAMIENTO)
def save_config():
    config = {
        "ips_publicas": ips_publicas,
        "ips_privadas": ips_privadas
    }
    with open(CONFIG_FILE, 'w') as file:
        json.dump(config, file, indent=4)

def load_config():
    global ips_publicas, ips_privadas
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as file:
            config = json.load(file)
            ips_publicas.update(config.get("ips_publicas", {}))
            ips_privadas.update(config.get("ips_privadas", {}))
load_config()

# =======================
# NUEVAS VARIABLES Y CONSTANTES PARA OPENWEATHER
# =======================
OPENWEATHER_API_KEY = ""
# Variables globales para cache de OpenWeather
cached_openweather_data = None
openweather_last_update = 0

# =======================
# NUEVAS FUNCIONES AUXILIARES PARA OPENWEATHER
# =======================
def fetch_openweather_data():
    global current_openweather_coords, openweather_location_set_time, current_location_name
    # Si han pasado más de 4h con la ubicación temporal, se vuelve a la predeterminada.
    if openweather_location_set_time and (time.time() - openweather_location_set_time > TEMP_LOCATION_DURATION):
        current_openweather_coords = DEFAULT_OPENWEATHER_COORDS
        openweather_location_set_time = 0
        current_location_name = DEFAULT_LOCATION_NAME
        logging.info("Se ha revertido a la ubicación por defecto (Celra)")
    lat, lon = current_openweather_coords
    url = (f"https://api.openweathermap.org/data/3.0/onecall?"
           f"lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric&lang=es")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.exception("Error al obtener datos de OpenWeather")
        return None


def update_openweather_cache():
    """
    Hilo que actualiza los datos de OpenWeather cada hora.
    """
    global cached_openweather_data, openweather_last_update
    while True:
        data = fetch_openweather_data()
        if data:
            cached_openweather_data = data
            openweather_last_update = time.time()
            logging.info("Datos de OpenWeather actualizados.")
        else:
            logging.warning("No se pudieron actualizar los datos de OpenWeather.")
        time.sleep(1800)  # Actualizar cada 30 min

def get_openweather_data():
    """
    Retorna los datos cacheados de OpenWeather.
    """
    return cached_openweather_data

def get_wind_direction(degrees):
    """
    Convierte grados en dirección del viento con nombre e ícono en catalán.
    """
    directions = [
        "⬆ Tramuntana (N)", "↗ Gregal (NE)", "➡ Llevant (E)", "↘ Xaloc (SE)",
        "⬇ Migjorn (S)", "↙ Garbí / Llebeig (SO)", "⬅ Ponent (O)", "↖ Mestral (NO)"
    ]
    index = round(degrees / 45) % 8
    return directions[index]

def get_moon_phase_icon(moon_phase):
    """
    Convierte el valor de moon_phase (0 a 1) en un icono representativo.
    Fases:
      - 0 a 0.0625 y 0.9375 a 1: Luna nueva (🌑)
      - 0.0625 a 0.1875: Luna creciente (🌒)
      - 0.1875 a 0.3125: Cuarto creciente (🌓)
      - 0.3125 a 0.4375: Gibosa creciente (🌔)
      - 0.4375 a 0.5625: Luna llena (🌕)
      - 0.5625 a 0.6875: Gibosa menguante (🌖)
      - 0.6875 a 0.8125: Cuarto menguante (🌗)
      - 0.8125 a 0.9375: Luna menguante (🌘)
    """
    try:
        phase = float(moon_phase)
    except Exception:
        return "❓"
    if phase < 0.0625 or phase >= 0.9375:
        return "🌑"
    elif phase < 0.1875:
        return "🌒"
    elif phase < 0.3125:
        return "🌓"
    elif phase < 0.4375:
        return "🌔"
    elif phase < 0.5625:
        return "🌕"
    elif phase < 0.6875:
        return "🌖"
    elif phase < 0.8125:
        return "🌗"
    else:
        return "🌘"

def construir_barra_viento(wind_speed):
    max_wind = 45.0
    ratio = max(0, min(1, wind_speed / max_wind))
    filled = round(ratio * 10)    

    if wind_speed < 10:
        block = "🟩"
    elif wind_speed < 20:
        block = "🟨"
    elif wind_speed < 30:
        block = "🟧"
    elif wind_speed < 40:
        block = "🟥"
    else:
        block = "🟪"
    
    return block * filled + "⬜" * (10 - filled)


def construir_barra_uv(uv):
    max_uv = 11
    ratio = max(0, min(1, uv / max_uv))
    filled = round(ratio * 10)
    if uv < 3:
        block = "🟩"
    elif uv < 6:
        block = "🟨"
    elif uv < 8:
        block = "🟧"
    else:
        block = "🟥"
    return block * filled + "⬜" * (10 - filled)
    
# FUNCIONES DE MONITOREO (IP, DuckDNS, PUERTOS)
def get_public_ip():
    try:
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        return response.json()['ip']
    except Exception as e:
        logging.exception("Error al obtener la IP pública")
        return "No disponible"

def get_isp_info(ip):
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=isp", timeout=5)
        data = response.json()
        return data.get("isp", "Desconocido")
    except Exception:
        return "Desconocido"

def update_duckdns(ip):
    try:
        response = requests.get(DUCKDNS_URL + ip, timeout=5)
        return "✅ DuckDNS actualizado correctamente" if "OK" in response.text else "❌ Error al actualizar DuckDNS"
    except Exception:
        return "❌ No se pudo conectar a DuckDNS"

def ping_ip_latency(ip):
    try:
        # Detecta si es Windows o Linux
        if platform.system().lower() == "windows":
            param = "-n"
        else:
            param = "-c"

        command = ["ping", param, "1", ip]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        output = result.stdout.lower()
        if "unreachable" in output or "timeout" in output:
            return "N/A"

        if result.returncode == 0:
            match = re.search(r"(?i)(?:time|tiempo|=|<)\s*([\d\.]+)\s*ms", output)
            return match.group(1) + "ms" if match else "0ms"

        return "N/A"
    except Exception as e:
        return f"Error: {e}"


def get_status_info(ip):
    latency = ping_ip_latency(ip)
    return ("🟢", latency) if latency != "N/A" else ("🔴", "")

def scan_specific_ports(ip):
    services = {"Plex": 32400, "WireGuard": [51820, 51821]}
    results = {}
    for service, port_info in services.items():
        if isinstance(port_info, list):
            open_ports = []
            for port in port_info:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex((ip, port))
                    if result == 0:
                        open_ports.append(port)
                    sock.close()
                except Exception:
                    continue
            results[service] = open_ports
        else:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((ip, port_info))
                sock.close()
                results[service] = [port_info] if result == 0 else []
            except Exception:
                results[service] = []
    return results

def build_progress_bar(cpu_usage, length=10, show_percentage=True):
    try:
        if isinstance(cpu_usage, str):
            cpu_usage = cpu_usage.strip()
            if cpu_usage.endswith('%'):
                value = float(cpu_usage.rstrip('%'))
            else:
                value = float(cpu_usage)
        else:
            value = float(cpu_usage)
    except Exception:
        return cpu_usage

    if value < 50:
        block = "🟩"
    elif value < 75:
        block = "🟨"
    elif value < 90:
        block = "🟧"
    else:
        block = "🟥"

    filled = int(round(value / 10))
    empty = length - filled
    bar = block * filled + "⬜" * empty
    return f"{bar} {value:.0f}%" if show_percentage else bar

def get_plex_ram_values():
    if not is_qnap_online():
        return None, None, None
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=QNAP_HOST, username=QNAP_USER, password=QNAP_PASSWORD,
                    allow_agent=False, look_for_keys=False)
        stdin, stdout, stderr = ssh.exec_command("cat /proc/meminfo")
        output = stdout.read().decode("utf-8")
        ssh.close()

        mem_total = None
        mem_available = None
        for line in output.splitlines():
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                mem_available = int(line.split()[1])
            if mem_total and mem_available:
                break

        if mem_total and mem_available:
            mem_used = mem_total - mem_available
            mem_used_mb = mem_used / 1024
            mem_total_mb = 16384  # Forzamos a 16384 MB
            usage_percent = (mem_used_mb / mem_total_mb) * 100
            return mem_used_mb, mem_total_mb, usage_percent
        else:
            return None, None, None
    except Exception as e:
        logging.exception("Error obteniendo la RAM")
        return None, None, None

def build_ram_bar(used_mb, total_mb, length=10):
    percent = (used_mb / total_mb) * 100
    if percent < 50:
        block = "🟩"
    elif percent < 75:
        block = "🟨"
    elif percent < 90:
        block = "🟧"
    else:
        block = "🟥"
    filled = int(round(percent / 100 * length))
    empty = length - filled
    return block * filled + "⬜" * empty

def get_weather_icon(main):
    icons = {
        "Clear": "☀️",
        "Clouds": "☁️",
        "Rain": "🌧️",
        "Drizzle": "🌦️",
        "Thunderstorm": "⛈️",
        "Snow": "❄️",
        "Mist": "🌫️",
        "Fog": "🌫️",
        "Haze": "🌁"
    }
    return icons.get(main, "🌍")

# --- Funciones para Netatmo (barras de colores) ---
def obtener_color_temp(temp, es_exterior):
    if es_exterior:
        if temp < 5:
            return "🟪"
        elif temp < 10:
            return "🟦"
        elif temp < 18:
            return "🟩"
        elif temp <= 22:
            return "🟨"
        elif temp <= 30:
            return "🟧"
        else:
            return "🟥"
    else:
        if temp < 19:
            return "🟩"
        elif temp <= 22:
            return "🟨"
        elif temp <= 26:
            return "🟧"
        else:
            return "🟥"

def construir_barra_temp(temp, redondear=False):
    min_temp, max_temp = -10, 40
    ratio = (temp - min_temp) / (max_temp - min_temp)
    ratio = max(0, min(1, ratio))
    filled = round(ratio * 10)
    if temp < 0:
        block = "🟦"
    elif temp < 15:
        block = "🟩"
    elif temp < 25:
        block = "🟨"
    elif temp < 35:
        block = "🟧"
    else:
        block = "🟥"
    return block * filled + "⬜" * (10 - filled)

def obtener_color_co2(co2):
    try:
        co2_value = float(co2)
    except Exception:
        return None
    if co2_value <= 700:
        return "🟢"  # Muy bueno
    elif co2_value <= 1000:
        return "🟡"  # Aceptable
    elif co2_value <= 2000:
        return "🟠"  # Malo
    else:
        return "🔴"  # Muy malo

# Función para construir la barra de lluvia en la última hora
def construir_barra_lluvia(lluvia, min_lluvia=0.1, max_lluvia=10, bloques=10):
    porcentaje = min(max(lluvia / max_lluvia, 0), 1)  # Limitar entre 0 y 1
    barras_rellenadas = round(porcentaje * bloques)
    # Forzar mínimo 1 bloque si lluvia > 0
    if lluvia > 0 and barras_rellenadas == 0:
        barras_rellenadas = 1
    return "🟦" * barras_rellenadas + "⬜" * (bloques - barras_rellenadas)

# Función para construir la barra de lluvia en las últimas 24h
def construir_barra_lluvia_24h(lluvia, min_lluvia=1, max_lluvia=120, bloques=10):
    porcentaje = min(max(lluvia / max_lluvia, 0), 1)  # Limitar entre 0 y 1
    barras_rellenadas = round(porcentaje * bloques)
    if lluvia > 0 and barras_rellenadas == 0:
        barras_rellenadas = 1
    return "🟦" * barras_rellenadas + "⬜" * (bloques - barras_rellenadas)

# FUNCIONES PARA DATOS DE OPEN HARDWARE MONITOR
def get_ohm_data():
    try:
        url = "http://192.168.0.225:8085/data.json"
        response = requests.get(url, timeout=5)
        return response.json()
    except Exception:
        return None

def find_sensor_value(data, sensor_id):
    if isinstance(data, dict):
        if "SensorId" in data and data.get("SensorId", "") == sensor_id:
            return data.get("Value", "N/A")
        for child in data.get("Children", []):
            result = find_sensor_value(child, sensor_id)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_sensor_value(item, sensor_id)
            if result is not None:
                return result
    return None

def build_speed_bar(speed, max_speed=100*1024*1024, length=10):
    proportion = speed / max_speed
    if proportion > 1:
        proportion = 1
    filled = int(round(proportion * length))
    empty = length - filled
    return "🟦" * filled + "⬜" * empty

# FUNCIONES PARA MÉTRICAS DEL SERVIDOR PLEX (sin uso de CPU)
def get_tautulli_sessions_info():
    try:
        url = f"{TAUTULLI_URL}/api/v2?apikey={TAUTULLI_APIKEY}&cmd=get_activity&force_refresh=1"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get("response", {}).get("result") != "success":
            return []
        sessions = data.get("response", {}).get("data", {}).get("sessions", [])
        if isinstance(sessions, dict):
            sessions = list(sessions.values())
        session_info_list = []
        state_icons = {
            "playing": "▶️",
            "paused": "⏸️",
            "buffering": "⏳",
            "stopped": "⏹️"
        }
        for session in sessions:
            user = session.get("friendly_name", "Desconocido")
            title = session.get("title", "Sin título")
            resolution = session.get("stream_video_resolution", "N/A")
            transcode_decision = session.get("transcode_decision", "Direct Play")
            progress = int(session.get("progress_percent", 0))
            playback_state = session.get("state", "playing")
            filled = progress // 10
            empty = 10 - filled
            bar = "🟧" * filled + "⬜" * empty
            state_icon = state_icons.get(playback_state.lower(), playback_state.capitalize())
            session_info_list.append(
                f"🎬 **{user}** - {title} (Resolución: {resolution}, {transcode_decision})\n"
                f"   {bar} {progress}% **{state_icon}**"
            )
        return session_info_list
    except Exception:
        return []

def get_plex_cpu_usage():
    if not is_qnap_online():
        return "QNAP Offline"
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=QNAP_HOST, username=QNAP_USER, password=QNAP_PASSWORD,
                    allow_agent=False, look_for_keys=False)
        stdin, stdout, stderr = ssh.exec_command("cat /proc/stat | head -n 1")
        first_line = stdout.read().decode("utf-8")
        parts = first_line.split()
        if parts[0] != "cpu":
            ssh.close()
            return "N/A"
        values1 = [int(x) for x in parts[1:]]
        total1 = sum(values1)
        idle1 = values1[3]
        time.sleep(INTERVAL)
        stdin, stdout, stderr = ssh.exec_command("cat /proc/stat | head -n 1")
        second_line = stdout.read().decode("utf-8")
        parts = second_line.split()
        values2 = [int(x) for x in parts[1:]]
        total2 = sum(values2)
        idle2 = values2[3]
        ssh.close()
        total_delta = total2 - total1
        idle_delta = idle2 - idle1
        if total_delta == 0:
            return "0.0%"
        usage = 100.0 * (total_delta - idle_delta) / total_delta
        return f"{usage:.2f}%"
    except Exception:
        return "N/A"

# FUNCIONES PARA CONTROL DE ILUMINACIÓN
HUE_BRIDGE_IP = "192.168.0.191"
HUE_USERNAME = ""
habitaciones = {
    "Dormitorio": [25],
    "Dormitorio Hugo": [3],
    "Pasillo": [7, 8, 9, 10, 20, 32],
    "Baño": [16, 34],
    "Cocina": [22, 27, 28, 29, 33, 38, 23, 24],
    "Terraza": [26, 30, 37],
    "Habitación PC": [39],
    "Comedor": [36, 31, 11, 12, 13, 14]
}

def get_room_lights_status(room):
    for luz_id in habitaciones[room]:
        url = f"http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/lights/{luz_id}"
        try:
            response = requests.get(url, timeout=5).json()
            if response.get("state", {}).get("on", False):
                return True
        except Exception:
            continue
    return False

def get_active_lights_rooms():
    active_rooms = []
    for room in habitaciones:
        if get_room_lights_status(room):
            active_rooms.append(room)
    return active_rooms

def turn_off_all_lights():
    for room in habitaciones:
        for luz_id in habitaciones[room]:
            url = f"http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/lights/{luz_id}/state"
            try:
                requests.put(url, json={"on": False}, timeout=5)
            except Exception as e:
                logging.error(f"Error apagando luz {luz_id} en {room}: {e}")

def turn_off_room_lights(room):
    for luz_id in habitaciones.get(room, []):
        url = f"http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/lights/{luz_id}/state"
        try:
            requests.put(url, json={"on": False}, timeout=5)
        except Exception as e:
            logging.error(f"Error apagando luz {luz_id} en {room}: {e}")

netatmo_access_token = netatmo_config.get("netatmo_access_token", "")
netatmo_refresh_token = netatmo_config.get("netatmo_refresh_token", "")
CLIENT_ID = netatmo_config.get("CLIENT_ID", "")
CLIENT_SECRET = netatmo_config.get("CLIENT_SECRET", "")


def refresh_netatmo_token():
    global netatmo_access_token, netatmo_refresh_token
    url = "https://api.netatmo.com/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": netatmo_refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        new_access_token = data.get("access_token")
        new_refresh_token = data.get("refresh_token")
        if new_access_token:
            netatmo_access_token = new_access_token
            logging.info(f"Nuevo access token obtenido: {netatmo_access_token}")
        if new_refresh_token:
            netatmo_refresh_token = new_refresh_token
            logging.info(f"Nuevo refresh token obtenido: {netatmo_refresh_token}")
        return netatmo_access_token
    except Exception as e:
        logging.exception("Error al refrescar el token de Netatmo")
        return None

def get_netatmo_data():
    global netatmo_access_token
    api_url = "https://api.netatmo.com/api/getstationsdata"
    params = {"access_token": netatmo_access_token}
    try:
        response = requests.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 403:
            logging.info("Access token expirado, refrescando...")
            new_token = refresh_netatmo_token()
            if new_token:
                params["access_token"] = new_token
                try:
                    response = requests.get(api_url, params=params, timeout=10)
                    response.raise_for_status()
                    return response.json()
                except Exception as e:
                    logging.exception("Error al obtener datos de Netatmo con nuevo token")
                    return None
            else:
                return None
        else:
            logging.error(f"Error al obtener datos de Netatmo: {http_err} {response.text}")
            return None
    except Exception as e:
        logging.exception("Error al obtener datos de Netatmo")
        return None

cached_netatmo_data = None
netatmo_last_update = 0

def update_netatmo_cache():
    global cached_netatmo_data, netatmo_last_update
    while True:
        new_data = get_netatmo_data()
        if new_data is not None:
            cached_netatmo_data = new_data
            netatmo_last_update = time.time()
            logging.info("Datos de Netatmo actualizados.")
        else:
            logging.warning("No se pudieron actualizar los datos de Netatmo.")
        time.sleep(300)

def get_netatmo_info():
    data = cached_netatmo_data
    netatmo_info = {
        "Comedor": {"Temperature": "N/A", "CO2": "N/A"},
        "Dormitorio": {"Temperature": "N/A", "CO2": "N/A"},
        "Terraza": {"Temperature": "N/A", "Humidity": "N/A"},
        "Lluvia": "Sin lluvia"
    }
    if data is None:
        return netatmo_info

    devices = data.get("body", {}).get("devices", [])
    for device in devices:
        station_name = device.get("station_name", "")
        if "Dormitorio-Terraza" in station_name:
            dashboard_data = device.get("dashboard_data", {})
            netatmo_info["Dormitorio"]["Temperature"] = dashboard_data.get("Temperature", "N/A")
            netatmo_info["Dormitorio"]["CO2"] = dashboard_data.get("CO2", "N/A")
            for module in device.get("modules", []):
                module_name = module.get("module_name", "").lower()
                if "exterior" in module_name:
                    dashboard_exterior = module.get("dashboard_data", {})
                    netatmo_info["Terraza"]["Temperature"] = dashboard_exterior.get("Temperature", "N/A")
                    netatmo_info["Terraza"]["Humidity"] = dashboard_exterior.get("Humidity", "N/A")
                if "rain" in module_name:
                    dashboard_rain = module.get("dashboard_data", {})
                    try:
                        rain_now = float(dashboard_rain.get("Rain", 0))
                    except:
                        rain_now = 0
                    try:
                        rain_1h = float(dashboard_rain.get("sum_rain_1", 0))
                    except:
                        rain_1h = 0
                    try:
                        rain_24h = float(dashboard_rain.get("sum_rain_24", 0))
                    except:
                        rain_24h = 0
                    if rain_now == 0 and rain_1h == 0 and rain_24h == 0:
                        netatmo_info["Lluvia"] = "Sin lluvia"
                    else:
                        netatmo_info["Lluvia"] = {"Ahora": rain_now, "1h": rain_1h, "24h": rain_24h}
        if "Paco Netatmo" in station_name:
            for module in device.get("modules", []):
                if "comedor" in module.get("module_name", "").lower():
                    dashboard_comedor = module.get("dashboard_data", {})
                    netatmo_info["Comedor"]["Temperature"] = dashboard_comedor.get("Temperature", "N/A")
                    netatmo_info["Comedor"]["CO2"] = dashboard_comedor.get("CO2", "N/A")
    return netatmo_info

# FUNCIONES PARA OBTENER LAS VELOCIDADES DE RED DEL QNAP
def parse_net_stats(output, interface):
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(interface + ":"):
            parts = line.split()
            try:
                recv_bytes = int(parts[1])
                trans_bytes = int(parts[9])
                return recv_bytes, trans_bytes
            except (IndexError, ValueError):
                return None, None
    return None, None

def human_readable(num_bytes, suffix="B"):
    factor = 1024.0
    for unit in ["", "K", "M", "G", "T", "P"]:
        if num_bytes < factor:
            return f"{num_bytes:.2f} {unit}{suffix}"
        num_bytes /= factor
    return f"{num_bytes:.2f} P{suffix}"

def get_plex_net_speed():
    if not is_qnap_online():
        return "N/A", "N/A", 0, 0
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=QNAP_HOST, username=QNAP_USER, password=QNAP_PASSWORD,
                    allow_agent=False, look_for_keys=False)
        stdin, stdout, stderr = ssh.exec_command("cat /proc/net/dev")
        output = stdout.read().decode("utf-8")
        prev_recv, prev_trans = parse_net_stats(output, NET_INTERFACE)
        if prev_recv is None or prev_trans is None:
            ssh.close()
            return "N/A", "N/A", 0, 0
        time.sleep(INTERVAL)
        stdin, stdout, stderr = ssh.exec_command("cat /proc/net/dev")
        output = stdout.read().decode("utf-8")
        current_recv, current_trans = parse_net_stats(output, NET_INTERFACE)
        ssh.close()
        if current_recv is None or current_trans is None:
            return "N/A", "N/A", 0, 0
        diff_recv = current_recv - prev_recv
        diff_trans = current_trans - prev_trans
        download_speed = diff_recv / INTERVAL
        upload_speed = diff_trans / INTERVAL
        download_hr = human_readable(download_speed)
        upload_hr = human_readable(upload_speed)
        return download_hr, upload_hr, download_speed, upload_speed
    except Exception:
        return "N/A", "N/A", 0, 0

def is_qnap_online():
    try:
        socket.create_connection((QNAP_HOST, 22), timeout=2)
        return True
    except Exception:
        return False

# FUNCIONES PARA ENCENDER Y APAGAR EL QNAP
def wake_qnap():
    try:
        mac = QNAP_MAC.replace(":", "").replace("-", "")
        if len(mac) != 12:
            return "MAC inválida"
        data = bytes.fromhex("FF" * 6 + mac * 16)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(data, ("192.168.0.255", 9))
        s.close()
        return "Paquete WOL enviado"
    except Exception as e:
        return f"Error: {str(e)}"

def shutdown_qnap():
    host = QNAP_HOST
    username = QNAP_USER
    password = QNAP_PASSWORD
    command = "poweroff"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=host, username=username, password=password,
                       allow_agent=False, look_for_keys=False)
        client.exec_command(command)
    except Exception as e:
        logging.error(f"Error al apagar QNAP: {e}")
    finally:
        client.close()

# FUNCIONES PARA ACCESOS (Nuki)
NUKI_API_URL = "http://192.168.0.76:8080"
LOCAL_NUKI_TOKEN = ""
ENTRADA_COM_ID = 
ENTRADA_PISO_ID = 

def obtener_estado_nuki(smartlock_id, device_type=None):
    # Llamamos a /list para obtener todos los dispositivos
    url = f"{NUKI_API_URL}/list?token={LOCAL_NUKI_TOKEN}"
    try:
        response = requests.get(url, timeout=10)
    except Exception as e:
        logging.error(f"Error al obtener estado de Nuki: {e}")
        return "Error"
    if response.status_code == 200:
        dispositivos = response.json()
        # Buscamos el dispositivo que coincida con smartlock_id
        for dispositivo in dispositivos:
            if dispositivo.get("nukiId") == smartlock_id:
                estado = dispositivo.get("lastKnownState", {}).get("state", None)
                if estado == 1:
                    return "Bloqueado"
                elif estado == 3:
                    return "Desbloqueado"
                elif estado == 5:
                    return "Unlatched"
                else:
                    return "Estado desconocido"
        return "No encontrado"
    else:
        logging.error(f"Error al obtener estado, código: {response.status_code} - {response.text}")
        return "Error"

def obtener_info_nuki(smartlock_id):
    url = f"http://192.168.0.76:8080/list?token=717978"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            dispositivos = response.json()
            for dispositivo in dispositivos:
                if dispositivo.get("nukiId") == smartlock_id:
                    return dispositivo
            return None
        else:
            logging.error("Error al obtener info de Nuki: " + str(response.status_code))
            return None
    except Exception as e:
        logging.error("Error al obtener info de Nuki: " + str(e))
        return None

def update_battery_status():
    global battery_value, battery_last_update
    while True:
        valid_value_found = False
        # Se intenta cada 10 segundos hasta conseguir un valor válido
        while not valid_value_found:
            nuki_info = obtener_info_nuki(ENTRADA_PISO_ID)
            new_value = None
            if nuki_info:
                new_value = nuki_info.get("lastKnownState", {}).get("batteryChargeState")
                if new_value is not None:
                    try:
                        new_value = int(new_value)
                    except Exception:
                        new_value = None
            if new_value is not None:
                battery_value = new_value
                battery_last_update = time.time()
                logging.info(f"Estado de batería actualizado: {battery_value}%")
                valid_value_found = True
            else:
                logging.warning("No se pudo obtener el valor de batería, reintentando en 10 segundos...")
                time.sleep(10)
        # Una vez obtenido un valor válido, se espera 1 hora antes de la siguiente actualización
        time.sleep(3600)


def abrir_entrada_com():
    url = f"{NUKI_API_URL}/lockAction?nukiId={ENTRADA_COM_ID}&deviceType=2&action=3&token={LOCAL_NUKI_TOKEN}"
    try:
        response = requests.get(url, timeout=10)
    except Exception as e:
        logging.error(f"Error al abrir EntradaCom: {e}")
        return f"Error: {e}"
    if response.status_code == 200:
        return "EntradaCom abierta correctamente."
    else:
        return f"Error al abrir EntradaCom ({response.status_code}): {response.text}"

def abrir_entrada_piso():
    url = f"{NUKI_API_URL}/lockAction?nukiId={ENTRADA_PISO_ID}&deviceType=0&action=3&token={LOCAL_NUKI_TOKEN}"
    attempts = 2
    for i in range(attempts):
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return "EntradaPiso abierta correctamente."
            else:
                logging.warning(f"Intento {i+1}: Error al abrir EntradaPiso ({response.status_code}).")
        except Exception as e:
            logging.error(f"Intento {i+1}: Error al abrir EntradaPiso: {e}")
        time.sleep(1)
    return f"Error al abrir EntradaPiso después de {attempts} intentos."

def lock_entrada_piso():
    url = f"{NUKI_API_URL}/lockAction?nukiId={ENTRADA_PISO_ID}&deviceType=0&action=2&token={LOCAL_NUKI_TOKEN}"
    try:
        response = requests.get(url, timeout=10)
    except Exception as e:
        logging.error(f"Error al bloquear EntradaPiso: {e}")
        return f"Error: {e}"
    if response.status_code == 200:
        return "EntradaPiso bloqueada correctamente."
    else:
        return f"Error al bloquear EntradaPiso ({response.status_code})."

# --- NUEVA FUNCIÓN PARA OBTENER DESCARGAS DE QBittorrent ---
def get_qb_downloads():
    if not is_qnap_online():
        return []
    try:
        qb_host = "http://192.168.0.160:6363"
        qb_client = qbittorrentapi.Client(host=qb_host)
        qb_client.auth_log_in()
        active_torrents = qb_client.torrents_info(filter="downloading")
        using_completed = False
        if active_torrents:
            torrents = active_torrents
        else:
            completed_torrents = qb_client.torrents_info(filter="completed")
            completed_torrents = [t for t in completed_torrents if getattr(t, "completion_on", 0) > 0]
            completed_torrents.sort(key=lambda t: t.completion_on, reverse=True)
            torrents = completed_torrents[:3]
            using_completed = True

        downloads_info = []
        max_name_length = 35
        if using_completed:
            downloads_info.append("**(Últimas finalizadas)**")
            for torrent in torrents:
                name = torrent.name
                abbreviated_name = name if len(name) <= max_name_length else name[:max_name_length] + "..."
                downloads_info.append(f"🔹{abbreviated_name} - **Completado**")
        else:
            total_segments = 10
            for torrent in torrents:
                name = torrent.name
                abbreviated_name = name if len(name) <= max_name_length else name[:max_name_length] + "..."
                filled = int(torrent.progress * total_segments)
                bar = "🟩" * filled + "⬜" * (total_segments - filled)
                speed_mb = torrent.dlspeed / 1e6
                downloads_info.append(f"{abbreviated_name}\n{bar} {speed_mb:.2f} MB/s")
        
        return downloads_info
    except Exception as e:
        logging.error(f"Error obteniendo descargas de qBittorrent: {e}")
        return []

# TECLADO INLINE
def get_main_keyboard():
    buttons = [
        [InlineKeyboardButton("➕ Añadir IP Pública", callback_data="add_ip_publica"),
         InlineKeyboardButton("❌ Borrar IP Pública", callback_data="del_ip_publica")],
        [InlineKeyboardButton("➕ Añadir IP Privada", callback_data="add_ip_privada"),
         InlineKeyboardButton("❌ Borrar IP Privada", callback_data="del_ip_privada")],
        [InlineKeyboardButton("🔌 Encender QNAP", callback_data="wake_qnap"),
         InlineKeyboardButton("🛑 Apagar QNAP", callback_data="shutdown_qnap")],
        [InlineKeyboardButton("🚪 Abrir EntradaCom", callback_data="abrir_entrada_com"),
         InlineKeyboardButton("🚪 Abrir EntradaPiso", callback_data="abrir_entrada_piso")]
    ]
    buttons.append([InlineKeyboardButton("💡 Control Avanzado de Luces", callback_data="control_avanzado_luces")])
    estado_entrada_piso = obtener_estado_nuki(ENTRADA_PISO_ID, device_type=0)
    if estado_entrada_piso == "Desbloqueado":
        buttons.append([InlineKeyboardButton("🔒 Bloquear EntradaPiso", callback_data="bloquear_entrada_piso")])
    active_rooms = get_active_lights_rooms()
    if len(active_rooms) > 1:
        buttons.append([InlineKeyboardButton("💡 Apagar todas las luces", callback_data="apagar_luces")])
    for room in active_rooms:
        buttons.append([InlineKeyboardButton(f"🟡 Apagar {room}", callback_data=f"apagar_luces_{room}")])
    return InlineKeyboardMarkup(buttons)

# ARMADO DEL MENSAJE DE ESTADO
def build_status_message():
    global last_update_time, last_public_ip_change_time, previous_public_ip, last_public_ip
    public_ip = last_public_ip if last_public_ip is not None else get_public_ip()
    isp_name = get_isp_info(public_ip)
    duckdns_status = update_duckdns(public_ip)
    services = scan_specific_ports(public_ip)
    service_lines = []
    if services.get("Plex") and services["Plex"]:
        service_lines.append(f"Plex: {services['Plex'][0]}")
    if services.get("WireGuard") and services["WireGuard"]:
        wg_ports = ", ".join(str(port) for port in services["WireGuard"])
        service_lines.append(f"WireGuard: {wg_ports}")
    ports_text = "; ".join(service_lines) if service_lines else "Ninguno"

    message_text = "🌐 **Monitoreo de Servicios** 🌐\n\n"
    message_text += f"📡 **IP Pública:** {public_ip}\n"
    message_text += f"🏢 **ISP:** {isp_name}\n"
    message_text += f"🦆 **DuckDNS:** {duckdns_status}\n"
    message_text += f"\n🔹 **DuckDNS Domain:** {DUCKDNS_DOMAIN}\n\n"

    message_text += "💻 **miniPC Server:**\n"
    ohm_data = get_ohm_data()
    if ohm_data:
        cpu_load = find_sensor_value(ohm_data, "/intelcpu/0/load/0") or "N/A"
        cpu_temp = find_sensor_value(ohm_data, "/intelcpu/0/temperature/6") or "N/A"
        mem_used = find_sensor_value(ohm_data, "/ram/data/0") or "N/A"
        download_speed_ohm = find_sensor_value(ohm_data, "/nic/%7B96BABA16-4C42-4B2B-908A-08449B80E1D8%7D/throughput/8") or "N/A"
        upload_speed_ohm = find_sensor_value(ohm_data, "/nic/%7B96BABA16-4C42-4B2B-908A-08449B80E1D8%7D/throughput/7") or "N/A"
        progress_bar = build_progress_bar(cpu_load) if cpu_load != "N/A" else "N/A"
        message_text += f"• CPU Load: {progress_bar}\n"
        message_text += f"• CPU Temp: {cpu_temp}\n"
        message_text += f"• Memory Used: {mem_used}\n"
        message_text += f"• Download Speed: {download_speed_ohm}\n"
        message_text += f"• Upload Speed: {upload_speed_ohm}\n"
    else:
        message_text += "⚠️ No se pudo obtener datos de Open Hardware Monitor.\n"

    message_text += "\n📁 **QnaP Server:**\n"
    cpu_usage = get_plex_cpu_usage()
    if cpu_usage != "N/A":
        cpu_percentage = cpu_usage.strip() if "%" in cpu_usage else f"{cpu_usage}%"
        progress_bar_plex = build_progress_bar(cpu_usage, show_percentage=False)
    else:
        cpu_percentage = "N/A"
        progress_bar_plex = "N/A"
    message_text += f"• CPU: {cpu_percentage}\n"
    message_text += f"{progress_bar_plex}\n"

    mem_vals = get_plex_ram_values()
    if mem_vals[0] is not None:
        ram_info = f"{mem_vals[0]:.2f} MB ({mem_vals[2]:.0f}%)"
        ram_bar = build_ram_bar(mem_vals[0], mem_vals[1])
    else:
        ram_info = "N/A"
        ram_bar = "N/A"
    message_text += f"• RAM: {ram_info}\n"
    message_text += f"{ram_bar}\n"

    download_hr, upload_hr, raw_download, raw_upload = get_plex_net_speed()
    message_text += f"• Download: {download_hr}\n"
    message_text += f"{build_speed_bar(raw_download)}\n"
    message_text += f"• Upload: {upload_hr}\n"
    message_text += f"{build_speed_bar(raw_upload)}\n"

    # Sección qBittorrent
    message_text += "\n📥 **Descargas en Qbit:**\n"
    qb_downloads = get_qb_downloads()
    if not qb_downloads:
        message_text += "⚠️ No hay descargas activas.\n"
    else:
        for download in qb_downloads:
            message_text += f"{download}\n"

    sessions_info = get_tautulli_sessions_info()
    if sessions_info:
        message_text += "•🎞 **Sesiones activas:**\n"
        for sess in sessions_info:
            message_text += f"   - {sess}\n"
    else:
        message_text += "• **Sesiones activas:** 0\n"

    message_text += "\n🌍 **IPs Públicas Monitorizadas:**\n"
    if ips_publicas:
        for alias, ip in list(ips_publicas.items()):
            icon, latency = get_status_info(ip)
            message_text += f"• {icon} {alias} -> {ip} {latency}\n" if latency else f"• {icon} {alias} -> {ip}\n"
    else:
        message_text += "⚠️ Sin IPs públicas añadidas.\n"

    message_text += "\n🏠 **IPs Privadas Monitorizadas:**\n"
    if ips_privadas:
        for alias, ip in list(ips_privadas.items()):
            icon, latency = get_status_info(ip)
            message_text += f"• {icon} {alias} -> {ip} {latency}\n" if latency else f"• {icon} {alias} -> {ip}\n"
    else:
        message_text += "⚠️ Sin IPs privadas añadidas.\n"

    # Sección Openweather
    message_text += "\n🌤 **Openweather:**\n"
    openweather_data = get_openweather_data()  # Función que retorna cached_openweather_data
    if openweather_data:
        if current_location_name != DEFAULT_LOCATION_NAME:
            message_text += f"📍 Ubicación temporal: {current_location_name}\n"
        time_obtencion = time.strftime('%H:%M:%S', time.localtime(openweather_last_update))
        message_text += f"⏰ Hora de obtención: {time_obtencion}\n"
        # Resto del formato (estado, temperatura, viento, etc.)


        current = openweather_data.get("current", {})
        weather = current.get("weather", [{}])[0]
        description = weather.get("description", "").capitalize()
        weather_main = weather.get("main", "")
        icon_estado = get_weather_icon(weather_main)
        # Verificar si hay alertas activas
        alerts = openweather_data.get("alerts")
        if alerts:
            message_text += "\n🚨 **Alertas Activas:**\n"
            for alert in alerts:
                sender = alert.get("sender_name", "Desconocido")
                event = alert.get("event", "Alerta")
                alert_start = time.strftime('%H:%M:%S', time.localtime(alert.get("start", time.time())))
                alert_end = time.strftime('%H:%M:%S', time.localtime(alert.get("end", time.time())))
                description = alert.get("description", "Sin descripción")
                message_text += f"• {event} por {sender} (desde {alert_start} hasta {alert_end})\n"

                # Opcional: puedes agregar parte de la descripción si es muy larga.
        message_text += f"🔸Estado: {description} {icon_estado}\n"
        
        # Agregar la fase lunar justo debajo del estado:
        daily = openweather_data.get("daily", [])
        if daily and len(daily) > 0:
            moon_phase = daily[0].get("moon_phase")
            if moon_phase is not None:
                moon_icon = get_moon_phase_icon(moon_phase)
                message_text += f"🔸Fase Lunar: {moon_icon}\n"
        
        # Probabilidad de precipitación
        hourly = openweather_data.get("hourly", [])
        pop = int(hourly[0].get("pop", 0) * 100) if hourly else 0
        pop_icon = "🌧" if pop > 0 else "☀️"
        message_text += f"🔹Probabilidad de precipitación: {pop}% {pop_icon}\n\n"
        
        # Temperatura y barra
        temp = current.get("temp", 0)
        feels_like = current.get("feels_like", 0)
        barra_temp = construir_barra_temp(float(temp))
        message_text += f"🏙 Temperatura: {temp:.2f}°C (sensación: {feels_like:.0f}°C)\n{barra_temp}\n"
        
        # Viento y barra
        wind_speed = current.get("wind_speed", 0) * 3.6
        wind_deg = current.get("wind_deg", 0)
        wind_direction = get_wind_direction(wind_deg)
        barra_viento = construir_barra_viento(wind_speed)
        message_text += f"💨 Viento: {wind_speed:.0f} km/h {wind_direction}\n{barra_viento}\n"
        
        # Índice UV y barra
        uv = current.get("uvi", 0)
        barra_uv = construir_barra_uv(uv)
        message_text += f"🔆 Índice UV: {uv:.2f}\n{barra_uv}\n"
        # Dentro de la sección de Openweather, después de la parte de pronóstico diario:

        # Pronóstico por hora para las próximas 9 horas (formato similar al diario)
        hourly = openweather_data.get("hourly", [])
        if hourly and len(hourly) >= 10:
            message_text += "\n🔸Pronóstico por hora:\n"
            # Se omite la entrada actual y se muestran las 9 siguientes
            for hour_data in hourly[2:7]:
                dt = hour_data.get("dt")
                hour_str = time.strftime('%H', time.localtime(dt))
                weather_hour = hour_data.get("weather", [{}])[0]
                icon_hour = get_weather_icon(weather_hour.get("main", ""))
                temp_hour = hour_data.get("temp", 0)
                pop_hour = int(hour_data.get("pop", 0) * 100)
                wind_speed_hour = hour_data.get("wind_speed", 0) * 3.6
                message_text += f"🕑 {hour_str} {icon_hour} | 🌡️ {temp_hour:.1f}°C | 💧 {pop_hour}% | 🌬️ {wind_speed_hour:.0f} km/h \n"

        # Pronóstico de los próximos 3 días
        daily = openweather_data.get("daily", [])
        if daily and len(daily) >= 4:
            message_text += "▪🔸Pronostico:\n"
            for day_data in daily[1:4]:
                dt = day_data.get("dt")
                day_str = time.strftime('%d', time.localtime(dt))
                weather_day = day_data.get("weather", [{}])[0]
                icon_day = get_weather_icon(weather_day.get("main", ""))
                temp_day = day_data.get("temp", {}).get("day", 0)
                pop_day = int(day_data.get("pop", 0) * 100)
                wind_speed_day = day_data.get("wind_speed", 0) * 3.6
                message_text += f"📅 {day_str} {icon_day} | 🌡️ {temp_day:.1f}°C | 💧 {pop_day}% | 🌬️ {wind_speed_day:.0f} km/h \n"
    else:
        message_text += "   ⚠️ No se pudo obtener datos del clima.\n"

    # Sección Netatmo
    netatmo_info = get_netatmo_info()
    message_text += "\n🌦 **Netatmo:**\n"
    if cached_netatmo_data:
        time_obtencion_netatmo = time.strftime('%H:%M:%S', time.localtime(netatmo_last_update))
        message_text += f"⏰ Hora de obtención: {time_obtencion_netatmo}\n"
    habitaciones_netatmo = {
        "Comedor": {"temp": netatmo_info.get("Comedor", {}).get("Temperature", "N/A"),
                    "co2": netatmo_info.get("Comedor", {}).get("CO2", None),
                    "exterior": False},
        "Dormitorio": {"temp": netatmo_info.get("Dormitorio", {}).get("Temperature", "N/A"),
                       "co2": netatmo_info.get("Dormitorio", {}).get("CO2", None),
                       "exterior": False},
        "Terraza": {"temp": netatmo_info.get("Terraza", {}).get("Temperature", "N/A"),
                    "co2": None,
                    "exterior": True}
    }
    for habitacion, datos in habitaciones_netatmo.items():
        temp = datos["temp"]
        if temp != "N/A":
            temp_bar = construir_barra_temp(float(temp), datos["exterior"])
            message_text += f"🏡 **{habitacion}** {temp}°C\n{temp_bar}\n"
        co2 = datos["co2"]
        if co2 is not None:
            color_co2 = obtener_color_co2(co2)
            message_text += f"CO₂: {color_co2} {co2} ppm\n"

    # Sección Iluminación
    global lights_on_times
    message_text += "\n💡 **Iluminación:**\n"
    active_rooms = get_active_lights_rooms()
    # Registrar la hora de encendido si es la primera detección
    for room in active_rooms:
        if room not in lights_on_times:
            lights_on_times[room] = time.time()
    # Limpiar aquellas que ya se apagaron
    for room in list(lights_on_times.keys()):
        if room not in active_rooms:
            del lights_on_times[room]
    if active_rooms:
        for room in active_rooms:
            activation_time = lights_on_times.get(room)
            formatted_time = time.strftime('%H:%M:%S', time.localtime(activation_time)) if activation_time else "N/A"
            message_text += f"• 🟡 {room} (**{formatted_time}**)\n"
    else:
        message_text += "✅ No hay luces encendidas.\n"

    global entrada_piso_last_state, entrada_piso_last_change_time
    estado_entrada_piso = obtener_estado_nuki(ENTRADA_PISO_ID, device_type=4)
    # Actualizamos solo si el nuevo estado es "Bloqueado" o "Desbloqueado"
    if estado_entrada_piso in ["Bloqueado", "Desbloqueado"]:
        if entrada_piso_last_state is None or estado_entrada_piso != entrada_piso_last_state:
            entrada_piso_last_state = estado_entrada_piso
            entrada_piso_last_change_time = time.time()
    formatted_change_time = time.strftime('%H:%M:%S', time.localtime(entrada_piso_last_change_time)) if entrada_piso_last_change_time else "N/A"

    # Obtener la información completa de la cerradura para extraer el nivel de batería
    nuki_info = obtener_info_nuki(ENTRADA_PISO_ID)
    battery = None
    if nuki_info:
        battery = nuki_info.get("lastKnownState", {}).get("batteryChargeState")
    if battery is not None:
        try:
            battery = int(battery)
        except Exception:
            battery = None

    # Seleccionar el icono según el valor obtenido: 🔋 si >= 50%, 🪫 si es menor
    if battery is not None:
        battery_icon = "🔋" if battery >= 50 else "🪫"
    else:
        battery_icon = "❓"

    # Dentro de la sección "Accesos"
    message_text += "\n🚪 **Accesos:**\n"
    message_text += f"• **EntradaPiso**: {estado_entrada_piso} (**{formatted_change_time}**)\n"
    if battery_value is not None:
        # Seleccionamos el icono según el porcentaje: 🔋 si es >= 50, 🪫 si es menor
        battery_icon = "🔋" if battery_value >= 50 else "🪫"
        message_text += f"• **Batería:** {battery_icon} ({battery_value}%)\n"
    else:
        message_text += f"• **Batería:** N/A\n"

    message_text += f"\n🔓 **Puertos abiertos en IP Pública:**\n• {ports_text}\n"
    if last_update_time:
        formatted_update_time = time.strftime('%H:%M:%S', time.localtime(last_update_time))
    else:
        formatted_update_time = "N/A"
    if last_public_ip_change_time:
        delta = time.time() - last_public_ip_change_time
        hours = int(delta // 3600)
        minutes = int((delta % 3600) // 60)
        time_since_change = f"{hours} hrs {minutes} min" if hours > 0 else f"{minutes} min"
    else:
        time_since_change = "N/A"
    message_text += f"\n🕒 Última actualización: {formatted_update_time}"
    message_text += f"\n🔄 Cambio de IP hace: {time_since_change}"
    message_text += f"\n📤 IP anterior: {previous_public_ip}"

    return message_text

# BORRADO DE MENSAJES (TRACKING)
def clear_all_messages(chat_id):
    if chat_id in tracked_message_ids:
        try:
            app.delete_messages(chat_id, list(tracked_message_ids[chat_id]))
            tracked_message_ids[chat_id].clear()
        except Exception as e:
            logging.error(f"Error al borrar mensajes en el chat {chat_id}: {e}")

# HANDLERS DEL BOT
@app.on_message(filters=lambda client, message: message.text is not None and not message.text.startswith("/"), group=0)
def track_message(client, message):
    chat_id = message.chat.id
    if chat_id in status_messages:
        if message.id != status_messages[chat_id]:
            if chat_id not in tracked_message_ids:
                tracked_message_ids[chat_id] = set()
            tracked_message_ids[chat_id].add(message.id)

@app.on_message(filters.command("ub"))
def change_location(client, message):
    global current_openweather_coords, openweather_location_set_time, current_location_name
    global cached_openweather_data, openweather_last_update
    if len(message.command) < 2:
        temp_msg = message.reply_text("Debes especificar el nombre de un municipio. Ejemplo: /ub Barcelona")
        time.sleep(5)
        client.delete_messages(message.chat.id, [message.id, temp_msg.id])
        return
    # Concatenamos los argumentos para formar el nombre completo del municipio
    municipality = " ".join(message.command[1:])
    
    # Usar la API de geocodificación para obtener coordenadas
    geocode_url = f"http://api.openweathermap.org/geo/1.0/direct?q={municipality}&limit=1&appid={OPENWEATHER_API_KEY}"
    try:
        response = requests.get(geocode_url, timeout=10)
        data = response.json()
        if data:
            lat = data[0].get("lat")
            lon = data[0].get("lon")
            if lat is not None and lon is not None:
                current_openweather_coords = (lat, lon)
                openweather_location_set_time = time.time()
                current_location_name = municipality
                # Forzar actualización inmediata de los datos
                new_data = fetch_openweather_data()
                if new_data:
                    cached_openweather_data = new_data
                    openweather_last_update = time.time()
                    reply_msg = message.reply_text(
                        f"Ubicación actualizada a: {municipality}. Datos meteorológicos actualizados y se usarán durante 4 horas."
                    )
                else:
                    reply_msg = message.reply_text(
                        "No se pudo obtener datos para esa ubicación. Inténtalo de nuevo."
                    )
            else:
                reply_msg = message.reply_text("No se pudieron obtener las coordenadas para esa ubicación.")
        else:
            reply_msg = message.reply_text("No se encontró la ubicación especificada.")
    except Exception as e:
        logging.exception("Error al obtener datos de ubicación")
        reply_msg = message.reply_text("Error al buscar la ubicación. Inténtalo de nuevo.")
    
    # Eliminar el mensaje del usuario y la respuesta del bot después de 5 segundos
    time.sleep(5)
    client.delete_messages(message.chat.id, [message.id, reply_msg.id])


@app.on_message(filters.chat(ALLOWED_CHAT_IDS) & filters.command("start"))
def start_handler(client, message):
    chat_id = message.chat.id
    if chat_id not in status_messages:
        msg = app.send_message(chat_id, "🚀 Iniciando monitoreo de IPs...")
        status_messages[chat_id] = msg.id
        tracked_message_ids[chat_id] = set()
    else:
        app.send_message(chat_id, "El bot ya está activo en este chat.")

@app.on_callback_query()
def handle_callbacks(client, callback_query):
    chat_id = callback_query.message.chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        return
    data = callback_query.data
    user_id = callback_query.from_user.id
    callback_query.answer()
    if data == "control_avanzado_luces":
        # Envía el comando /hue al chat
        app.send_message(chat_id, "/hue")
        callback_query.answer("Comando /hue enviado", show_alert=True)
    if data in ["add_ip_publica", "add_ip_privada", "del_ip_publica", "del_ip_privada"]:
        action = "Añadir" if "add" in data else "Borrar"
        tipo_ip = "pública" if "publica" in data else "privada"
        prompt = (f"✏️ Envía el alias y la IP (separados por un espacio) para {action.lower()} (ejemplo: MiCasa 192.168.1.10)") if action == "Añadir" else f"✏️ Envía el alias de la IP {tipo_ip} que deseas borrar:"
        msg = callback_query.message.reply_text(prompt)
        logging.info(f"Estableciendo estado para el usuario {user_id}: ({action}, {tipo_ip}, {msg.id})")
        user_states[user_id] = (action, tipo_ip, msg.id)
        clear_all_messages(chat_id)
    elif data == "wake_qnap":
        result = wake_qnap()
        callback_query.answer(f"{result}", show_alert=True)
    elif data == "shutdown_qnap":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirmar apagado", callback_data="confirm_shutdown_qnap"),
             InlineKeyboardButton("Cancelar apagado", callback_data="cancel_shutdown_qnap")]
        ])
        confirmation_msg = callback_query.message.reply_text("⚠️ ¿Estás seguro de que deseas apagar el QNAP?", reply_markup=keyboard)
        shutdown_confirmations[user_id] = confirmation_msg.id
    elif data == "confirm_shutdown_qnap":
        if user_id in shutdown_confirmations:
            try:
                app.delete_messages(chat_id, shutdown_confirmations[user_id])
            except Exception as e:
                logging.error(e)
            shutdown_confirmations.pop(user_id, None)
        shutdown_qnap()
        callback_query.answer("Comando de apagado enviado.", show_alert=True)
    elif data == "cancel_shutdown_qnap":
        if user_id in shutdown_confirmations:
            try:
                app.delete_messages(chat_id, shutdown_confirmations[user_id])
            except Exception as e:
                logging.error(e)
            shutdown_confirmations.pop(user_id, None)
        callback_query.answer("Apagado cancelado.", show_alert=True)
    elif data == "apagar_luces":
        turn_off_all_lights()
        callback_query.answer("Todas las luces han sido apagadas", show_alert=True)
    elif data == "abrir_entrada_com":
        result = abrir_entrada_com()
        callback_query.answer(result, show_alert=True)
    elif data == "abrir_entrada_piso":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirmar apertura", callback_data="confirm_abrir_entrada_piso"),
             InlineKeyboardButton("Cancelar", callback_data="cancel_abrir_entrada_piso")]
        ])
        confirmation_msg = callback_query.message.reply_text("⚠️ ¿Confirmas la apertura de EntradaPiso?", reply_markup=keyboard)
        apertura_confirmations[user_id] = confirmation_msg.id
    elif data == "confirm_abrir_entrada_piso":
        if user_id in apertura_confirmations:
            try:
                app.delete_messages(chat_id, apertura_confirmations[user_id])
            except Exception as e:
                logging.error(e)
            apertura_confirmations.pop(user_id, None)
        result = abrir_entrada_piso()
        callback_query.answer(result, show_alert=True)
    elif data == "cancel_abrir_entrada_piso":
        if user_id in apertura_confirmations:
            try:
                app.delete_messages(chat_id, apertura_confirmations[user_id])
            except Exception as e:
                logging.error(e)
            apertura_confirmations.pop(user_id, None)
        callback_query.answer("Apertura cancelada.", show_alert=True)
    elif data.startswith("apagar_luces_"):
        room = data.replace("apagar_luces_", "")
        turn_off_room_lights(room)
        callback_query.answer(f"Luces de {room} apagadas", show_alert=True)
    elif data == "bloquear_entrada_piso":
        result = lock_entrada_piso()
        callback_query.answer(result, show_alert=True)

@app.on_message(filters.text, group=1)
def process_ip_input(client, message):
    # Verificar si existe un remitente en el mensaje
    if message.from_user is None:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text.strip()
    if user_id not in user_states:
        return
    logging.info(f"Procesando input del usuario {user_id}: '{text}' con estado {user_states[user_id]}")
    action, tipo_ip, msg_id = user_states.pop(user_id)
    if action == "Añadir":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            temp_msg = message.reply_text("⚠️ Formato incorrecto. Usa: Alias IP")
            time.sleep(5)
            app.delete_messages(chat_id, [message.id, temp_msg.id, msg_id])
            return
        alias, ip = parts[0], parts[1]
        if not re.match(IP_REGEX, ip):
            temp_msg = message.reply_text("⚠️ IP inválida. Intenta nuevamente.")
            time.sleep(5)
            app.delete_messages(chat_id, [message.id, temp_msg.id, msg_id])
            return
        if tipo_ip == "pública":
            if alias not in ips_publicas:
                ips_publicas[alias] = ip
                save_config()
                temp_msg = message.reply_text(f"✅ IP {ip} añadida con alias '{alias}'.")
            else:
                temp_msg = message.reply_text(f"⚠️ El alias '{alias}' ya existe.")
        else:
            if alias not in ips_privadas:
                ips_privadas[alias] = ip
                save_config()
                temp_msg = message.reply_text(f"✅ IP {ip} añadida con alias '{alias}'.")
            else:
                temp_msg = message.reply_text(f"⚠️ El alias '{alias}' ya existe.")
    else:
        alias = text
        if tipo_ip == "pública":
            if alias in ips_publicas:
                del ips_publicas[alias]
                save_config()
                temp_msg = message.reply_text(f"✅ IP asociada a '{alias}' eliminada.")
            else:
                temp_msg = message.reply_text(f"❌ No se encontró el alias '{alias}'.")
        else:
            if alias in ips_privadas:
                del ips_privadas[alias]
                save_config()
                temp_msg = message.reply_text(f"✅ IP asociada a '{alias}' eliminada.")
            else:
                temp_msg = message.reply_text(f"❌ No se encontró el alias '{alias}'.")
    time.sleep(5)
    app.delete_messages(chat_id, [message.id, temp_msg.id, msg_id])
    clear_all_messages(chat_id)

def update_status():
    global last_public_ip, last_public_ip_change_time, previous_public_ip, last_update_time
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        while True:
            start_time = time.time()
            current_public_ip = get_public_ip()
            last_update_time = time.time()
            if current_public_ip != "No disponible":
                if last_public_ip is None:
                    last_public_ip = current_public_ip
                    last_public_ip_change_time = time.time()
                    previous_public_ip = current_public_ip
                elif current_public_ip != last_public_ip:
                    previous_public_ip = last_public_ip
                    last_public_ip_change_time = time.time()
                    last_public_ip = current_public_ip

            future_isp      = executor.submit(get_isp_info, current_public_ip)
            future_duckdns  = executor.submit(update_duckdns, current_public_ip)
            future_ports    = executor.submit(scan_specific_ports, current_public_ip)
            future_ohm      = executor.submit(get_ohm_data)
            future_cpu      = executor.submit(get_plex_cpu_usage)
            future_ram      = executor.submit(get_plex_ram_values)
            future_net      = executor.submit(get_plex_net_speed)
            future_tautulli = executor.submit(get_tautulli_sessions_info)
            future_netatmo  = executor.submit(get_netatmo_info)
            future_active   = executor.submit(get_active_lights_rooms)
            future_nuki     = executor.submit(obtener_estado_nuki, ENTRADA_PISO_ID, 4)

            try:
                isp_name      = future_isp.result(timeout=5)
                duckdns_status= future_duckdns.result(timeout=5)
                ports         = future_ports.result(timeout=5)
                ohm_data      = future_ohm.result(timeout=5)
                cpu_usage     = future_cpu.result(timeout=5)
                ram_vals      = future_ram.result(timeout=5)
                net_speed     = future_net.result(timeout=5)
                sessions_info = future_tautulli.result(timeout=5)
                netatmo_info  = future_netatmo.result(timeout=5)
                active_rooms  = future_active.result(timeout=5)
                nuki_state    = future_nuki.result(timeout=7)
            except Exception as e:
                logging.exception("Error en alguna de las consultas concurrentes")
                isp_name = duckdns_status = "N/A"
                ports = {}
                ohm_data = None
                cpu_usage = "N/A"
                ram_vals = (None, None, None)
                net_speed = ("N/A", "N/A", 0, 0)
                sessions_info = []
                netatmo_info = {}
                active_rooms = []
                nuki_state = "N/A"

            service_lines = []
            if ports.get("Plex") and ports["Plex"]:
                service_lines.append(f"Plex: {ports['Plex'][0]}")
            if ports.get("WireGuard") and ports["WireGuard"]:
                wg_ports = ", ".join(str(port) for port in ports["WireGuard"])
                service_lines.append(f"WireGuard: {wg_ports}")
            ports_text = "; ".join(service_lines) if service_lines else "Ninguno"

            msg_text = "🌐 **Monitoreo de Servicios** 🌐\n\n"
            msg_text += f"📡 **IP Pública:** {current_public_ip}\n"
            msg_text += f"🏢 **ISP:** {isp_name}\n"
            msg_text += f"🦆 **DuckDNS:** {duckdns_status}\n"
            msg_text += f"\n🔹 **DuckDNS Domain:** {DUCKDNS_DOMAIN}\n\n"

            msg_text += "💻 **miniPC Server:**\n"
            if ohm_data:
                cpu_load = find_sensor_value(ohm_data, "/intelcpu/0/load/0") or "N/A"
                cpu_temp = find_sensor_value(ohm_data, "/intelcpu/0/temperature/6") or "N/A"
                mem_used = find_sensor_value(ohm_data, "/ram/data/0") or "N/A"
                download_speed_ohm = find_sensor_value(ohm_data, "/nic/%7B96BABA16-4C42-4B2B-908A-08449B80E1D8%7D/throughput/8") or "N/A"
                upload_speed_ohm = find_sensor_value(ohm_data, "/nic/%7B96BABA16-4C42-4B2B-908A-08449B80E1D8%7D/throughput/7") or "N/A"
                progress_bar = build_progress_bar(cpu_load) if cpu_load != "N/A" else "N/A"
                msg_text += f"• CPU Load: {progress_bar}\n"
                msg_text += f"• CPU Temp: {cpu_temp}\n"
                msg_text += f"• Memory Used: {mem_used}\n"
                msg_text += f"• Download Speed: {download_speed_ohm}\n"
                msg_text += f"• Upload Speed: {upload_speed_ohm}\n"
            else:
                msg_text += "⚠️ No se pudo obtener datos de Open Hardware Monitor.\n"

            msg_text += "\n📁 **QnaP Server:**\n"
            if cpu_usage != "N/A":
                cpu_percentage = cpu_usage.strip() if "%" in cpu_usage else f"{cpu_usage}%"
                progress_bar_plex = build_progress_bar(cpu_usage, show_percentage=False)
            else:
                cpu_percentage = "N/A"
                progress_bar_plex = "N/A"
            msg_text += f"• CPU: {cpu_percentage}\n"
            msg_text += f"{progress_bar_plex}\n"

            if ram_vals[0] is not None:
                ram_info = f"{ram_vals[0]:.2f} MB ({ram_vals[2]:.0f}%)"
                ram_bar = build_ram_bar(ram_vals[0], ram_vals[1])
            else:
                ram_info = "N/A"
                ram_bar = "N/A"
            msg_text += f"• RAM: {ram_info}\n"
            msg_text += f"{ram_bar}\n"

            download_hr, upload_hr, raw_download, raw_upload = net_speed
            msg_text += f"• Download: {download_hr}\n"
            msg_text += f"{build_speed_bar(raw_download)}\n"
            msg_text += f"• Upload: {upload_hr}\n"
            msg_text += f"{build_speed_bar(raw_upload)}\n"

            if sessions_info:
                msg_text += "• **🎞 Sesiones activas:**\n"
                for sess in sessions_info:
                    msg_text += f"   - {sess}\n"
            else:
                msg_text += "• **Sesiones activas:** 0\n"

            msg_text += "\n📥 **Descargas en Qbit:**\n"
            qb_downloads = get_qb_downloads()
            if not qb_downloads:
                msg_text += "⚠️ No hay descargas activas.\n"
            else:
                for d in qb_downloads:
                    msg_text += f"{d}\n"

            msg_text += "\n🌍 **IPs Públicas Monitorizadas:**\n"
            if ips_publicas:
                for alias, ip in list(ips_publicas.items()):
                    icon, latency = get_status_info(ip)
                    msg_text += f"• {icon} {alias} -> {ip} {latency}\n" if latency else f"• {icon} {alias} -> {ip}\n"
            else:
                msg_text += "⚠️ Sin IPs públicas añadidas.\n"

            msg_text += "\n🏠 **IPs Privadas Monitorizadas:**\n"
            if ips_privadas:
                for alias, ip in list(ips_privadas.items()):
                    icon, latency = get_status_info(ip)
                    msg_text += f"• {icon} {alias} -> {ip} {latency}\n" if latency else f"• {icon} {alias} -> {ip}\n"
            else:
                msg_text += "⚠️ Sin IPs privadas añadidas.\n"

            msg_text += "\n🌤 **Openweather:**\n"
            openweather_data = get_openweather_data()  # Función que retorna cached_openweather_data
            if openweather_data:
                if current_location_name != DEFAULT_LOCATION_NAME:
                    msg_text += f"📍 Ubicación temporal: {current_location_name}\n"
                time_obtencion = time.strftime('%H:%M:%S', time.localtime(openweather_last_update))
                msg_text += f"⏰ Hora de obtención: {time_obtencion}\n"
                # Resto del formato (estado, temperatura, viento, etc.)
                current = openweather_data.get("current", {})
                weather = current.get("weather", [{}])[0]
                description = weather.get("description", "").capitalize()
                weather_main = weather.get("main", "")
                icon_estado = get_weather_icon(weather_main)
                # Verificar si hay alertas activas
                alerts = openweather_data.get("alerts")
                if alerts:
                    msg_text += "\n🚨 **Alertas Activas:**\n"
                    for alert in alerts:
                        sender = alert.get("sender_name", "Desconocido")
                        event = alert.get("event", "Alerta")
                        alert_start = time.strftime('%H:%M:%S', time.localtime(alert.get("start", time.time())))
                        alert_end = time.strftime('%H:%M:%S', time.localtime(alert.get("end", time.time())))
                        description = alert.get("description", "Sin descripción")
                        msg_text += f"• {event} por {sender} (desde {alert_start} hasta {alert_end})\n"

                        # Opcional: puedes agregar parte de la descripción si es muy larga.
                msg_text += f"🔸Estado: {description} {icon_estado}\n"

                # Agregar la fase lunar justo debajo del estado:
                daily = openweather_data.get("daily", [])
                if daily and len(daily) > 0:
                    moon_phase = daily[0].get("moon_phase")
                    if moon_phase is not None:
                        moon_icon = get_moon_phase_icon(moon_phase)
                        msg_text += f"🔸Fase Lunar: {moon_icon}\n"
                
                # Probabilidad de precipitación (del primer dato horario)
                hourly = openweather_data.get("hourly", [])
                pop = int(hourly[0].get("pop", 0) * 100) if hourly else 0
                pop_icon = "🌧" if pop > 0 else "☀️"
                msg_text += f"🔹Probabilidad de precipitación: {pop}% {pop_icon}\n\n"
                
                # Temperatura y barra
                temp = current.get("temp", 0)
                feels_like = current.get("feels_like", 0)
                barra_temp = construir_barra_temp(float(temp))
                msg_text += f"🏙 Temperatura: {temp:.2f}°C (sensación: {feels_like:.0f}°C)\n{barra_temp}\n"
                
                # Viento y barra
                wind_speed = current.get("wind_speed", 0) * 3.6  # m/s a km/h
                wind_deg = current.get("wind_deg", 0)
                wind_direction = get_wind_direction(wind_deg)
                barra_viento = construir_barra_viento(wind_speed)
                msg_text += f"💨 Viento: {wind_speed:.0f} km/h {wind_direction}\n{barra_viento}\n"
                
                # Índice UV y barra
                uv = current.get("uvi", 0)
                barra_uv = construir_barra_uv(uv)
                msg_text += f"🔆 Índice UV: {uv:.2f}\n{barra_uv}\n"
                
                # Dentro de la sección de Openweather, después de la parte de pronóstico diario:

                # Pronóstico por hora para las próximas 9 horas (formato similar al diario)
                hourly = openweather_data.get("hourly", [])
                if hourly and len(hourly) >= 10:
                    msg_text += "\n🔸Pronóstico por hora:\n"
                    # Se omite la entrada actual y se muestran las 9 siguientes
                    for hour_data in hourly[2:7]:
                        dt = hour_data.get("dt")
                        hour_str = time.strftime('%H', time.localtime(dt))
                        weather_hour = hour_data.get("weather", [{}])[0]
                        icon_hour = get_weather_icon(weather_hour.get("main", ""))
                        temp_hour = hour_data.get("temp", 0)
                        pop_hour = int(hour_data.get("pop", 0) * 100)
                        wind_speed_hour = hour_data.get("wind_speed", 0) * 3.6
                        msg_text += f"🕑 {hour_str} {icon_hour} | 🌡️ {temp_hour:.1f}°C | 💧 {pop_hour}% | 🌬️ {wind_speed_hour:.0f} km/h \n"


                # Pronóstico de los próximos 3 días
                daily = openweather_data.get("daily", [])
                if daily and len(daily) >= 4:
                    msg_text += "🔸Pronostico:\n"
                    for day_data in daily[1:4]:
                        dt = day_data.get("dt")
                        day_str = time.strftime('%d', time.localtime(dt))
                        weather_day = day_data.get("weather", [{}])[0]
                        icon_day = get_weather_icon(weather_day.get("main", ""))
                        temp_day = day_data.get("temp", {}).get("day", 0)
                        pop_day = int(day_data.get("pop", 0) * 100)
                        wind_speed_day = day_data.get("wind_speed", 0) * 3.6
                        msg_text += f"📅 {day_str} {icon_day} | 🌡️ {temp_day:.1f}°C | 💧 {pop_day}% | 🌬️ {wind_speed_day:.0f} km/h \n"

            else:
                msg_text += "   ⚠️ No se pudo obtener datos del clima.\n"

            netatmo_info = get_netatmo_info()
            msg_text += "\n🌦 **Netatmo:**\n"
            if cached_netatmo_data:
                time_obtencion_netatmo = time.strftime('%H:%M:%S', time.localtime(netatmo_last_update))
                msg_text += f"⏰ Hora de obtención: {time_obtencion_netatmo}\n"

            habitaciones_netatmo = {
                "Comedor": {
                    "temp": netatmo_info.get("Comedor", {}).get("Temperature", "N/A"),
                    "co2": netatmo_info.get("Comedor", {}).get("CO2", None),
                    "exterior": False
                },
                "Dormitorio": {
                    "temp": netatmo_info.get("Dormitorio", {}).get("Temperature", "N/A"),
                    "co2": netatmo_info.get("Dormitorio", {}).get("CO2", None),
                    "exterior": False
                },
                "Terraza": {
                    "temp": netatmo_info.get("Terraza", {}).get("Temperature", "N/A"),
                    "co2": None,
                    "exterior": True
                }
            }

            for habitacion, datos in habitaciones_netatmo.items():
                temp = datos["temp"]
                if temp != "N/A":
                    temp_bar = construir_barra_temp(float(temp), datos["exterior"])
                    if datos["co2"] is not None:
                        color_co2 = obtener_color_co2(datos["co2"])
                        msg_text += f"🏡 **{habitacion}** {temp}°C\n{temp_bar} CO₂: {color_co2} {datos['co2']} ppm\n"
                    else:
                        msg_text += f"🏡 **{habitacion}** {temp}°C\n{temp_bar}\n"

            # Sección de lluvia
            lluvia_info = netatmo_info.get("Lluvia", {})
            if isinstance(lluvia_info, dict):
                lluvia_1h = float(lluvia_info.get("1h", 0))
                lluvia_24h = float(lluvia_info.get("24h", 0))
                msg_text += "\n🌧 **Lluvia:**\n"
                if lluvia_1h > 0:
                    barra_lluvia_1h = construir_barra_lluvia(lluvia_1h)
                    msg_text += f"💧 **Última hora**:\n{barra_lluvia_1h} ({lluvia_1h:.1f} mm)\n"
                if lluvia_24h > 0:
                    barra_lluvia_24h = construir_barra_lluvia_24h(lluvia_24h)
                    msg_text += f"🌊 **Últimas 24h**:\n{barra_lluvia_24h} ({lluvia_24h:.1f} mm)\n"
                if lluvia_1h == 0 and lluvia_24h == 0:
                    msg_text += "   - Sin lluvia\n"
            else:
                msg_text += f"• **Lluvia**: {lluvia_info}\n"
            
            # Sección Iluminación
            global lights_on_times
            msg_text += "\n💡 **Iluminación:**\n"
            active_rooms = get_active_lights_rooms()
            # Registrar la hora de encendido si es la primera detección
            for room in active_rooms:
                if room not in lights_on_times:
                    lights_on_times[room] = time.time()
            # Eliminar aquellas que ya se apagaron
            for room in list(lights_on_times.keys()):
                if room not in active_rooms:
                    del lights_on_times[room]
            if active_rooms:
                for room in active_rooms:
                    activation_time = lights_on_times.get(room)
                    formatted_time = time.strftime('%H:%M:%S', time.localtime(activation_time)) if activation_time else "N/A"
                    msg_text += f"• 🟡 {room} (**{formatted_time}**)\n"
            else:
                msg_text += "✅ No hay luces encendidas.\n"

            global entrada_piso_last_state, entrada_piso_last_change_time
            estado_entrada_piso = obtener_estado_nuki(ENTRADA_PISO_ID, device_type=4)
            # Actualizamos solo si el nuevo estado es "Bloqueado" o "Desbloqueado"
            if estado_entrada_piso in ["Bloqueado", "Desbloqueado"]:
                if entrada_piso_last_state is None or estado_entrada_piso != entrada_piso_last_state:
                    entrada_piso_last_state = estado_entrada_piso
                    entrada_piso_last_change_time = time.time()
            formatted_change_time = time.strftime('%H:%M:%S', time.localtime(entrada_piso_last_change_time)) if entrada_piso_last_change_time else "N/A"

            # Obtener la información completa de la cerradura para extraer el nivel de batería
            nuki_info = obtener_info_nuki(ENTRADA_PISO_ID)
            battery = None
            if nuki_info:
                battery = nuki_info.get("lastKnownState", {}).get("batteryChargeState")
            if battery is not None:
                try:
                    battery = int(battery)
                except Exception:
                    battery = None

            # Seleccionar el icono según el valor obtenido: 🔋 si >= 50%, 🪫 si es menor
            if battery is not None:
                battery_icon = "🔋" if battery >= 50 else "🪫"
            else:
                battery_icon = "❓"

            # Dentro de la sección "Accesos"
            msg_text += "\n🚪 **Accesos:**\n"
            msg_text += f"• **EntradaPiso**: {estado_entrada_piso} (**{formatted_change_time}**)\n"
            if battery_value is not None:
                # Seleccionamos el icono según el porcentaje: 🔋 si es >= 50, 🪫 si es menor
                battery_icon = "🔋" if battery_value >= 50 else "🪫"
                msg_text += f"• **Batería:** {battery_icon} ({battery_value}%)\n"
            else:
                msg_text += f"• **Batería:** N/A\n"

            msg_text += f"\n🔓 **Puertos abiertos en IP Pública:**\n• {ports_text}\n"
            if last_update_time:
                formatted_update_time = time.strftime('%H:%M:%S', time.localtime(last_update_time))
            else:
                formatted_update_time = "N/A"
            if last_public_ip_change_time:
                delta = time.time() - last_public_ip_change_time
                hours = int(delta // 3600)
                minutes = int((delta % 3600) // 60)
                time_since_change = f"{hours} hrs {minutes} min" if hours > 0 else f"{minutes} min"
            else:
                time_since_change = "N/A"
            msg_text += f"\n🕒 **Última actualización:** {formatted_update_time}"
            msg_text += f"\n🔄 **Cambio de IP hace:** {time_since_change}"
            msg_text += f"\n📤 **IP anterior:** {previous_public_ip}"

            for chat_id, message_id in list(status_messages.items()):
                try:
                    app.edit_message_text(chat_id, message_id, msg_text, reply_markup=get_main_keyboard())
                except Exception as e:
                    logging.error(f"Error actualizando el chat {chat_id}: {e}")

            elapsed = time.time() - start_time
            sleep_time = max(0, UPDATE_INTERVAL - elapsed)
            time.sleep(sleep_time)

threading.Thread(target=update_netatmo_cache, daemon=True).start()
threading.Thread(target=update_openweather_cache, daemon=True).start()
threading.Thread(target=update_status, daemon=True).start()
threading.Thread(target=update_battery_status, daemon=True).start()

def send_initial_notifications():
    time.sleep(2)
    for chat_id in ALLOWED_CHAT_IDS:
        try:
            msg = app.send_message(chat_id, "🚀 Iniciando monitoreo de IPs...")
            status_messages[chat_id] = msg.id
            tracked_message_ids[chat_id] = set()
        except Exception as e:
            logging.error(f"Error al enviar notificación a {chat_id}: {e}")

 #linea para lanzar notificacion automaticamente a chatids
 #threading.Thread(target=send_initial_notifications, daemon=True).start()

app.run()
