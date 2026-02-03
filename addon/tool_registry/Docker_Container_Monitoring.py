import httpx
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_container_info(container_id):
    """Get container info from Docker API"""
    url = f"http://localhost:2375/containers/{container_id}/json"
    response = httpx.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"Failed to get container info: {response.text}")
        return None

def get_container_logs(container_id):
    """Get container logs from Docker API"""
    url = f"http://localhost:2375/containers/{container_id}/logs"
    response = httpx.get(url)
    if response.status_code == 200:
        return response.text
    else:
        logger.error(f"Failed to get container logs: {response.text}")
        return None

def monitor_container(container_id):
    """Monitor container performance and logs"""
    info = get_container_info(container_id)
    if info:
        logger.info(f"Container {container_id} info: {info}")
    logs = get_container_logs(container_id)
    if logs:
        logger.info(f"Container {container_id} logs: {logs}")

def main():
    # Load service data from JSON
    service_data = {
        "tool_name": "Docker Container Monitoring",
        "description": "Tool to monitor and manage Docker container performance and logs",
        "service": {
            "id": 3,
            "service_type": "docker",
            "service_name": "listmonk",
            "service_meta": "{\"image\": \"listmonk/listmonk:latest\", \"ports\": \"0.0.0.0:9000->9000/tcp, [::]:9000->9000/tcp\"}",
            "discovered_at": "2026-02-03 10:30:29",
            "status": "new"
        }
    }

    # Extract container ID from service data
    container_id = service_data["service"]["id"]

    # Monitor container
    monitor_container(container_id)

if __name__ == "__main__":
    main()