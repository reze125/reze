import json
import httpx
import time

class MonitoringTool:
    def __init__(self, service):
        self.service = service

    def monitor_service(self):
        try:
            # Assuming the service is a Docker container
            # and we're checking its uptime
            response = httpx.get(f"http://{self.service['service_name']}:5433")
            if response.status_code == 200:
                print(f"{self.service['service_name']} is up and running.")
                return True
            else:
                print(f"{self.service['service_name']} is down.")
                return False
        except httpx.ConnectError:
            print(f"Failed to connect to {self.service['service_name']}.")
            return False

    def check_performance(self):
        # For simplicity, let's assume we're checking the response time
        start_time = time.time()
        try:
            response = httpx.get(f"http://{self.service['service_name']}:5433")
            end_time = time.time()
            response_time = end_time - start_time
            print(f"Response time for {self.service['service_name']}: {response_time} seconds")
        except httpx.ConnectError:
            print(f"Failed to connect to {self.service['service_name']}.")

def main():
    data = {
        "tool_name": "Monitoring Tool",
        "description": "Tool to monitor service performance and uptime",
        "service": {
            "id": 5,
            "service_type": "docker",
            "service_name": "quotepilot-db",
            "service_meta": "{\"image\": \"postgres:15\", \"ports\": \"0.0.0.0:5433->5432/tcp, [::]:5433->5432/tcp\"}",
            "discovered_at": "2026-02-03 10:30:29",
            "status": "new"
        }
    }
    service = data["service"]
    monitoring_tool = MonitoringTool(service)
    monitoring_tool.monitor_service()
    monitoring_tool.check_performance()

if __name__ == "__main__":
    main()