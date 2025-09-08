#!/usr/bin/env python3
"""
Example of using the Table Extraction Pro API.
"""

import requests
import json
from pathlib import Path


def test_api():
    """Test the API endpoints."""
    base_url = "http://localhost:8000"
    
    # Test health endpoint
    print("Testing health endpoint...")
    response = requests.get(f"{base_url}/health")
    print(f"Health check: {response.json()}")
    
    # Test root endpoint
    print("\nTesting root endpoint...")
    response = requests.get(f"{base_url}/")
    print(f"API info: {json.dumps(response.json(), indent=2)}")


def upload_and_extract(file_path: str):
    """Upload a file and extract tables."""
    base_url = "http://localhost:8000"
    
    if not Path(file_path).exists():
        print(f"File {file_path} not found.")
        return
    
    print(f"Uploading and extracting tables from: {file_path}")
    
    with open(file_path, 'rb') as f:
        files = {'file': f}
        data = {
            'confidence': 0.5,
            'use_fallback': True,
            'include_metadata': True,
            'output_format': 'json'
        }
        
        response = requests.post(f"{base_url}/extract", files=files, data=data)
        
        if response.status_code == 200:
            result = response.json()
            print(f"Extraction successful!")
            print(f"Total tables: {result['total_tables']}")
            
            # Save result to file
            output_file = f"api_result_{Path(file_path).stem}.json"
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Result saved to: {output_file}")
            
        else:
            print(f"Extraction failed: {response.status_code}")
            print(f"Error: {response.text}")


def main():
    """Main function."""
    print("Table Extraction Pro API Example")
    print("=" * 40)
    
    # Test basic endpoints
    try:
        test_api()
    except requests.exceptions.ConnectionError:
        print("API server is not running. Please start it with:")
        print("python -m table_extraction.api")
        return
    
    # Example file upload (uncomment and modify as needed)
    # upload_and_extract("example.pdf")


if __name__ == "__main__":
    main()
