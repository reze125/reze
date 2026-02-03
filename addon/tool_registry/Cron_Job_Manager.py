import httpx
import json
import sys

class CronJobManager:
    def __init__(self, tool_name, description, service):
        self.tool_name = tool_name
        self.description = description
        self.service = service

    def get_cron_job_info(self):
        return {
            "tool_name": self.tool_name,
            "description": self.description,
            "service": self.service
        }

    def update_cron_job(self, new_service):
        self.service = new_service

    def fetch_cron_job(self, url):
        try:
            response = httpx.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"An error occurred: {e}")
            return None

def main():
    data = {
        "tool_name": "Cron Job Manager",
        "description": "Manages and monitors cron jobs",
        "service": {
            "type": "cron",
            "name": "cron_2458",
            "meta": {
                "schedule": "SHELL=/bin/bash"
            }
        }
    }

    manager = CronJobManager(data["tool_name"], data["description"], data["service"])
    print(json.dumps(manager.get_cron_job_info(), indent=4))

    # Example usage of fetch_cron_job
    url = "https://example.com/cron_job"
    fetched_data = manager.fetch_cron_job(url)
    if fetched_data:
        print(json.dumps(fetched_data, indent=4))

if __name__ == "__main__":
    main()