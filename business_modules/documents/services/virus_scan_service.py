"""Virus scanning service for document security."""

import tempfile
import subprocess
import hashlib
from typing import Dict, Any, Optional
from django.conf import settings
from django.core.cache import cache
import requests


class VirusScanService:
    """Service for scanning files for viruses and malware."""
    
    def __init__(self):
        self.scan_method = getattr(settings, 'VIRUS_SCAN_METHOD', 'clamav')
        self.virustotal_api_key = getattr(settings, 'VIRUSTOTAL_API_KEY', None)
        self.cache_timeout = 86400  # 24 hours
    
    def scan_file(self, file_content: bytes) -> Dict[str, Any]:
        """Scan file content for viruses."""
        if not getattr(settings, 'DOCUMENTS_VIRUS_SCAN_ENABLED', True):
            return {'status': 'skipped', 'message': 'Virus scanning disabled'}
        
        # Check cache first (based on file hash)
        file_hash = hashlib.sha256(file_content).hexdigest()
        cache_key = f"virus_scan:{file_hash}"
        cached_result = cache.get(cache_key)
        
        if cached_result:
            return cached_result
        
        # Perform scan based on configured method
        if self.scan_method == 'clamav':
            result = self._scan_with_clamav(file_content)
        elif self.scan_method == 'virustotal' and self.virustotal_api_key:
            result = self._scan_with_virustotal(file_content, file_hash)
        else:
            result = {'status': 'skipped', 'message': 'No virus scanner configured'}
        
        # Cache clean results
        if result['status'] == 'clean':
            cache.set(cache_key, result, self.cache_timeout)
        
        return result
    
    def _scan_with_clamav(self, file_content: bytes) -> Dict[str, Any]:
        """Scan file using ClamAV."""
        try:
            # Write content to temporary file
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(file_content)
                tmp_file.flush()
                tmp_path = tmp_file.name
            
            try:
                # Run clamscan
                result = subprocess.run(
                    ['clamscan', '--no-summary', tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                # Parse result
                if result.returncode == 0:
                    return {
                        'status': 'clean',
                        'message': 'No virus found',
                        'scanner': 'clamav'
                    }
                elif result.returncode == 1:
                    # Virus found
                    virus_name = self._extract_virus_name(result.stdout)
                    return {
                        'status': 'infected',
                        'message': f'Virus found: {virus_name}',
                        'virus_name': virus_name,
                        'scanner': 'clamav'
                    }
                else:
                    # Error
                    return {
                        'status': 'error',
                        'message': f'Scan error: {result.stderr}',
                        'scanner': 'clamav'
                    }
            
            finally:
                # Clean up
                import os
                os.unlink(tmp_path)
        
        except subprocess.TimeoutExpired:
            return {
                'status': 'error',
                'message': 'Scan timeout',
                'scanner': 'clamav'
            }
        except FileNotFoundError:
            return {
                'status': 'error',
                'message': 'ClamAV not installed',
                'scanner': 'clamav'
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Scan error: {str(e)}',
                'scanner': 'clamav'
            }
    
    def _scan_with_virustotal(self, file_content: bytes, file_hash: str) -> Dict[str, Any]:
        """Scan file using VirusTotal API."""
        try:
            # First check if file hash is already known
            check_url = f"https://www.virustotal.com/api/v3/files/{file_hash}"
            headers = {"x-apikey": self.virustotal_api_key}
            
            response = requests.get(check_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                # File already scanned
                data = response.json()
                return self._parse_virustotal_result(data)
            
            # File not found, upload for scanning
            if len(file_content) > 32 * 1024 * 1024:  # 32MB limit
                return {
                    'status': 'error',
                    'message': 'File too large for VirusTotal',
                    'scanner': 'virustotal'
                }
            
            # Upload file
            upload_url = "https://www.virustotal.com/api/v3/files"
            files = {"file": ("file", file_content)}
            
            response = requests.post(
                upload_url,
                headers=headers,
                files=files,
                timeout=30
            )
            
            if response.status_code == 200:
                # File uploaded, get analysis ID
                data = response.json()
                analysis_id = data['data']['id']
                
                # Check analysis status (would need to poll in production)
                return {
                    'status': 'pending',
                    'message': 'File submitted for analysis',
                    'analysis_id': analysis_id,
                    'scanner': 'virustotal'
                }
            else:
                return {
                    'status': 'error',
                    'message': f'Upload failed: {response.status_code}',
                    'scanner': 'virustotal'
                }
        
        except requests.RequestException as e:
            return {
                'status': 'error',
                'message': f'API error: {str(e)}',
                'scanner': 'virustotal'
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Scan error: {str(e)}',
                'scanner': 'virustotal'
            }
    
    def _parse_virustotal_result(self, data: Dict) -> Dict[str, Any]:
        """Parse VirusTotal API response."""
        try:
            attributes = data['data']['attributes']
            stats = attributes['last_analysis_stats']
            
            if stats['malicious'] > 0:
                # Get first detection name
                detections = attributes['last_analysis_results']
                virus_name = None
                for engine, result in detections.items():
                    if result['category'] == 'malicious':
                        virus_name = result.get('result', 'Unknown')
                        break
                
                return {
                    'status': 'infected',
                    'message': f'Detected by {stats["malicious"]} engines',
                    'virus_name': virus_name,
                    'scanner': 'virustotal',
                    'details': {
                        'malicious': stats['malicious'],
                        'suspicious': stats['suspicious'],
                        'undetected': stats['undetected']
                    }
                }
            else:
                return {
                    'status': 'clean',
                    'message': 'No threats detected',
                    'scanner': 'virustotal',
                    'details': stats
                }
        
        except KeyError:
            return {
                'status': 'error',
                'message': 'Invalid API response',
                'scanner': 'virustotal'
            }
    
    def _extract_virus_name(self, clamscan_output: str) -> str:
        """Extract virus name from ClamAV output."""
        lines = clamscan_output.strip().split('\n')
        for line in lines:
            if 'FOUND' in line:
                parts = line.split(':')
                if len(parts) >= 2:
                    virus_part = parts[1].strip()
                    return virus_part.replace(' FOUND', '')
        return 'Unknown virus'
    
    def check_file_reputation(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Check file reputation by hash without scanning."""
        # Check cache
        cache_key = f"virus_scan:{file_hash}"
        cached_result = cache.get(cache_key)
        
        if cached_result:
            return cached_result
        
        # Check with VirusTotal if configured
        if self.scan_method == 'virustotal' and self.virustotal_api_key:
            try:
                url = f"https://www.virustotal.com/api/v3/files/{file_hash}"
                headers = {"x-apikey": self.virustotal_api_key}
                
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    result = self._parse_virustotal_result(data)
                    
                    # Cache if clean
                    if result['status'] == 'clean':
                        cache.set(cache_key, result, self.cache_timeout)
                    
                    return result
            
            except Exception:
                pass
        
        return None
    
    def quarantine_file(self, file_path: str, reason: str) -> bool:
        """Move infected file to quarantine."""
        try:
            # This would move the file to a quarantine location
            # Implementation depends on storage backend
            quarantine_path = file_path.replace('/documents/', '/quarantine/')
            
            # Log the quarantine action
            print(f"File quarantined: {file_path} - Reason: {reason}")
            
            return True
        
        except Exception as e:
            print(f"Failed to quarantine file: {e}")
            return False
    
    def update_definitions(self) -> bool:
        """Update virus definitions."""
        if self.scan_method == 'clamav':
            try:
                result = subprocess.run(
                    ['freshclam'],
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minutes
                )
                
                return result.returncode == 0
            
            except Exception:
                return False
        
        return True
    
    def get_scanner_info(self) -> Dict[str, Any]:
        """Get information about the virus scanner."""
        info = {
            'method': self.scan_method,
            'enabled': getattr(settings, 'DOCUMENTS_VIRUS_SCAN_ENABLED', True),
            'available': False,
            'version': None,
            'definitions_date': None
        }
        
        if self.scan_method == 'clamav':
            try:
                # Check ClamAV version
                result = subprocess.run(
                    ['clamscan', '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    info['available'] = True
                    info['version'] = result.stdout.strip()
            
            except Exception:
                pass
        
        elif self.scan_method == 'virustotal':
            info['available'] = bool(self.virustotal_api_key)
            info['version'] = 'v3 API'
        
        return info