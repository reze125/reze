import httpx
import json
import sys

def scan_service(service):
    """
    Scan the given service for vulnerabilities.
    
    Args:
    service (dict): A dictionary containing information about the service.
    
    Returns:
    dict: A dictionary containing the results of the scan.
    """
    try:
        # Extract the service metadata
        service_meta = json.loads(service['service_meta'])
        
        # Extract the image name
        image_name = service_meta['image']
        
        # Use the httpx library to make a request to a vulnerability database
        # Replace 'https://vuln-db.com/api/image/' with the actual API endpoint
        response = httpx.get(f'https://vuln-db.com/api/image/{image_name}')
        
        # Check if the request was successful
        if response.status_code == 200:
            # Return the results of the scan
            return response.json()
        else:
            # Return an error message if the request was not successful
            return {'error': 'Failed to retrieve vulnerability data'}
    except Exception as e:
        # Return an error message if an exception occurred
        return {'error': str(e)}

def main():
    # Example usage
    service = {
        "id": 6,
        "service_type": "docker",
        "service_name": "n8n",
        "service_meta": "{\"image\": \"n8nio/n8n:latest\", \"ports\": \"0.0.0.0:5678->5678/tcp, [::]:5678->5678/tcp\"}",
        "discovered_at": "2026-02-03 10:30:29",
        "status": "new"
    }
    
    results = scan_service(service)
    
    # Print the results
    print(json.dumps(results, indent=4))

if __name__ == "__main__":
    main()