import httpx
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def collect_service_logs(service_id: int) -> dict:
    """
    Collect service logs from a given service ID.

    Args:
    - service_id (int): The ID of the service to collect logs from.

    Returns:
    - dict: A dictionary containing the collected logs.
    """
    try:
        # Assuming a REST API endpoint to collect service logs
        response = httpx.get(f"https://example.com/services/{service_id}/logs")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to collect service logs: {e}")
        return {}

def analyze_service_logs(logs: dict) -> dict:
    """
    Analyze the collected service logs.

    Args:
    - logs (dict): A dictionary containing the collected logs.

    Returns:
    - dict: A dictionary containing the analysis results.
    """
    # Basic analysis, can be extended based on the log format and content
    analysis_results = {
        "log_count": len(logs.get("logs", [])),
        "error_count": sum(1 for log in logs.get("logs", []) if log.get("level") == "ERROR")
    }
    return analysis_results

def main():
    # Example usage
    service_data = {
        "tool_name": "Logging Tool",
        "description": "Tool to collect and analyze service logs",
        "service": {
            "id": 4,
            "service_type": "docker",
            "service_name": "listmonk-db",
            "service_meta": "{\"image\": \"postgres:13\", \"ports\": \"5432/tcp\"}",
            "discovered_at": "2026-02-03 10:30:29",
            "status": "new"
        }
    }

    service_id = service_data["service"]["id"]
    logs = collect_service_logs(service_id)
    analysis_results = analyze_service_logs(logs)

    logger.info(f"Collected logs: {json.dumps(logs, indent=4)}")
    logger.info(f"Analysis results: {json.dumps(analysis_results, indent=4)}")

if __name__ == "__main__":
    main()