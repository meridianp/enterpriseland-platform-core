"""
Provider configuration for external integrations.

This file defines the configuration for all external service providers
used by the application.
"""
from decouple import config

# Provider configuration
PROVIDER_CONFIG = {
    'contact_enrichment': {
        'default': config('DEFAULT_ENRICHMENT_PROVIDER', default='clearbit'),
        'fallback_order': ['clearbit', 'apollo', 'hunter'],
        'providers': {
            'clearbit': {
                'class': 'integrations.providers.enrichment.clearbit.ClearbitProvider',
                'enabled': config('CLEARBIT_ENABLED', default=True, cast=bool),
                'params': {
                    'api_key': config('CLEARBIT_API_KEY', default='')
                },
                'timeout': 30,
                'retry_count': 3,
                'cache_ttl': 86400,  # 24 hours
                'circuit_breaker_threshold': 5,
                'circuit_breaker_timeout': 60,
                'rate_limits': {
                    'requests_per_minute': 600,
                    'requests_per_hour': 12000,
                    'concurrent_requests': 10
                }
            },
            'apollo': {
                'class': 'integrations.providers.enrichment.apollo.ApolloProvider',
                'enabled': config('APOLLO_ENABLED', default=False, cast=bool),
                'params': {
                    'api_key': config('APOLLO_API_KEY', default='')
                },
                'timeout': 20,
                'retry_count': 2,
                'cache_ttl': 86400,
                'circuit_breaker_threshold': 5,
                'circuit_breaker_timeout': 60,
                'rate_limits': {
                    'requests_per_minute': 300,
                    'requests_per_hour': 6000,
                    'concurrent_requests': 5
                }
            },
            'hunter': {
                'class': 'integrations.providers.enrichment.hunter.HunterProvider',
                'enabled': config('HUNTER_ENABLED', default=False, cast=bool),
                'params': {
                    'api_key': config('HUNTER_API_KEY', default='')
                },
                'timeout': 15,
                'retry_count': 2,
                'cache_ttl': 86400,
                'circuit_breaker_threshold': 3,
                'circuit_breaker_timeout': 120,
                'rate_limits': {
                    'requests_per_minute': 50,
                    'requests_per_hour': 1000,
                    'concurrent_requests': 2
                }
            }
        }
    },
    'email': {
        'default': config('DEFAULT_EMAIL_PROVIDER', default='sendgrid'),
        'fallback_order': ['sendgrid', 'aws_ses', 'mailgun'],
        'providers': {
            'sendgrid': {
                'class': 'integrations.providers.email.sendgrid.SendGridProvider',
                'enabled': config('SENDGRID_ENABLED', default=True, cast=bool),
                'params': {
                    'api_key': config('SENDGRID_API_KEY', default=''),
                    'from_email': config('DEFAULT_FROM_EMAIL', default='noreply@enterpriseland.com')
                },
                'timeout': 60,
                'retry_count': 3,
                'circuit_breaker_threshold': 10,
                'circuit_breaker_timeout': 300,
                'rate_limits': {
                    'requests_per_minute': 3000,
                    'requests_per_hour': 100000,
                    'concurrent_requests': 100
                }
            },
            'aws_ses': {
                'class': 'integrations.providers.email.aws_ses.SESProvider',
                'enabled': config('AWS_SES_ENABLED', default=False, cast=bool),
                'params': {
                    'region': config('AWS_SES_REGION', default='us-east-1'),
                    'access_key': config('AWS_ACCESS_KEY_ID', default=''),
                    'secret_key': config('AWS_SECRET_ACCESS_KEY', default=''),
                    'from_email': config('DEFAULT_FROM_EMAIL', default='noreply@enterpriseland.com')
                },
                'timeout': 60,
                'retry_count': 3,
                'circuit_breaker_threshold': 10,
                'circuit_breaker_timeout': 300,
                'rate_limits': {
                    'requests_per_minute': 1000,
                    'requests_per_hour': 50000,
                    'concurrent_requests': 50
                }
            },
            'mailgun': {
                'class': 'integrations.providers.email.mailgun.MailgunProvider',
                'enabled': config('MAILGUN_ENABLED', default=False, cast=bool),
                'params': {
                    'api_key': config('MAILGUN_API_KEY', default=''),
                    'domain': config('MAILGUN_DOMAIN', default=''),
                    'from_email': config('DEFAULT_FROM_EMAIL', default='noreply@enterpriseland.com')
                },
                'timeout': 45,
                'retry_count': 2,
                'circuit_breaker_threshold': 5,
                'circuit_breaker_timeout': 180,
                'rate_limits': {
                    'requests_per_minute': 300,
                    'requests_per_hour': 10000,
                    'concurrent_requests': 10
                }
            }
        }
    },
    'calendar': {
        'default': config('DEFAULT_CALENDAR_PROVIDER', default='google'),
        'providers': {
            'google': {
                'class': 'integrations.providers.calendar.google.GoogleCalendarProvider',
                'enabled': config('GOOGLE_CALENDAR_ENABLED', default=False, cast=bool),
                'params': {
                    'client_id': config('GOOGLE_CLIENT_ID', default=''),
                    'client_secret': config('GOOGLE_CLIENT_SECRET', default='')
                },
                'timeout': 30,
                'cache_ttl': 300  # 5 minutes
            },
            'outlook': {
                'class': 'integrations.providers.calendar.outlook.OutlookCalendarProvider',
                'enabled': config('OUTLOOK_CALENDAR_ENABLED', default=False, cast=bool),
                'params': {
                    'client_id': config('OUTLOOK_CLIENT_ID', default=''),
                    'client_secret': config('OUTLOOK_CLIENT_SECRET', default='')
                },
                'timeout': 30,
                'cache_ttl': 300
            }
        }
    },
    'web_research': {
        'default': 'mcp',
        'providers': {
            'mcp': {
                'class': 'integrations.providers.research.mcp.MCPResearchProvider',
                'enabled': config('MCP_ENABLED', default=False, cast=bool),
                'params': {
                    'service_url': config('MCP_SERVICE_URL', default='http://localhost:8080'),
                    'api_key': config('MCP_API_KEY', default='')
                },
                'timeout': 300,  # 5 minutes for research tasks
                'retry_count': 1
            }
        }
    }
}

# Development overrides
if config('DEBUG', default=False, cast=bool):
    # Use console email backend in development
    PROVIDER_CONFIG['email']['default'] = 'console'
    PROVIDER_CONFIG['email']['providers']['console'] = {
        'class': 'integrations.providers.email.console.ConsoleEmailProvider',
        'enabled': True,
        'params': {}
    }
    
    # Enable mock providers for testing
    PROVIDER_CONFIG['contact_enrichment']['providers']['mock'] = {
        'class': 'integrations.testing.MockEnrichmentProvider',
        'enabled': True,
        'params': {
            'fail_rate': 0.0
        },
        'timeout': 5,
        'cache_ttl': 60
    }

# Test environment overrides
if config('TESTING', default=False, cast=bool):
    from integrations.testing import get_test_provider_config
    PROVIDER_CONFIG = get_test_provider_config()