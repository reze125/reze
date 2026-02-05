import httpx
import json

def send_notification(service_name, status):
    """Send a notification when the service experiences errors or downtime."""
    notification_url = "https://your-notification-service.com/alert"
    payload = {
        "service_name": service_name,
        "status": status
    }
    try:
        response = httpx.post(notification_url, json=payload)
        response.raise_for_status()
        print(f"Notification sent successfully for {service_name} with status {status}")
    except httpx.RequestError as e:
        print(f"Error sending notification: {e}")

def check_service_status(service_name):
    """Check the status of the service."""
    service_url = f"https://your-service-status.com/{service_name}"
    try:
        response = httpx.get(service_url)
        response.raise_for_status()
        service_status = response.json()["meta"]["status"]
        return service_status
    except httpx.RequestError as e:
        print(f"Error checking service status: {e}")
        return None

def main():
    """Main function to receive notifications when the service experiences errors or downtime."""
    service_name = "ai-tools-lab"
    service_status = check_service_status(service_name)
    if service_status == "errored":
        send_notification(service_name, service_status)

if __name__ == "__main__":
    main()