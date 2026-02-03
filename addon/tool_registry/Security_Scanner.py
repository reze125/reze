import httpx
import json
import sys

def scan_postgres_vulnerabilities(service_meta):
    """
    Scan Postgres image for vulnerabilities.
    
    Args:
    service_meta (str): JSON string containing Postgres image metadata.
    
    Returns:
    list: List of vulnerabilities found in the Postgres image.
    """
    # Parse service metadata JSON
    meta = json.loads(service_meta)
    image = meta.get('image')
    
    # Check if image is Postgres
    if 'postgres' not in image:
        return []
    
    # Extract Postgres version
    version = image.split(':')[-1]
    
    # Use httpx to fetch vulnerability data from a public API (e.g., VulnDB)
    url = f'https://vulndb.cyberriskanalytics.com/api/v3/vulnerabilities?search=postgres&version={version}'
    response = httpx.get(url)
    
    # Parse response JSON
    vulnerabilities = response.json().get('data', [])
    
    return vulnerabilities

def main():
    # Example usage
    service_meta = "{\"image\": \"postgres:15\", \"ports\": \"0.0.0.0:5433->5432/tcp, [::]:5433->5432/tcp\"}"
    vulnerabilities = scan_postgres_vulnerabilities(service_meta)
    
    # Print vulnerabilities
    if vulnerabilities:
        print('Vulnerabilities found:')
        for vuln in vulnerabilities:
            print(vuln.get('title'))
    else:
        print('No vulnerabilities found.')

if __name__ == '__main__':
    main()