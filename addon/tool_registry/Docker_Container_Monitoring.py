import httpx
import json
import logging

logging.basicConfig(level=logging.INFO)

def get_service_info(service_id: int) -> dict:
    """Retrieve service information from the API."""
    url = f"https://example.com/services/{service_id}"
    response = httpx.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        logging.error(f"Failed to retrieve service info: {response.text}")
        return {}

def monitor_container(service_info: dict) -> None:
    """Monitor Docker container performance and logs."""
    service_meta = json.loads(service_info.get("service_meta", "{}"))
    image = service_meta.get("image")
    ports = service_meta.get("ports")
    logging.info(f"Monitoring container {image} with ports {ports}")

def main() -> None:
    """Main entry point for the Docker Container Monitoring tool."""
    service_id = 7
    service_info = get_service_info(service_id)
    if service_info:
        monitor_container(service_info)

if __name__ == "__main__":
    main()