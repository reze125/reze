import httpx
import json
import sys

def get_cron_jobs():
    """Fetches cron jobs from a remote API."""
    try:
        response = httpx.get('https://example.com/cron-jobs')
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as e:
        print(f"Error fetching cron jobs: {e}")
        return []

def create_cron_job(job):
    """Creates a new cron job."""
    try:
        response = httpx.post('https://example.com/cron-jobs', json=job)
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as e:
        print(f"Error creating cron job: {e}")
        return None

def update_cron_job(job_id, job):
    """Updates an existing cron job."""
    try:
        response = httpx.put(f'https://example.com/cron-jobs/{job_id}', json=job)
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as e:
        print(f"Error updating cron job: {e}")
        return None

def delete_cron_job(job_id):
    """Deletes a cron job."""
    try:
        response = httpx.delete(f'https://example.com/cron-jobs/{job_id}')
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as e:
        print(f"Error deleting cron job: {e}")
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python cron_job_manager.py <command> [options]")
        print("Available commands: list, create, update, delete")
        return

    command = sys.argv[1]

    if command == 'list':
        jobs = get_cron_jobs()
        for job in jobs:
            print(json.dumps(job, indent=4))
    elif command == 'create':
        if len(sys.argv) < 3:
            print("Usage: python cron_job_manager.py create <job_json>")
            return
        job_json = sys.argv[2]
        job = json.loads(job_json)
        created_job = create_cron_job(job)
        if created_job:
            print(json.dumps(created_job, indent=4))
    elif command == 'update':
        if len(sys.argv) < 4:
            print("Usage: python cron_job_manager.py update <job_id> <job_json>")
            return
        job_id = sys.argv[2]
        job_json = sys.argv[3]
        job = json.loads(job_json)
        updated_job = update_cron_job(job_id, job)
        if updated_job:
            print(json.dumps(updated_job, indent=4))
    elif command == 'delete':
        if len(sys.argv) < 3:
            print("Usage: python cron_job_manager.py delete <job_id>")
            return
        job_id = sys.argv[2]
        deleted_job = delete_cron_job(job_id)
        if deleted_job:
            print(json.dumps(deleted_job, indent=4))
    else:
        print("Unknown command")

if __name__ == '__main__':
    main()