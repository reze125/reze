import httpx
import json
import time

class AlertingTool:
    def __init__(self, tool_name, description, service):
        self.tool_name = tool_name
        self.description = description
        self.service = service

    def check_service_status(self):
        if self.service['type'] == 'pm2':
            # For simplicity, assume we have a function to get the status of a pm2 service
            # In a real-world scenario, you would use the pm2 API or a library like python-pm2
            # to get the status of the service
            status = self.get_pm2_service_status(self.service['name'])
            if status != 'online':
                self.send_alert(f"{self.service['name']} is {status}")
            else:
                print(f"{self.service['name']} is online")

    def get_pm2_service_status(self, name):
        # Simulate getting the status of a pm2 service
        # In a real-world scenario, you would use the pm2 API or a library like python-pm2
        # to get the status of the service
        # For this example, assume the service is online
        return 'online'

    def send_alert(self, message):
        # For simplicity, assume we have a function to send an alert
        # In a real-world scenario, you would use a library like httpx to send a request
        # to a service that can send alerts, such as a webhook or an email service
        print(f"Sending alert: {message}")
        try:
            response = httpx.post('https://example.com/alert', json={'message': message})
            if response.status_code != 200:
                print(f"Failed to send alert: {response.text}")
        except httpx.RequestError as e:
            print(f"Failed to send alert: {e}")

def main():
    data = {
        "tool_name": "Alerting Tool",
        "description": "To notify when the service goes offline or encounters issues",
        "service": {
            "type": "pm2",
            "name": "reze-addon",
            "meta": {
                "status": "online"
            }
        }
    }
    tool = AlertingTool(data['tool_name'], data['description'], data['service'])
    while True:
        tool.check_service_status()
        time.sleep(60)  # Check the service status every 60 seconds

if __name__ == "__main__":
    main()