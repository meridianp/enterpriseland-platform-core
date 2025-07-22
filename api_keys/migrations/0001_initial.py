# Generated manually for API keys app

import django.contrib.postgres.fields
import django.core.validators
from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('accounts', '0003_add_security_models'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='APIKey',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(help_text='Descriptive name for the API key', max_length=255)),
                ('key_hash', models.CharField(db_index=True, help_text='SHA-256 hash of the API key', max_length=64, unique=True)),
                ('key_prefix', models.CharField(help_text='First 8 characters for identification', max_length=8)),
                ('application_name', models.CharField(blank=True, help_text='Application using this key (for app-level keys)', max_length=255)),
                ('scopes', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(choices=[('read', 'Read Access'), ('write', 'Write Access'), ('delete', 'Delete Access'), ('admin', 'Admin Access'), ('assessments:read', 'Read Assessments'), ('assessments:write', 'Write Assessments'), ('leads:read', 'Read Leads'), ('leads:write', 'Write Leads'), ('market_intel:read', 'Read Market Intelligence'), ('market_intel:write', 'Write Market Intelligence'), ('deals:read', 'Read Deals'), ('deals:write', 'Write Deals'), ('contacts:read', 'Read Contacts'), ('contacts:write', 'Write Contacts'), ('files:read', 'Read Files'), ('files:write', 'Write Files'), ('files:delete', 'Delete Files')], max_length=50), default=list, help_text='List of permitted scopes', size=None)),
                ('expires_at', models.DateTimeField(help_text='When this key expires')),
                ('is_active', models.BooleanField(default=True, help_text='Whether this key is currently active')),
                ('allowed_ips', django.contrib.postgres.fields.ArrayField(base_field=models.GenericIPAddressField(), blank=True, default=list, help_text='List of allowed IP addresses (empty = all allowed)', size=None)),
                ('rate_limit_per_hour', models.IntegerField(default=1000, help_text='Maximum requests per hour', validators=[django.core.validators.MinValueValidator(0)])),
                ('last_used_at', models.DateTimeField(blank=True, help_text='Last time this key was used', null=True)),
                ('usage_count', models.BigIntegerField(default=0, help_text='Total number of times used')),
                ('metadata', models.JSONField(blank=True, default=dict, help_text='Additional metadata')),
                ('rotation_reminder_sent', models.BooleanField(default=False, help_text='Whether rotation reminder was sent')),
                ('group', models.ForeignKey(blank=True, help_text='Group this key belongs to', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='api_keys', to='accounts.group')),
                ('replaced_by', models.ForeignKey(blank=True, help_text='New key that replaces this one', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='replaces', to='api_keys.apikey')),
                ('user', models.ForeignKey(blank=True, help_text='User who owns this key', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='api_keys', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'API Key',
                'verbose_name_plural': 'API Keys',
                'db_table': 'api_keys',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='APIKeyUsage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('endpoint', models.CharField(help_text='API endpoint accessed', max_length=255)),
                ('method', models.CharField(help_text='HTTP method used', max_length=10)),
                ('status_code', models.IntegerField(help_text='Response status code')),
                ('ip_address', models.GenericIPAddressField(help_text='IP address of the request')),
                ('user_agent', models.TextField(blank=True, help_text='User agent string')),
                ('response_time_ms', models.IntegerField(help_text='Response time in milliseconds')),
                ('error_message', models.TextField(blank=True, help_text='Error message if request failed')),
                ('api_key', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='usage_logs', to='api_keys.apikey')),
            ],
            options={
                'verbose_name': 'API Key Usage',
                'verbose_name_plural': 'API Key Usage Logs',
                'db_table': 'api_key_usage',
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='apikeyusage',
            index=models.Index(fields=['api_key', 'timestamp'], name='api_key_usa_api_key_68a2e4_idx'),
        ),
        migrations.AddIndex(
            model_name='apikeyusage',
            index=models.Index(fields=['timestamp', 'status_code'], name='api_key_usa_timesta_00d75c_idx'),
        ),
        migrations.AddIndex(
            model_name='apikeyusage',
            index=models.Index(fields=['endpoint', 'timestamp'], name='api_key_usa_endpoin_a58866_idx'),
        ),
        migrations.AddIndex(
            model_name='apikey',
            index=models.Index(fields=['key_hash', 'is_active'], name='api_keys_key_has_e9ee2e_idx'),
        ),
        migrations.AddIndex(
            model_name='apikey',
            index=models.Index(fields=['user', 'is_active'], name='api_keys_user_id_22d6a5_idx'),
        ),
        migrations.AddIndex(
            model_name='apikey',
            index=models.Index(fields=['expires_at', 'is_active'], name='api_keys_expires_1b5cd1_idx'),
        ),
        migrations.AddIndex(
            model_name='apikey',
            index=models.Index(fields=['application_name', 'is_active'], name='api_keys_applica_9fa18e_idx'),
        ),
        migrations.AddIndex(
            model_name='apikey',
            index=models.Index(fields=['group', 'is_active'], name='api_keys_group_i_9c1d8c_idx'),
        ),
        migrations.AddIndex(
            model_name='apikey',
            index=models.Index(fields=['last_used_at'], name='api_keys_last_us_dff0f1_idx'),
        ),
    ]