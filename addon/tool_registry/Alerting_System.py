import httpx
import json
import asyncio

class AlertingSystem:
    def __init__(self, service_name, service_type, notification_url):
        self.service_name = service_name
        self.service_type = service_type
        self.notification_url = notification_url
        self.previous_status = None

    async def get_service_status(self):
        # For simplicity, assume we have a function to get the service status
        # In a real-world scenario, you would use the pm2 API or another method to get the status
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://example.com/{self.service_type}/{self.service_name}/status")
            if response.status_code == 200:
                return response.json()["meta"]["status"]
            else:
                return None

    async def send_notification(self, status):
        # Send a notification using the provided URL
        async with httpx.AsyncClient() as client:
            data = {
                "service_name": self.service_name,
                "service_type": self.service_type,
                "status": status
            }
            response = await client.post(self.notification_url, json=data)
            if response.status_code != 200:
                print(f"Failed to send notification: {response.text}")

    async def run(self):
        while True:
            status = await self.get_service_status()
            if status != self.previous_status:
                await self.send_notification(status)
                self.previous_status = status
            await asyncio.sleep(60)  # Check every minute

async def main():
    data = {
        "tool_name": "Alerting System",
        "description": "Send notifications on service status changes",
        "service": {
            "type": "pm2",
            "name": "reze-discord",
            "meta": {
                "status": "online"
            }
        }
    }
    notification_url = "https://example.com/notifications"
    alerting_system = AlertingSystem(data["service"]["name"], data["service"]["type"], notification_url)
    await alerting_system.run()

if __name__ == "__main__":
    asyncio.run(main())