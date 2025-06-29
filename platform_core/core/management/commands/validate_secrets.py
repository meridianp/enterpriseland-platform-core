"""
Django management command to validate secret configuration and security.

This command checks for hardcoded secrets, validates environment configuration,
and provides recommendations for security improvements.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Any

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from platform_core.core.settings.secrets import secrets, generate_secret_key, generate_jwt_key


class Command(BaseCommand):
    help = 'Validate secret configuration and security settings'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Automatically fix some issues where possible',
        )
        parser.add_argument(
            '--rotate',
            action='store_true',
            help='Generate new secrets for rotation',
        )
        parser.add_argument(
            '--environment',
            type=str,
            default='development',
            help='Environment to validate (development, staging, production)',
        )
        parser.add_argument(
            '--check-git',
            action='store_true',
            help='Check git history for committed secrets',
        )

    def handle(self, *args, **options):
        self.verbosity = options['verbosity']
        self.fix = options['fix']
        self.rotate = options['rotate']
        self.environment = options['environment']
        self.check_git = options['check_git']
        
        self.stdout.write(
            self.style.SUCCESS('🔐 Starting security validation...\n')
        )
        
        issues_found = []
        
        # 1. Validate secrets configuration
        issues_found.extend(self.validate_secrets())
        
        # 2. Check for hardcoded secrets in code
        issues_found.extend(self.check_hardcoded_secrets())
        
        # 3. Validate environment configuration
        issues_found.extend(self.validate_environment())
        
        # 4. Check git history for secrets (if requested)
        if self.check_git:
            issues_found.extend(self.check_git_history())
        
        # 5. Generate rotation recommendations
        if self.rotate:
            self.generate_rotation_keys()
        
        # Summary
        self.print_summary(issues_found)
        
        if issues_found:
            raise CommandError(f"Found {len(issues_found)} security issues")

    def validate_secrets(self) -> List[Dict[str, Any]]:
        """Validate the secrets configuration."""
        self.stdout.write('📋 Validating secrets configuration...')
        
        issues = []
        
        try:
            # Get validation report
            report = secrets.get_validation_report()
            
            # Check errors
            for error in report['errors']:
                issues.append({
                    'type': 'error',
                    'category': 'secrets',
                    'message': error,
                    'fix': 'Set the required environment variable'
                })
                self.stdout.write(
                    self.style.ERROR(f'  ❌ ERROR: {error}')
                )
            
            # Check warnings
            for warning in report['warnings']:
                issues.append({
                    'type': 'warning',
                    'category': 'secrets',
                    'message': warning,
                    'fix': 'Consider improving the secret quality'
                })
                self.stdout.write(
                    self.style.WARNING(f'  ⚠️  WARNING: {warning}')
                )
            
            # Check rotation needed
            rotation_needed = secrets.check_rotation_needed()
            for item in rotation_needed:
                issues.append({
                    'type': 'warning',
                    'category': 'rotation',
                    'message': f'Secret rotation recommended: {item}',
                    'fix': 'Rotate the secret using --rotate option'
                })
                self.stdout.write(
                    self.style.WARNING(f'  🔄 ROTATION: {item}')
                )
            
            if not issues:
                self.stdout.write(
                    self.style.SUCCESS('  ✅ All secrets properly configured')
                )
                
        except Exception as e:
            issues.append({
                'type': 'error',
                'category': 'secrets',
                'message': f'Failed to validate secrets: {str(e)}',
                'fix': 'Check secrets configuration'
            })
            self.stdout.write(
                self.style.ERROR(f'  ❌ ERROR: Failed to validate secrets: {str(e)}')
            )
        
        return issues

    def check_hardcoded_secrets(self) -> List[Dict[str, Any]]:
        """Check for hardcoded secrets in the codebase."""
        self.stdout.write('🔍 Checking for hardcoded secrets...')
        
        issues = []
        backend_dir = Path(settings.BASE_DIR)
        
        # Patterns to look for
        secret_patterns = [
            (r'SECRET_KEY\s*=\s*["\'](?!django-insecure-test-key)[^"\']{20,}["\']', 'Hardcoded SECRET_KEY'),
            (r'JWT_SECRET_KEY\s*=\s*["\'][^"\']{20,}["\']', 'Hardcoded JWT_SECRET_KEY'),
            (r'AWS_SECRET_ACCESS_KEY\s*=\s*["\'][^"\']{20,}["\']', 'Hardcoded AWS secret'),
            (r'(?:password|pwd)\s*=\s*["\'][^"\']{8,}["\']', 'Hardcoded password'),
            (r'(?:api_key|apikey)\s*=\s*["\'][^"\']{20,}["\']', 'Hardcoded API key'),
            (r'(?:private_key|privatekey)\s*=\s*["\'][^"\']{50,}["\']', 'Hardcoded private key'),
        ]
        
        # Files to check - exclude test files, migrations, and venv
        excluded_patterns = [
            'test_', 'tests.py', 'validate_secrets.py', 'secrets.py',
            'migrations', '__pycache__', 'venv', '.pytest_cache',
            'node_modules', '.git', 'site-packages'
        ]
        
        python_files = []
        config_files = []
        
        for file_path in backend_dir.rglob('*.py'):
            # Skip if any excluded pattern is in the path
            if any(pattern in str(file_path) for pattern in excluded_patterns):
                continue
            python_files.append(file_path)
        
        for pattern in ['*.json', '*.yaml', '*.yml']:
            for file_path in backend_dir.rglob(pattern):
                # Skip if any excluded pattern is in the path
                if any(excl_pattern in str(file_path) for excl_pattern in excluded_patterns):
                    continue
                config_files.append(file_path)
        
        all_files = python_files + config_files
        
        for file_path in all_files:
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for pattern, description in secret_patterns:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        line_num = content[:match.start()].count('\n') + 1
                        issues.append({
                            'type': 'error',
                            'category': 'hardcoded',
                            'message': f'{description} found in {file_path}:{line_num}',
                            'fix': 'Move secret to environment variable'
                        })
                        self.stdout.write(
                            self.style.ERROR(
                                f'  ❌ {description} in {file_path}:{line_num}'
                            )
                        )
                        
            except (UnicodeDecodeError, PermissionError):
                # Skip binary files or files we can't read
                continue
        
        if not issues:
            self.stdout.write(
                self.style.SUCCESS('  ✅ No hardcoded secrets found')
            )
        
        return issues

    def validate_environment(self) -> List[Dict[str, Any]]:
        """Validate environment-specific settings."""
        self.stdout.write(f'🌍 Validating {self.environment} environment...')
        
        issues = []
        
        # Production-specific checks
        if self.environment == 'production':
            prod_checks = [
                ('DEBUG', False, 'DEBUG should be False in production'),
                ('ALLOWED_HOSTS', lambda x: x != ['*'], 'ALLOWED_HOSTS should not be wildcard in production'),
                ('SECURE_SSL_REDIRECT', True, 'SSL redirect should be enabled in production'),
                ('SECURE_HSTS_SECONDS', lambda x: x > 0, 'HSTS should be enabled in production'),
                ('SECURE_CONTENT_TYPE_NOSNIFF', True, 'Content type nosniff should be enabled'),
                ('SECURE_BROWSER_XSS_FILTER', True, 'XSS filter should be enabled'),
                ('X_FRAME_OPTIONS', lambda x: x in ['DENY', 'SAMEORIGIN'], 'X-Frame-Options should be restrictive'),
            ]
            
            for setting_name, expected, message in prod_checks:
                value = getattr(settings, setting_name, None)
                
                if callable(expected):
                    is_valid = expected(value)
                else:
                    is_valid = value == expected
                
                if not is_valid:
                    issues.append({
                        'type': 'error',
                        'category': 'environment',
                        'message': f'{message} (current: {value})',
                        'fix': f'Set {setting_name} properly for production'
                    })
                    self.stdout.write(
                        self.style.ERROR(f'  ❌ {message}')
                    )
        
        # Check CORS settings
        cors_origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', [])
        if '*' in cors_origins or getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False):
            if self.environment == 'production':
                issues.append({
                    'type': 'error',
                    'category': 'environment',
                    'message': 'CORS allows all origins in production',
                    'fix': 'Restrict CORS to specific origins'
                })
                self.stdout.write(
                    self.style.ERROR('  ❌ CORS allows all origins in production')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'  ⚠️  CORS allows all origins in {self.environment}')
                )
        
        if not issues:
            self.stdout.write(
                self.style.SUCCESS(f'  ✅ {self.environment} environment properly configured')
            )
        
        return issues

    def check_git_history(self) -> List[Dict[str, Any]]:
        """Check git history for committed secrets."""
        self.stdout.write('📜 Checking git history for secrets...')
        
        issues = []
        
        try:
            # Use git log to search for potential secrets
            secret_patterns = [
                'SECRET_KEY',
                'PASSWORD',
                'API_KEY',
                'PRIVATE_KEY',
                'ACCESS_TOKEN',
                'AWS_SECRET_ACCESS_KEY',
            ]
            
            for pattern in secret_patterns:
                try:
                    result = subprocess.run(
                        ['git', 'log', '--all', '-S', pattern, '--oneline'],
                        cwd=settings.BASE_DIR,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if result.returncode == 0 and result.stdout.strip():
                        commits = result.stdout.strip().split('\n')
                        for commit in commits:
                            if commit.strip():
                                issues.append({
                                    'type': 'warning',
                                    'category': 'git_history',
                                    'message': f'Potential secret "{pattern}" found in commit: {commit}',
                                    'fix': 'Review commit and consider history rewriting if needed'
                                })
                                self.stdout.write(
                                    self.style.WARNING(f'  ⚠️  Secret in commit: {commit}')
                                )
                
                except subprocess.TimeoutExpired:
                    self.stdout.write(
                        self.style.WARNING('  ⚠️  Git history check timed out')
                    )
                    break
                    
        except FileNotFoundError:
            self.stdout.write(
                self.style.WARNING('  ⚠️  Git not available for history check')
            )
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'  ⚠️  Git history check failed: {str(e)}')
            )
        
        if not issues:
            self.stdout.write(
                self.style.SUCCESS('  ✅ No obvious secrets in git history')
            )
        
        return issues

    def generate_rotation_keys(self):
        """Generate new keys for rotation."""
        self.stdout.write('🔑 Generating new keys for rotation...\n')
        
        # Generate new Django secret key
        new_secret_key = generate_secret_key()
        self.stdout.write(
            self.style.SUCCESS(f'New SECRET_KEY: {new_secret_key}')
        )
        
        # Generate new JWT secret key
        new_jwt_key = generate_jwt_key()
        self.stdout.write(
            self.style.SUCCESS(f'New JWT_SECRET_KEY: {new_jwt_key}')
        )
        
        self.stdout.write('\n📝 To rotate these secrets:')
        self.stdout.write('1. Update your environment variables or .env file')
        self.stdout.write('2. Deploy the changes')
        self.stdout.write('3. Restart all application instances')
        self.stdout.write('4. Verify all services are working')
        self.stdout.write('5. Invalidate old sessions/tokens if needed\n')

    def print_summary(self, issues: List[Dict[str, Any]]):
        """Print a summary of all issues found."""
        self.stdout.write('\n' + '='*60)
        self.stdout.write('📊 SECURITY VALIDATION SUMMARY')
        self.stdout.write('='*60)
        
        if not issues:
            self.stdout.write(
                self.style.SUCCESS('🎉 No security issues found! Your configuration looks good.')
            )
            return
        
        # Group issues by type
        errors = [i for i in issues if i['type'] == 'error']
        warnings = [i for i in issues if i['type'] == 'warning']
        
        self.stdout.write(f'\n📈 Total Issues: {len(issues)}')
        self.stdout.write(f'❌ Errors: {len(errors)}')
        self.stdout.write(f'⚠️  Warnings: {len(warnings)}')
        
        # Group by category
        categories = {}
        for issue in issues:
            cat = issue['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(issue)
        
        self.stdout.write('\n📋 Issues by Category:')
        for category, cat_issues in categories.items():
            self.stdout.write(f'  {category}: {len(cat_issues)} issues')
        
        # Priority recommendations
        self.stdout.write('\n🎯 Priority Actions:')
        
        critical_issues = [i for i in errors if i['category'] in ['secrets', 'hardcoded']]
        if critical_issues:
            self.stdout.write(
                self.style.ERROR(f'  1. Fix {len(critical_issues)} critical secret issues immediately')
            )
        
        env_issues = [i for i in errors if i['category'] == 'environment']
        if env_issues:
            self.stdout.write(
                self.style.ERROR(f'  2. Fix {len(env_issues)} environment configuration issues')
            )
        
        rotation_issues = [i for i in issues if i['category'] == 'rotation']
        if rotation_issues:
            self.stdout.write(
                self.style.WARNING(f'  3. Consider rotating {len(rotation_issues)} secrets')
            )
        
        self.stdout.write('\n💡 Use --rotate to generate new keys for rotation')
        self.stdout.write('💡 Use --fix to automatically fix some issues (when available)')
        self.stdout.write('='*60)