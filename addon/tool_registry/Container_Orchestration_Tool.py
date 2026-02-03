import json
import httpx
import argparse

class ContainerOrchestrationTool:
    def __init__(self, service):
        self.service = service

    def start_container(self):
        # Start the container using the provided service meta
        service_meta = json.loads(self.service['service_meta'])
        image = service_meta['image']
        ports = service_meta['ports']

        # Use httpx to send a request to the Docker API to start the container
        url = f'http://localhost:2375/containers/create'
        data = {
            'Image': image,
            'PortBindings': {
                '8000/tcp': [{'HostPort': '8201'}]
            }
        }
        response = httpx.post(url, json=data)

        if response.status_code == 201:
            print(f'Container {image} started successfully')
        else:
            print(f'Failed to start container {image}')

    def stop_container(self):
        # Stop the container using the provided service meta
        service_meta = json.loads(self.service['service_meta'])
        image = service_meta['image']

        # Use httpx to send a request to the Docker API to stop the container
        url = f'http://localhost:2375/containers/{image}/stop'
        response = httpx.post(url)

        if response.status_code == 204:
            print(f'Container {image} stopped successfully')
        else:
            print(f'Failed to stop container {image}')

def __main__():
    parser = argparse.ArgumentParser(description='Container Orchestration Tool')
    parser.add_argument('--service', type=str, help='Path to the service JSON file')
    parser.add_argument('--action', type=str, help='Action to perform (start/stop)')
    args = parser.parse_args()

    if args.service:
        with open(args.service, 'r') as f:
            service = json.load(f)
    else:
        service = {
            "id": 1,
            "service_type": "docker",
            "service_name": "paintingan-api",
            "service_meta": "{\"image\": \"paintingan-api\", \"ports\": \"0.0.0.0:8201->8000/tcp, [::]:8201->8000/tcp\"}",
            "discovered_at": "2026-02-03 10:30:29",
            "status": "new"
        }

    tool = ContainerOrchestrationTool(service)

    if args.action == 'start':
        tool.start_container()
    elif args.action == 'stop':
        tool.stop_container()
    else:
        print('Invalid action')

if __name__ == '__main__':
    __main__()