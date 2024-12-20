import json
import requests
import sys
from socket import socket, AF_UNIX, SOCK_DGRAM
import os
import http.client

http.client.HTTPConnection.debuglevel = 1

# Dirección de la API de MISP y clave de API MISP
MISP_API_URL = "https://34.236.118.1/attributes/restSearch"
MISP_API_KEY = "hM6zjQRJKC74Lxq6cmWUStuPKdzwMES2h4NfiPFn"

# Dirección del socket de Wazuh para enviar eventos
SOCKET_ADDR = "/var/ossec/queue/sockets/queue"

# Enviar el fileHash a MISP
def send_filehash_to_misp(filehash):
    """Envía el fileHash a la API de MISP y devuelve la respuesta."""
    headers = {
        "Authorization": MISP_API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    data = {
        "returnFormat": "json",
        #"type": "md5",  # Ajusta esto si estás usando un tipo de hash diferente, como sha256
        "value": filehash
    }

    # Imprimir JSON enviado
    print("JSON enviado a MISP:")
    print(json.dumps(data, indent=2))

    # Imprimir encabezados de la solicitud
    print("Encabezados enviados a MISP:")
    print(json.dumps(headers, indent=2))

    try:
        response = requests.post(MISP_API_URL, headers=headers, json=data, verify=False, allow_redirects=False)
        response.raise_for_status()
        import http.client
        http.client.HTTPConnection.debuglevel = 1
        return response.json()  # Retorna la respuesta de MISP
    except requests.exceptions.RequestException as e:
        print(f"Error enviando el hash a MISP: {e}", file=sys.stderr)
        print(f"Detalles del error: {response.text}")

        return None

# Función para enviar la alerta al sistema de Wazuh (para que aparezca en el Dashboard)
def send_event_to_wazuh(alert):
    """Envía la alerta enriquecida al sistema Wazuh para que se vea en el Dashboard."""
    try:
        if alert.get("agent", {}).get("id") == "000" or not alert.get("agent"):
            string = f'1:misp:{json.dumps(alert)}'
        else:
            agent = alert.get("agent", {})
            string = f'1:[{agent["id"]}] ({agent["name"]}) {agent.get("ip", "any")}->misp:{json.dumps(alert)}'
        
        sock = socket(AF_UNIX, SOCK_DGRAM)
        sock.connect(SOCKET_ADDR)
        sock.send(string.encode())
        sock.close()
        print("Alerta enriquecida enviada a Wazuh correctamente.")
    except Exception as e:
        print(f"Error al enviar la alerta a Wazuh: {e}", file=sys.stderr)

# Integrar la respuesta de MISP en la alerta y enviarla
def process_alert(alert):
    """Procesa la alerta, enriqueciendo con datos de MISP si es necesario."""
    # Filtrar alertas por nivel (>=3)
    if alert.get("rule", {}).get("level", 0) < 3:
        print("Nivel de alerta menor a 3. No se procesará.")
        return None

    # Filtrar alertas por el grupo de reglas (rule.group == "sentinelone")
    rule_groups = alert.get("rule", {}).get("groups", [])
    if "sentinelone" not in rule_groups:
        print("La alerta no pertenece al grupo 'sentinelone'. No se procesará.")
        return None

    # Obtener el hash del archivo (field: `fileHash`)
    filehash = alert.get("data", {}).get("fileHash")
    if not filehash:
        print("No se encontró fileHash en la alerta. No se procesará.", file=sys.stderr)
        return None

    # Enviar el fileHash a MISP
    print(f"Enviando fileHash {filehash} a MISP...")
    misp_response = send_filehash_to_misp(filehash)

    if misp_response:
        # Si la respuesta de MISP contiene IoCs (Indicadores de Compromiso), agregarlos a la alerta
        if "response" in misp_response and "Attribute" in misp_response["response"]:
            if misp_response["response"]["Attribute"]:  # Comprobar si la lista no está vacía
                attribute = misp_response["response"]["Attribute"][0]  # Tomamos el primer IoC encontrado
                alert["misp"] = {
                    "event_id": attribute.get("event_id", ""),
                    "category": attribute.get("category", ""),
                    "value": attribute.get("value", ""),
                    "type": attribute.get("type", ""),
                    "source": alert.get("rule", {}).get("description", ""),
                }
                alert["integration"] = "misp"  # Indicamos que la alerta fue enriquecida con MISP
                # Aquí se envía la alerta enriquecida al sistema Wazuh (Dashboard)
                send_event_to_wazuh(alert)
            else:
                alert["misp"] = {"error": "No se encontraron atributos relevantes en MISP"}
                alert["integration"] = "misp_error"  # Indicamos que hubo un error al enriquecer con MISP
        else:
            alert["misp"] = {"error": "Respuesta de MISP no contiene atributos"}
            alert["integration"] = "misp_error"  # Indicamos que hubo un error al enriquecer con MISP
    else:
        print("No se pudo obtener respuesta de MISP", file=sys.stderr)


# Función principal
def main():
    # Leer alerta desde stdin (proporcionada por Wazuh)
    alert = sys.stdin.read()

    # Parsear alerta como JSON
    try:
        alert_json = json.loads(alert)
    except json.JSONDecodeError:
        print("No se pudo decodificar la alerta como JSON.", file=sys.stderr)
        sys.exit(1)

    # Procesar la alerta y enriquecerla
    process_alert(alert_json)

if __name__ == "__main__":
    main()
