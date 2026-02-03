import json
import httpx
import argparse

def get_service_info(service_id):
    """Fetch service information from the API."""
    url = f"https://example.com/api/services/{service_id}"
    response = httpx.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        return None

def update_docker_image(service_meta):
    """Update the Docker image for the service."""
    image = json.loads(service_meta)["image"]
    # Update the image using Docker API or other means
    print(f"Updating Docker image to {image}")

def main():
    parser = argparse.ArgumentParser(description="Image Update Management")
    parser.add_argument("--service-id", type=int, help="Service ID")
    args = parser.parse_args()

    if args.service_id:
        service_info = get_service_info(args.service_id)
        if service_info:
            service_meta = service_info.get("service_meta")
            if service_meta:
                update_docker_image(service_meta)
            else:
                print("Service meta not found")
        else:
            print("Service not found")
    else:
        print("Service ID is required")

if __name__ == "__main__":
    main()