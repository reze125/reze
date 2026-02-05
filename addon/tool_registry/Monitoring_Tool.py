import httpx
import json
import time

class MonitoringTool:
    def __init__(self, service):
        self.service = service
        self.service_name = service['service_name']
        self.service_type = service['service_type']
        self.service_meta = json.loads(service['service_meta'])

    def check_service_status(self):
        try:
            response = httpx.get(f'http://{self.service_name}:5678')
            if response.status_code == 200:
                return 'up'
            else:
                return 'down'
        except httpx.ConnectError:
            return 'down'

    def monitor_service(self):
        while True:
            status = self.check_service_status()
            print(f'Service {self.service_name} is {status}')
            time.sleep(60)

def main():
    service = {
        "id": 6,
        "service_type": "docker",
        "service_name": "n8n",
        "service_meta": "{\"image\": \"n8nio/n8n:latest\", \"ports\": \"0.0.0.0:5678->5678/tcp, [::]:5678->5678/tcp\"}",
        "discovered_at": "2026-02-03 10:30:29",
        "status": "new"
    }
    tool = MonitoringTool(service)
    tool.monitor_service()

if __name__ == '__main__':
    main()