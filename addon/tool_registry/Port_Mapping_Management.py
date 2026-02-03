import json
import httpx

class PortMappingManagement:
    def __init__(self, service):
        self.service = service

    def get_service_meta(self):
        """Get service meta data"""
        return json.loads(self.service['service_meta'])

    def get_ports(self):
        """Get ports from service meta data"""
        meta = self.get_service_meta()
        ports = meta.get('ports', '')
        return ports.split(', ')

    def get_port_mapping(self, port):
        """Get port mapping for a given port"""
        ports = self.get_ports()
        for p in ports:
            if port in p:
                return p
        return None

    def update_port_mapping(self, port, new_port):
        """Update port mapping for a given port"""
        meta = self.get_service_meta()
        ports = meta.get('ports', '')
        ports_list = ports.split(', ')
        for i, p in enumerate(ports_list):
            if port in p:
                ports_list[i] = p.replace(port, new_port)
                break
        meta['ports'] = ', '.join(ports_list)
        self.service['service_meta'] = json.dumps(meta)
        return self.service

def main():
    data = {
        "tool_name": "Port Mapping Management",
        "description": "Tool to manage and configure port mappings for the service",
        "service": {
            "id": 3,
            "service_type": "docker",
            "service_name": "listmonk",
            "service_meta": "{\"image\": \"listmonk/listmonk:latest\", \"ports\": \"0.0.0.0:9000->9000/tcp, [::]:9000->9000/tcp\"}",
            "discovered_at": "2026-02-03 10:30:29",
            "status": "new"
        }
    }
    service = data['service']
    manager = PortMappingManagement(service)
    print("Service Meta:", manager.get_service_meta())
    print("Ports:", manager.get_ports())
    print("Port Mapping for 9000:", manager.get_port_mapping('9000'))
    updated_service = manager.update_port_mapping('9000', '9001')
    print("Updated Service:", updated_service)

    # Send updated service to server using httpx
    url = "https://example.com/update-service"
    response = httpx.post(url, json=updated_service)
    print("Response:", response.text)

if __name__ == "__main__":
    main()