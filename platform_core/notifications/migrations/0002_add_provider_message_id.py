# Generated by Django 4.2.7 on 2025-06-27 14:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailnotification',
            name='provider_message_id',
            field=models.CharField(blank=True, help_text='Message ID from email provider', max_length=255),
        ),
    ]
