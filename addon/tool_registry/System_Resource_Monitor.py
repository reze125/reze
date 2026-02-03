import httpx
import psutil
import time
import json

def get_system_resources():
    """Returns a dictionary containing system resource usage."""
    resources = {
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent
    }
    return resources

def send_resources_to_server(resources):
    """Sends system resource usage to a server."""
    url = "http://example.com/resources"
    try:
        response = httpx.post(url, json=resources)
        response.raise_for_status()
    except httpx.RequestError as e:
        print(f"Error sending resources: {e}")

def main():
    """Monitors system resources and sends them to a server."""
    while True:
        resources = get_system_resources()
        send_resources_to_server(resources)
        time.sleep(60)  # wait 1 minute before checking again

if __name__ == "__main__":
    main()