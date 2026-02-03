import httpx
import json
import sys

def send_notification(tool_name, description, service_name, error_message):
    """
    Send a notification using HTTP request.
    
    Args:
    tool_name (str): The name of the tool.
    description (str): The description of the tool.
    service_name (str): The name of the service.
    error_message (str): The error message to be sent.
    """
    notification_data = {
        "tool_name": tool_name,
        "description": description,
        "service_name": service_name,
        "error_message": error_message
    }
    try:
        response = httpx.post("https://example.com/notifications", json=notification_data)
        response.raise_for_status()
    except httpx.RequestError as e:
        print(f"Error sending notification: {e}")

def parse_cron_job(cron_job):
    """
    Parse the cron job and extract relevant information.
    
    Args:
    cron_job (str): The cron job string.
    
    Returns:
    dict: A dictionary containing the parsed cron job information.
    """
    parts = cron_job.split()
    schedule = parts[0]
    command = " ".join(parts[1:])
    return {
        "schedule": schedule,
        "command": command
    }

def main():
    if len(sys.argv) != 2:
        print("Usage: python alerting_tool.py <cron_job_string>")
        sys.exit(1)
    
    cron_job_string = sys.argv[1]
    cron_job_info = parse_cron_job(cron_job_string)
    
    tool_name = "Alerting Tool"
    description = "To receive notifications on cron job failures or errors"
    service_name = "cron_5434"
    error_message = "Cron job failed"
    
    send_notification(tool_name, description, service_name, error_message)

if __name__ == "__main__":
    main()