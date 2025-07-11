# Generated by Django 4.2.7 on 2025-06-28 17:43

from django.conf import settings
import django.core.serializers.json
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('contenttypes', '0002_remove_content_type_name'),
        ('accounts', '0003_add_security_models'),
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('action', models.CharField(choices=[('CREATE', 'Create'), ('READ', 'Read'), ('UPDATE', 'Update'), ('DELETE', 'Delete'), ('BULK_CREATE', 'Bulk Create'), ('BULK_UPDATE', 'Bulk Update'), ('BULK_DELETE', 'Bulk Delete'), ('LOGIN', 'Login'), ('LOGOUT', 'Logout'), ('LOGIN_FAILED', 'Login Failed'), ('PASSWORD_CHANGE', 'Password Change'), ('PERMISSION_CHANGE', 'Permission Change'), ('ADMIN_ACCESS', 'Admin Access'), ('SETTINGS_CHANGE', 'Settings Change'), ('USER_ACTIVATION', 'User Activation'), ('USER_DEACTIVATION', 'User Deactivation'), ('EXPORT', 'Data Export'), ('IMPORT', 'Data Import'), ('BACKUP', 'Data Backup'), ('RESTORE', 'Data Restore'), ('FILE_UPLOAD', 'File Upload'), ('FILE_DOWNLOAD', 'File Download'), ('FILE_DELETE', 'File Delete'), ('API_ACCESS', 'API Access'), ('API_ERROR', 'API Error'), ('RATE_LIMIT', 'Rate Limit Exceeded')], db_index=True, help_text='Type of action performed', max_length=50)),
                ('object_id', models.CharField(blank=True, help_text='ID of the object affected', max_length=255, null=True)),
                ('model_name', models.CharField(blank=True, db_index=True, help_text='Name of the model affected', max_length=100, null=True)),
                ('changes', models.JSONField(default=dict, encoder=django.core.serializers.json.DjangoJSONEncoder, help_text='JSON object containing the changes made')),
                ('ip_address', models.GenericIPAddressField(blank=True, help_text='IP address of the request', null=True)),
                ('user_agent', models.TextField(blank=True, help_text='User agent string from the request', null=True)),
                ('metadata', models.JSONField(default=dict, encoder=django.core.serializers.json.DjangoJSONEncoder, help_text='Additional context and metadata')),
                ('success', models.BooleanField(default=True, help_text='Whether the action was successful')),
                ('error_message', models.TextField(blank=True, help_text='Error message if action failed', null=True)),
                ('content_type', models.ForeignKey(blank=True, help_text='Type of object affected', null=True, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype')),
                ('group', models.ForeignKey(blank=True, help_text='Group context for the action', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='audit_logs', to='accounts.group')),
                ('user', models.ForeignKey(blank=True, help_text='User who performed the action', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Audit Log',
                'verbose_name_plural': 'Audit Logs',
                'db_table': 'audit_logs',
                'ordering': ['-timestamp'],
            },
        ),
        migrations.CreateModel(
            name='SystemMetrics',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('metric_type', models.CharField(choices=[('PERFORMANCE', 'Performance'), ('SECURITY', 'Security'), ('USAGE', 'Usage'), ('ERROR', 'Error'), ('BUSINESS', 'Business')], db_index=True, max_length=20)),
                ('metric_name', models.CharField(db_index=True, help_text='Name of the metric', max_length=100)),
                ('value', models.DecimalField(decimal_places=6, help_text='Numeric value of the metric', max_digits=15)),
                ('unit', models.CharField(help_text='Unit of measurement (seconds, bytes, count, etc.)', max_length=20)),
                ('metadata', models.JSONField(default=dict, help_text='Additional metric metadata and tags')),
                ('group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='metrics', to='accounts.group')),
            ],
            options={
                'verbose_name': 'System Metric',
                'verbose_name_plural': 'System Metrics',
                'db_table': 'system_metrics',
                'ordering': ['-timestamp'],
                'indexes': [models.Index(fields=['metric_type', 'metric_name', 'timestamp'], name='system_metr_metric__9fb90b_idx'), models.Index(fields=['group', 'timestamp'], name='system_metr_group_i_f8e15f_idx'), models.Index(fields=['timestamp', 'value'], name='system_metr_timesta_151005_idx')],
            },
        ),
        migrations.CreateModel(
            name='AuditLogEntry',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('field_name', models.CharField(help_text='Name of the field that changed', max_length=100)),
                ('field_type', models.CharField(help_text='Type of the field (CharField, IntegerField, etc.)', max_length=50)),
                ('old_value', models.TextField(blank=True, help_text='Previous value (JSON serialized)', null=True)),
                ('new_value', models.TextField(blank=True, help_text='New value (JSON serialized)', null=True)),
                ('is_sensitive', models.BooleanField(default=False, help_text='Whether this field contains sensitive data')),
                ('change_reason', models.CharField(blank=True, help_text='Reason for the change', max_length=255, null=True)),
                ('audit_log', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='core.auditlog')),
            ],
            options={
                'verbose_name': 'Audit Log Entry',
                'verbose_name_plural': 'Audit Log Entries',
                'db_table': 'audit_log_entries',
                'ordering': ['field_name'],
                'indexes': [models.Index(fields=['audit_log', 'field_name'], name='audit_log_e_audit_l_7ff381_idx'), models.Index(fields=['field_name', 'is_sensitive'], name='audit_log_e_field_n_4a7aae_idx')],
                'unique_together': {('audit_log', 'field_name')},
            },
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['timestamp', 'action'], name='audit_logs_timesta_05ea8c_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['user', 'timestamp'], name='audit_logs_user_id_88267f_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['model_name', 'timestamp'], name='audit_logs_model_n_764981_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['group', 'timestamp'], name='audit_logs_group_i_d4d9e6_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['content_type', 'object_id'], name='audit_logs_content_b0ef47_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['ip_address', 'timestamp'], name='audit_logs_ip_addr_932507_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['action', 'success', 'timestamp'], name='audit_logs_action_036a84_idx'),
        ),
    ]
